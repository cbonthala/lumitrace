"use strict";

// Lumitrace Flash web app. Talks to the Prism it is served from (same origin, session cookie).
// Every capture is saved in IndexedDB first and deleted only after the Prism confirms it, so a
// dropped connection never loses a recording (docs/flash.md → Flash web app).

const $ = (id) => document.getElementById(id);
const DB_NAME = "lumitrace-flash";
const OUTBOX = "outbox";
const SENT_KEY = "lumitrace.sent";
const PLACE_KEY = "lumitrace.place";
const LOCATION_KEY = "lumitrace.useLocation";
const SIGNED_IN_KEY = "lumitrace.signedIn";
const SENT_KEEP_DAYS = 8;
const MIN_RECORDING_MS = 1000;  // a double tap must not start and stop at once

const state = {
  date: "",              // "" = today; otherwise YYYY-MM-DD
  recPhotos: [],
  notePhotos: [],
  recorder: null,
  starting: false,
  recording: null,       // {stream, chunks, started, timer, raf, audioCtx, wakeLock, coords}
  serverCaptures: [],
  pollTimer: null,
  sending: false,
};

// --- small helpers -------------------------------------------------------------------------

const pad = (n) => String(Math.floor(Math.abs(n))).padStart(2, "0");

function isoLocal(d) {
  const off = -d.getTimezoneOffset();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:` +
    `${pad(d.getMinutes())}:${pad(d.getSeconds())}${off >= 0 ? "+" : "-"}${pad(off / 60)}:${pad(off % 60)}`;
}

function localDate(d = new Date()) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function captureId(kind, d) {
  const stamp = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}T` +
    `${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
  const rand = Array.from(crypto.getRandomValues(new Uint8Array(3)), (b) => b.toString(16).padStart(2, "0")).join("");
  return `web-${stamp}-${kind}-${rand}`;
}

function when(iso) {
  const d = new Date(iso);
  const today = localDate();
  const yesterday = localDate(new Date(Date.now() - 86400000));
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const day = localDate(d);
  if (day === today) return `Today ${time}`;
  if (day === yesterday) return `Yesterday ${time}`;
  return `${d.toLocaleDateString([], { weekday: "short" })} ${time}`;
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

let toastTimer = null;
function toast(message, isError = false) {
  const box = $("toast");
  box.textContent = message;
  box.classList.toggle("err", isError);
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.hidden = true; }, isError ? 6000 : 3500);
}

function setConn(kind, text) {
  const conn = $("conn");
  conn.classList.remove("ok", "offline", "bad");
  if (kind) conn.classList.add(kind);
  $("conn-text").textContent = text;
}

// --- API -----------------------------------------------------------------------------------

class HttpError extends Error {
  constructor(status, detail) { super(detail); this.status = status; }
}

async function api(path, options = {}) {
  let resp;
  try {
    resp = await fetch(path, { credentials: "same-origin", ...options });
  } catch (err) {
    setConn("offline", "Offline");
    throw err;
  }
  if (resp.status === 401 && path !== "/login") {
    showSignedOut();
  }
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try { detail = (await resp.json()).detail || detail; } catch { /* not JSON */ }
    if (resp.status >= 500) setConn("bad", "Server problem");
    throw new HttpError(resp.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  setConn("ok", "Connected");
  return resp.status === 204 ? null : resp.json();
}

// --- IndexedDB outbox ----------------------------------------------------------------------

let dbPromise = null;
function db() {
  dbPromise ??= new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(OUTBOX, { keyPath: "capture_id" });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbPromise;
}

async function outbox(mode, fn) {
  const database = await db();
  return new Promise((resolve, reject) => {
    const tx = database.transaction(OUTBOX, mode);
    const result = fn(tx.objectStore(OUTBOX));
    tx.oncomplete = () => resolve(result && "result" in result ? result.result : undefined);
    tx.onerror = () => reject(tx.error);
  });
}

const outboxAll = () => outbox("readonly", (s) => s.getAll());
const outboxPut = (item) => outbox("readwrite", (s) => s.put(item));
const outboxDelete = (id) => outbox("readwrite", (s) => s.delete(id));

// --- what this device sent (previews stay on the device) ----------------------------------

function sentMap() {
  try { return JSON.parse(localStorage.getItem(SENT_KEY)) || {}; } catch { return {}; }
}

function rememberSent(item) {
  const map = sentMap();
  map[item.capture_id] = {
    kind: item.kind, preview: (item.fields.text || "").slice(0, 120), photos: item.photos.length,
    seconds: item.seconds || 0, place: item.fields.place || "", captured_at: item.fields.captured_at,
  };
  const cutoff = Date.now() - SENT_KEEP_DAYS * 86400000;
  for (const [id, v] of Object.entries(map)) {
    if (new Date(v.captured_at).getTime() < cutoff) delete map[id];
  }
  localStorage.setItem(SENT_KEY, JSON.stringify(map));
}

// --- sending -------------------------------------------------------------------------------

function formFor(item) {
  const form = new FormData();
  for (const [key, value] of Object.entries(item.fields)) {
    if (value !== "" && value !== null && value !== undefined) form.append(key, String(value));
  }
  form.append("capture_id", item.capture_id);
  if (item.audio) form.append("audio", item.audio, item.audioName);
  for (const photo of item.photos) form.append("photos", photo.blob, photo.name);
  return form;
}

async function upload(item) {
  const path = item.kind === "recording" ? "/recordings" : "/notes";
  const body = await api(path, { method: "POST", body: formFor(item) });
  await outboxDelete(item.capture_id);
  rememberSent(item);
  return body;
}

async function queueAndSend(item) {
  await outboxPut(item);
  try {
    const body = await upload(item);
    toast(body.message || "Saved.");
  } catch (err) {
    if (err instanceof HttpError && err.status !== 401 && err.status < 500) {
      item.error = err.message;
      await outboxPut(item);
      toast(`Not accepted: ${err.message}`, true);
    } else if (err instanceof HttpError && err.status === 401) {
      toast("Signed out. Sign in again and it will be sent.", true);
    } else {
      toast("Saved on this device. It will be sent when you're back online.");
    }
  }
  await refreshAll();
}

async function flushOutbox() {
  if (state.sending || document.body.dataset.auth !== "in") return;
  state.sending = true;
  try {
    const items = (await outboxAll()).filter((i) => !i.error);
    items.sort((a, b) => a.created - b.created);
    for (const item of items) {
      try {
        await upload(item);
      } catch (err) {
        if (err instanceof HttpError && err.status !== 401 && err.status < 500) {
          item.error = err.message;
          await outboxPut(item);
          continue;
        }
        break;
      }
    }
  } finally {
    state.sending = false;
  }
  await renderBanner();
}

// --- location and date ---------------------------------------------------------------------

function placeName() { return (localStorage.getItem(PLACE_KEY) || "").trim(); }
function useLocation() { return localStorage.getItem(LOCATION_KEY) === "1"; }

function getCoords() {
  if (!useLocation() || !navigator.geolocation) return Promise.resolve(null);
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lat: pos.coords.latitude.toFixed(5), lon: pos.coords.longitude.toFixed(5) }),
      () => resolve(null),
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 600000 },
    );
  });
}

function renderPlace() {
  const name = placeName();
  $("place-text").textContent = name || (useLocation() ? "My location" : "No location");
}

function renderDate() {
  const label = state.date ? dayLabel(state.date) : "today";
  document.querySelectorAll(".date-label").forEach((node) => {
    node.textContent = node.classList.contains("cap") && !state.date ? "Today" : label;
  });
  document.querySelectorAll(".date-input").forEach((input) => {
    input.max = localDate();
    input.value = state.date || localDate();
  });
}

function baseFields(started) {
  return {
    captured_at: isoLocal(started),
    date: state.date && state.date !== localDate(started) ? state.date : "",
    place: placeName(),
  };
}

// --- photos --------------------------------------------------------------------------------

function renderThumbs(listName, containerId, countId) {
  const box = $(containerId);
  box.replaceChildren();
  for (const [index, photo] of state[listName].entries()) {
    const btn = el("button", "thumb");
    btn.type = "button";
    btn.title = "Remove photo";
    const img = el("img");
    img.alt = "";
    img.src = photo.url;
    btn.append(img);
    btn.addEventListener("click", () => {
      URL.revokeObjectURL(photo.url);
      state[listName].splice(index, 1);
      renderThumbs(listName, containerId, countId);
    });
    box.append(btn);
  }
  if (countId) $(countId).textContent = String(state[listName].length);
}

function addPhotos(input, listName, containerId, countId) {
  for (const file of input.files) {
    state[listName].push({ blob: file, name: file.name || "photo.jpg", url: URL.createObjectURL(file) });
  }
  input.value = "";
  renderThumbs(listName, containerId, countId);
}

function takePhotos(listName, containerId, countId) {
  const photos = state[listName].map(({ blob, name }) => ({ blob, name }));
  state[listName].forEach((p) => URL.revokeObjectURL(p.url));
  state[listName] = [];
  renderThumbs(listName, containerId, countId);
  return photos;
}

// --- recording -----------------------------------------------------------------------------

function pickMime() {
  if (!window.MediaRecorder) return null;
  for (const type of ["audio/mp4", "audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"]) {
    if (MediaRecorder.isTypeSupported?.(type)) return type;
  }
  return "";
}

function extensionFor(type) {
  if (type.includes("mp4")) return ".m4a";
  if (type.includes("webm")) return ".webm";
  if (type.includes("ogg")) return ".ogg";
  return ".audio";
}

function drawWave(analyser, canvas) {
  const ctx = canvas.getContext("2d");
  const data = new Uint8Array(analyser.frequencyBinCount);
  const gradient = ctx.createLinearGradient(0, 0, canvas.width, 0);
  [["#8b7cff", 0], ["#4cc9f0", .45], ["#3ddc97", .7], ["#ffb547", 1]].forEach(([c, s]) => gradient.addColorStop(s, c));
  const bars = 46;
  const loop = () => {
    analyser.getByteTimeDomainData(data);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = gradient;
    const step = Math.floor(data.length / bars);
    for (let i = 0; i < bars; i++) {
      let peak = 0;
      for (let j = 0; j < step; j++) peak = Math.max(peak, Math.abs(data[i * step + j] - 128));
      const h = Math.max(4, (peak / 128) * canvas.height * 1.6);
      const x = i * (canvas.width / bars);
      ctx.fillRect(x, (canvas.height - Math.min(h, canvas.height)) / 2, 4, Math.min(h, canvas.height));
    }
    state.recording.raf = requestAnimationFrame(loop);
  };
  loop();
}

function setRecordingUi(on) {
  $("rec-btn").classList.toggle("stop", on);
  $("rec-btn").setAttribute("aria-label", on ? "Stop and send" : "Start recording");
  $("rec-live").hidden = !on;
  $("rec-hint").hidden = !on;
  $("discard-btn").hidden = !on;
  $("rec-idle").hidden = on;
}

function toggleRecording() {
  if (state.starting) return;
  if (!state.recorder) {
    state.starting = true;
    startRecording().finally(() => { state.starting = false; });
  } else if (Date.now() - state.recording.started.getTime() >= MIN_RECORDING_MS) {
    stopRecording();
  }
}

async function startRecording() {
  const mime = pickMime();
  if (mime === null || !navigator.mediaDevices?.getUserMedia) {
    toast("This browser can't record audio. Use Safari on iPhone, or Chrome.", true);
    return;
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    toast("Microphone access was refused. Allow it in the browser settings.", true);
    return;
  }
  const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
  const rec = { stream, chunks: [], started: new Date(), coords: null };
  state.recorder = recorder;
  state.recording = rec;
  recorder.ondataavailable = (e) => { if (e.data && e.data.size) rec.chunks.push(e.data); };
  recorder.start(1000);
  setRecordingUi(true);
  rec.timer = setInterval(() => {
    const s = Math.floor((Date.now() - rec.started.getTime()) / 1000);
    $("timer").textContent = `${pad(s / 60)}:${pad(s % 60)}`;
  }, 250);
  try {
    rec.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const analyser = rec.audioCtx.createAnalyser();
    analyser.fftSize = 1024;
    rec.audioCtx.createMediaStreamSource(stream).connect(analyser);
    drawWave(analyser, $("wave"));
  } catch { /* the waveform is decoration */ }
  try { rec.wakeLock = await navigator.wakeLock?.request("screen"); } catch { /* not supported */ }
  getCoords().then((coords) => { rec.coords = coords; });
}

function stopTracks(rec) {
  clearInterval(rec.timer);
  cancelAnimationFrame(rec.raf);
  rec.stream.getTracks().forEach((t) => t.stop());
  rec.audioCtx?.close().catch(() => {});
  rec.wakeLock?.release().catch(() => {});
  $("timer").textContent = "00:00";
}

function finishRecording() {
  const recorder = state.recorder;
  const rec = state.recording;
  return new Promise((resolve) => {
    recorder.onstop = () => {
      stopTracks(rec);
      resolve(new Blob(rec.chunks, { type: recorder.mimeType || "audio/mp4" }));
    };
    recorder.stop();
  });
}

async function stopRecording() {
  const rec = state.recording;
  $("rec-btn").disabled = true;
  try {
    const blob = await finishRecording();
    state.recorder = null;
    state.recording = null;
    setRecordingUi(false);
    if (!blob.size) {
      toast("Nothing was recorded.", true);
      return;
    }
    const item = {
      capture_id: captureId("rec", rec.started),
      kind: "recording",
      created: Date.now(),
      fields: { ...baseFields(rec.started), ...(rec.coords || {}) },
      audio: blob,
      audioName: `audio${extensionFor(blob.type)}`,
      photos: takePhotos("recPhotos", "rec-thumbs", "rec-photo-count"),
      seconds: Math.round((Date.now() - rec.started.getTime()) / 1000),
    };
    await queueAndSend(item);
  } finally {
    $("rec-btn").disabled = false;
  }
}

async function discardRecording() {
  if (!state.recorder || !confirm("Discard this recording?")) return;
  await finishRecording();
  state.recorder = null;
  state.recording = null;
  setRecordingUi(false);
  toast("Recording discarded.");
}

// --- quick note ----------------------------------------------------------------------------

async function sendNote() {
  const text = $("note-text").value.trim();
  if (!text && !state.notePhotos.length) {
    toast("Write something or add a photo first.", true);
    return;
  }
  const started = new Date();
  $("note-send").disabled = true;
  try {
    const coords = await getCoords();
    const item = {
      capture_id: captureId("note", started),
      kind: "note",
      created: Date.now(),
      fields: { ...baseFields(started), ...(coords || {}), text },
      audio: null,
      photos: takePhotos("notePhotos", "note-thumbs"),
    };
    $("note-text").value = "";
    await queueAndSend(item);
  } finally {
    $("note-send").disabled = false;
  }
}

// --- history, banner and summary -----------------------------------------------------------

const STATUS_CHIP = {
  queued: ["queue", "Queued"],
  processing: ["proc", "Writing journal…"],
  done: ["done", "In journal"],
  failed: ["failed", "Failed · retry"],
};

function describe(kind, local, photos) {
  if (kind === "recording") {
    const seconds = local?.seconds || 0;
    if (!seconds) return ["🎙", "Recording"];
    return ["🎙", seconds < 60 ? `Recording · ${seconds} s` : `Recording · ${Math.round(seconds / 60)} min`];
  }
  if (!local?.preview && photos) return ["🖼", "Photos"];
  return ["📝", "Note"];
}

function dayLabel(day) {
  return new Date(`${day}T12:00:00`).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
}

function captureRow({ kind, capturedAt, entryDate, photos, local, chip, onChip }) {
  const row = el("div", "item");
  const [icon, title] = describe(kind, local, photos);
  row.append(el("div", "ico", icon));
  const meta = el("div", "meta");
  meta.append(el("div", "a", title));
  const bits = [when(capturedAt)];
  if (entryDate && entryDate !== localDate(new Date(capturedAt))) bits.push(`for ${dayLabel(entryDate)}`);
  if (photos) bits.push(`${photos} photo${photos === 1 ? "" : "s"}`);
  if (local?.place) bits.push(local.place);
  if (local?.preview) bits.push(`“${local.preview}”`);
  meta.append(el("div", "b", bits.join(" · ")));
  row.append(meta);
  const status = el(onChip ? "button" : "span", `st ${chip[0]}`, chip[1]);
  if (onChip) {
    status.type = "button";
    status.addEventListener("click", onChip);
  }
  row.append(status);
  return row;
}

async function retryCapture(id) {
  try {
    await api(`/captures/${encodeURIComponent(id)}/retry`, { method: "POST" });
    toast("Trying again.");
  } catch (err) {
    toast(`Retry failed: ${err.message}`, true);
  }
  await refreshCaptures();
}

async function renderCaptures() {
  const box = $("captures");
  const local = sentMap();
  const pending = await outboxAll();
  const rows = [];
  for (const item of pending) {
    rows.push({
      at: item.fields.captured_at,
      node: captureRow({
        kind: item.kind, capturedAt: item.fields.captured_at, entryDate: item.fields.date, photos: item.photos.length,
        local: { preview: (item.fields.text || "").slice(0, 120), seconds: item.seconds, place: item.fields.place },
        chip: item.error ? ["failed", "Not accepted · remove"] : ["offline", "Waiting to send"],
        onChip: item.error ? async () => {
          if (confirm(`The server refused this capture: ${item.error}\n\nRemove it from this device?`)) {
            await outboxDelete(item.capture_id);
            await refreshAll();
          }
        } : null,
      }),
    });
  }
  const seen = new Set(pending.map((i) => i.capture_id));
  for (const c of state.serverCaptures) {
    if (seen.has(c.capture_id)) continue;
    rows.push({
      at: c.captured_at,
      node: captureRow({
        kind: c.kind, capturedAt: c.captured_at, entryDate: c.entry_date, photos: c.photos.length || local[c.capture_id]?.photos || 0,
        local: local[c.capture_id], chip: STATUS_CHIP[c.status] || ["queue", c.status],
        onChip: c.status === "failed" ? () => retryCapture(c.capture_id) : null,
      }),
    });
  }
  rows.sort((a, b) => new Date(b.at) - new Date(a.at));
  box.replaceChildren(...rows.map((r) => r.node));
  $("captures-empty").hidden = rows.length > 0;
}

async function renderBanner() {
  const pending = (await outboxAll()).filter((i) => !i.error);
  $("pending-count").textContent = String(pending.length);
  $("banner").hidden = pending.length === 0;
  $("banner-text").textContent = pending.length === 1
    ? "⏳ 1 capture saved on this device, waiting to send"
    : `⏳ ${pending.length} captures saved on this device, waiting to send`;
}

async function refreshCaptures() {
  try {
    state.serverCaptures = await api("/captures?days=7&limit=50");
  } catch { /* keep the last list */ }
  await renderCaptures();
  const busy = state.serverCaptures.some((c) => c.status === "queued" || c.status === "processing");
  clearTimeout(state.pollTimer);
  state.pollTimer = setTimeout(async () => {
    const wasBusy = busy;
    await refreshCaptures();
    if (wasBusy) refreshSummary();
  }, busy ? 4000 : 30000);
}

async function refreshSummary() {
  try {
    const s = await api("/summary");
    $("stat-days").textContent = `${s.days_logged} / ${s.days}`;
    $("stat-captures").textContent = String(s.captures);
    $("stat-streak").textContent = s.streak ? `🔥 ${s.streak}` : "0";
    const dots = $("week-dots");
    dots.replaceChildren();
    const logged = new Set(s.logged_dates);
    const today = new Date(`${s.today}T12:00:00`);
    for (let n = s.days - 1; n >= 0; n--) {
      const d = new Date(today.getTime() - n * 86400000);
      const cell = el("div", logged.has(localDate(d)) ? "on" : "");
      cell.append(el("i"), document.createTextNode(d.toLocaleDateString([], { weekday: "narrow" })));
      dots.append(cell);
    }
  } catch { /* offline: keep the last numbers */ }
}

async function refreshAll() {
  await renderBanner();
  await refreshCaptures();
  refreshSummary();
}

// --- sign-in -------------------------------------------------------------------------------

function showSignedOut() {
  localStorage.removeItem(SIGNED_IN_KEY);
  document.body.dataset.auth = "out";
  setConn("bad", "Signed out");
  setTimeout(() => $("username").focus(), 50);
}

function showSignedIn(info) {
  localStorage.setItem(SIGNED_IN_KEY, "1");
  document.body.dataset.auth = "in";
  if (info) {
    $("who").textContent = info.username || "";
    $("version").textContent = info.version || "–";
  }
  renderDate();
  renderPlace();
  refreshAll().then(flushOutbox);
}

async function checkSession() {
  try {
    const info = await api("/session");
    if (info.signed_in) {
      showSignedIn(info);
    } else {
      showSignedOut();
      if (!info.sign_in_available) {
        $("login-msg").textContent =
          "Sign-in is not set up on the server yet: set LUMITRACE_FLASH_USERNAME and LUMITRACE_FLASH_PASSWORD.";
      }
    }
  } catch {
    if (localStorage.getItem(SIGNED_IN_KEY)) {
      showSignedIn(null);
      setConn("offline", "Offline");
    } else {
      document.body.dataset.auth = "out";
      $("login-msg").textContent = "Can't reach the server. Check your connection (or VPN).";
    }
  }
}

async function login(event) {
  event.preventDefault();
  $("login-btn").disabled = true;
  $("login-msg").textContent = "";
  try {
    const info = await api("/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: $("username").value, password: $("password").value }),
    });
    $("password").value = "";
    showSignedIn(info);
  } catch (err) {
    $("login-msg").textContent = err instanceof HttpError
      ? err.message.charAt(0).toUpperCase() + err.message.slice(1)
      : "Can't reach the server. Check your connection (or VPN).";
  } finally {
    $("login-btn").disabled = false;
  }
}

async function logout() {
  const pending = (await outboxAll()).length;
  if (pending && !confirm(`${pending} capture(s) are still waiting to send. They stay on this device. Sign out?`)) return;
  try { await api("/logout", { method: "POST" }); } catch { /* signed out locally anyway */ }
  showSignedOut();
}

// --- wiring --------------------------------------------------------------------------------

function go(tab) {
  document.body.dataset.tab = tab;
  window.scrollTo(0, 0);
}

function wire() {
  $("login-form").addEventListener("submit", login);
  $("logout").addEventListener("click", logout);
  $("gear").addEventListener("click", () => go(document.body.dataset.tab === "settings" ? "capture" : "settings"));
  document.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => go(b.dataset.go)));

  $("rec-btn").addEventListener("click", toggleRecording);
  $("discard-btn").addEventListener("click", discardRecording);
  $("rec-photos").addEventListener("change", (e) => addPhotos(e.target, "recPhotos", "rec-thumbs", "rec-photo-count"));
  $("note-photos").addEventListener("change", (e) => addPhotos(e.target, "notePhotos", "note-thumbs"));
  $("note-send").addEventListener("click", sendNote);
  $("send-now").addEventListener("click", async () => { await flushOutbox(); await refreshAll(); });

  document.querySelectorAll(".date-input").forEach((input) => {
    input.addEventListener("click", () => { try { input.showPicker?.(); } catch { /* iOS opens it itself */ } });
    input.addEventListener("change", () => {
      state.date = input.value && input.value !== localDate() ? input.value : "";
      renderDate();
    });
  });

  $("place-input").value = placeName();
  $("place-input").addEventListener("input", (e) => { localStorage.setItem(PLACE_KEY, e.target.value); renderPlace(); });
  $("use-location").checked = useLocation();
  $("use-location").addEventListener("change", (e) => {
    localStorage.setItem(LOCATION_KEY, e.target.checked ? "1" : "0");
    renderPlace();
    if (e.target.checked) getCoords();
  });
  $("clear-history").addEventListener("click", () => {
    localStorage.removeItem(SENT_KEY);
    renderCaptures();
    toast("Sent history forgotten on this device.");
  });

  window.addEventListener("online", () => flushOutbox().then(refreshAll));
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && document.body.dataset.auth === "in") {
      renderDate();
      flushOutbox().then(refreshAll);
    }
  });
  window.addEventListener("beforeunload", (e) => { if (state.recorder) e.preventDefault(); });
  setInterval(flushOutbox, 60000);

  const now = new Date();
  $("today-label").textContent =
    `${now.toLocaleDateString([], { weekday: "long" })} · ${now.toLocaleDateString([], { month: "short", day: "numeric" })}`;
}

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => { /* works without it, just not offline */ });
}
wire();
checkSession();
