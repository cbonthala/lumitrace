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
  recorder: null,
  starting: false,
  phase: "idle",         // idle | recording | paused | review
  recording: null,       // {stream, chunks, started, elapsed, segmentStart, paused, timer, raf, audioCtx, analyser, wakeLock, coords}
  review: null,          // held take: blob, audio element, crop start/end, decode buffer
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
    // A Lens problem is shown in its own card, not as a Prism problem.
    if (resp.status >= 500 && !path.startsWith("/lens/")) setConn("bad", "Server problem");
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
  if (countId === "rec-photo-count") syncCardSend();
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

const CROP_EDGE = 0.15; // this close to both ends counts as the whole take
const MIN_CROP = 0.3;

function clock(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${pad(s % 60)}`;
}

function recordedMs(rec) {
  if (rec.paused) return rec.elapsed;
  return rec.elapsed + (Date.now() - rec.segmentStart);
}

function drawWave(analyser, canvas) {
  const ctx = canvas.getContext("2d");
  const data = new Uint8Array(analyser.frequencyBinCount);
  const gradient = ctx.createLinearGradient(0, 0, canvas.width, 0);
  [["#8b7cff", 0], ["#4cc9f0", .45], ["#3ddc97", .7], ["#ffb547", 1]].forEach(([c, s]) => gradient.addColorStop(s, c));
  const bars = 46;
  const loop = () => {
    if (!state.recording || state.phase !== "recording") return;
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

function setRecPhase(phase) {
  state.phase = phase;
  const live = phase === "recording" || phase === "paused";
  const canPause = typeof state.recorder?.pause === "function";
  $("rec-btn").hidden = phase === "review";
  $("rec-btn").classList.toggle("stop", live);
  $("rec-btn").setAttribute("aria-label", live ? "Stop recording" : "Start recording");
  $("rec-live").hidden = !live;
  $("rec-hint").hidden = !live;
  $("rec-idle").hidden = phase !== "idle";
  $("rec-controls").hidden = !live;
  $("discard-btn").hidden = !live;
  $("pause-btn").hidden = !(live && canPause);
  $("pause-btn").classList.toggle("is-resume", phase === "paused");
  $("pause-btn").setAttribute("aria-label", phase === "paused" ? "Resume recording" : "Pause recording");
  $("rec-state").textContent = phase === "paused" ? "Paused" : "● Recording";
  $("rec-state").classList.toggle("paused", phase === "paused");
  $("rec-review").hidden = phase !== "review";
  syncCardSend();
}

function setPlayIcon(playing) {
  $("play-btn").classList.toggle("is-playing", !!playing);
  $("play-btn").setAttribute("aria-label", playing ? "Pause playback" : "Play");
}

function syncCardSend() {
  const btn = $("card-send");
  if (!btn) return;
  const live = state.phase === "recording" || state.phase === "paused";
  $("rec-foot").hidden = live;
  const busy = btn.dataset.busy === "1";
  if (!busy) $("card-send-label").textContent = "Send";
  if (state.phase === "review") {
    btn.disabled = busy || !state.review?.ready;
    btn.setAttribute("aria-label", "Send recording");
  } else {
    btn.disabled = busy || state.recPhotos.length === 0;
    btn.setAttribute("aria-label", "Send photos");
  }
}

function toggleRecording() {
  if (state.starting || state.phase === "review") return;
  if (!state.recorder) {
    state.starting = true;
    startRecording().finally(() => { state.starting = false; });
  } else if (Date.now() - state.recording.started.getTime() >= MIN_RECORDING_MS) {
    stopRecording();
  }
}

function togglePause() {
  const rec = state.recording;
  const recorder = state.recorder;
  if (!rec || !recorder || state.phase === "review") return;
  try {
    if (rec.paused) {
      recorder.resume();
      rec.paused = false;
      rec.segmentStart = Date.now();
      if (rec.analyser) drawWave(rec.analyser, $("wave"));
      setRecPhase("recording");
    } else {
      rec.elapsed += Date.now() - rec.segmentStart;
      recorder.pause();
      rec.paused = true;
      cancelAnimationFrame(rec.raf);
      setRecPhase("paused");
    }
  } catch {
    toast("Couldn't pause. Stop, then send or discard.", true);
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
  const started = new Date();
  let recorder;
  try {
    recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
  } catch {
    stream.getTracks().forEach((t) => t.stop());
    toast("This browser can't record audio. Use Safari on iPhone, or Chrome.", true);
    return;
  }
  const rec = {
    stream, chunks: [], started, coords: null, elapsed: 0, segmentStart: started, paused: false,
  };
  state.recorder = recorder;
  state.recording = rec;
  recorder.ondataavailable = (e) => { if (e.data && e.data.size) rec.chunks.push(e.data); };
  recorder.start(1000);
  setRecPhase("recording");
  rec.timer = setInterval(() => {
    const s = Math.floor(recordedMs(rec) / 1000);
    $("timer").textContent = `${pad(s / 60)}:${pad(s % 60)}`;
  }, 250);
  try {
    rec.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const analyser = rec.audioCtx.createAnalyser();
    analyser.fftSize = 1024;
    rec.audioCtx.createMediaStreamSource(stream).connect(analyser);
    rec.analyser = analyser;
    drawWave(analyser, $("wave"));
  } catch { /* the waveform is decoration */ }
  try { rec.wakeLock = await navigator.wakeLock?.request("screen"); } catch { /* not supported */ }
  getCoords().then((coords) => { if (state.recording === rec) rec.coords = coords; });
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
    const pack = () => {
      stopTracks(rec);
      resolve(new Blob(rec.chunks, { type: recorder.mimeType || "audio/mp4" }));
    };
    if (recorder.state === "inactive") {
      pack();
      return;
    }
    recorder.onstop = pack;
    try { if (recorder.state === "paused") recorder.resume(); } catch { /* stop still keeps the chunks */ }
    recorder.stop();
  });
}

async function stopRecording() {
  const rec = state.recording;
  const AudioCtx = window.AudioContext || window.webkitAudioContext;
  const unlock = AudioCtx ? new AudioCtx() : null;
  unlock?.resume?.();
  $("rec-btn").disabled = true;
  $("pause-btn").disabled = true;
  try {
    const blob = await finishRecording();
    const seconds = Math.round(recordedMs(rec) / 1000);
    state.recorder = null;
    state.recording = null;
    if (!blob.size) {
      setRecPhase("idle");
      toast("Nothing was recorded.", true);
      unlock?.close?.().catch(() => {});
      return;
    }
    await openReview(blob, rec, seconds, unlock);
  } finally {
    $("rec-btn").disabled = false;
    $("pause-btn").disabled = false;
  }
}

function audioSeconds(file) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const audio = new Audio();
    const done = (seconds) => { URL.revokeObjectURL(url); resolve(seconds); };
    audio.preload = "metadata";
    audio.onloadedmetadata = () => done(Number.isFinite(audio.duration) ? Math.round(audio.duration) : 0);
    audio.onerror = () => done(0);
    setTimeout(() => done(0), 3000);
    audio.src = url;
  });
}

function cropIsWhole(review) {
  if (!review.buffer || !review.duration) return true;
  return review.start <= CROP_EDGE && review.duration - review.end <= CROP_EDGE;
}

function drawCropWave(buffer) {
  const canvas = $("crop-wave");
  const ctx = canvas.getContext("2d");
  const data = buffer.getChannelData(0);
  const bars = 80;
  const step = Math.max(1, Math.floor(data.length / bars));
  const gradient = ctx.createLinearGradient(0, 0, canvas.width, 0);
  [["#8b7cff", 0], ["#4cc9f0", .45], ["#3ddc97", .7], ["#ffb547", 1]].forEach(([c, s]) => gradient.addColorStop(s, c));
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = gradient;
  for (let i = 0; i < bars; i++) {
    let peak = 0;
    for (let j = 0; j < step; j += 8) peak = Math.max(peak, Math.abs(data[i * step + j] || 0));
    const h = Math.max(3, peak * canvas.height * 0.9);
    const x = i * (canvas.width / bars);
    ctx.fillRect(x, (canvas.height - h) / 2, 3, h);
  }
}

function layoutCrop() {
  const review = state.review;
  if (!review?.duration) return;
  const start = (review.start / review.duration) * 100;
  const end = (review.end / review.duration) * 100;
  $("crop-dim-left").style.width = `${start}%`;
  $("crop-dim-right").style.width = `${100 - end}%`;
  $("crop-start").style.left = `${start}%`;
  $("crop-end").style.left = `${end}%`;
  $("crop-start").setAttribute("aria-valuemax", String(Math.round(review.duration)));
  $("crop-end").setAttribute("aria-valuemax", String(Math.round(review.duration)));
  $("crop-start").setAttribute("aria-valuenow", String(Math.round(review.start)));
  $("crop-end").setAttribute("aria-valuenow", String(Math.round(review.end)));
  const kept = Math.max(0, review.end - review.start);
  $("crop-status").textContent = cropIsWhole(review)
    ? "Drag the handles to keep part of the recording. The whole take will be sent."
    : `Only ${clock(kept)} will be sent.`;
  renderReviewTime();
}

function renderReviewTime() {
  const review = state.review;
  if (!review) return;
  const kept = Math.max(0, review.end - review.start);
  const at = review.audio.currentTime;
  const pos = !Number.isFinite(at) || at <= review.start + 0.05
    ? 0
    : Math.min(kept, Math.max(0, at - review.start));
  $("review-time").textContent = `${clock(pos)} / ${clock(kept || review.duration)}`;
}

function setCropEdge(which, seconds) {
  const review = state.review;
  if (!review?.duration) return;
  const gap = Math.min(MIN_CROP, review.duration);
  if (which === "start") review.start = Math.min(Math.max(0, seconds), review.end - gap);
  else review.end = Math.max(Math.min(review.duration, seconds), review.start + gap);
  if (!review.audio.paused && (review.audio.currentTime < review.start || review.audio.currentTime > review.end)) {
    review.audio.pause();
    setPlayIcon(false);
    $("crop-playhead").hidden = true;
  }
  layoutCrop();
}

function bindCropHandle(id, which) {
  const el = $(id);
  const fromPointer = (ev) => {
    const box = $("crop-box").getBoundingClientRect();
    const frac = Math.min(1, Math.max(0, (ev.clientX - box.left) / box.width));
    setCropEdge(which, frac * state.review.duration);
  };
  el.addEventListener("pointerdown", (e) => {
    if (!state.review?.ready || !state.review.duration || $("crop-box").hidden) return;
    e.preventDefault();
    el.setPointerCapture(e.pointerId);
    const move = (ev) => fromPointer(ev);
    const up = () => {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
  });
  el.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    if (!state.review?.duration) return;
    e.preventDefault();
    const step = (e.key === "ArrowRight" ? 0.5 : -0.5) * (e.shiftKey ? 4 : 1);
    const current = which === "start" ? state.review.start : state.review.end;
    setCropEdge(which, current + step);
  });
}

function trackPlayback() {
  const review = state.review;
  if (!review || review.audio.paused) {
    if (review) {
      renderReviewTime();
      $("crop-playhead").hidden = true;
    }
    return;
  }
  if (review.audio.currentTime >= review.end - 0.03) {
    review.audio.pause();
    setPlayIcon(false);
    renderReviewTime();
    $("crop-playhead").hidden = true;
    return;
  }
  renderReviewTime();
  if (review.duration && !$("crop-box").hidden) {
    $("crop-playhead").hidden = false;
    $("crop-playhead").style.left = `${(review.audio.currentTime / review.duration) * 100}%`;
  }
  review.raf = requestAnimationFrame(trackPlayback);
}

function togglePlayback() {
  const review = state.review;
  if (!review?.ready) return;
  const audio = review.audio;
  if (!audio.paused) {
    audio.pause();
    setPlayIcon(false);
    $("crop-playhead").hidden = true;
    renderReviewTime();
    return;
  }
  try { audio.currentTime = review.start || 0; } catch { /* seek again once metadata arrives */ }
  audio.play().then(() => {
    setPlayIcon(true);
    trackPlayback();
  }).catch(() => toast("Couldn't play the recording.", true));
}

async function openReview(blob, rec, seconds, unlock) {
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  audio.preload = "auto";
  state.review = {
    blob, url, audio, started: rec.started, coords: rec.coords, seconds,
    buffer: null, duration: seconds, start: 0, end: seconds, ready: false, raf: 0,
  };
  $("crop-box").hidden = false;
  $("crop-box").classList.remove("busy");
  $("play-btn").disabled = true;
  $("card-send").dataset.busy = "";
  setPlayIcon(false);
  $("review-time").textContent = "Loading…";
  $("crop-status").textContent = "Preparing the recording…";
  setRecPhase("review");
  let ctx = unlock;
  try {
    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === "suspended") await ctx.resume();
    const buffer = await ctx.decodeAudioData((await blob.arrayBuffer()).slice(0));
    await ctx.close().catch(() => {});
    ctx = null;
    if (!Number.isFinite(buffer.duration) || buffer.duration <= 0) throw new Error("bad duration");
    const review = state.review;
    if (!review || review.blob !== blob) return;
    review.buffer = buffer;
    review.duration = buffer.duration;
    review.start = 0;
    review.end = buffer.duration;
    review.ready = true;
    drawCropWave(buffer);
    layoutCrop();
    $("play-btn").disabled = false;
    syncCardSend();
  } catch {
    ctx?.close?.().catch(() => {});
    const review = state.review;
    if (!review || review.blob !== blob) return;
    review.ready = true;
    review.start = 0;
    review.end = review.duration;
    $("crop-box").hidden = true;
    $("crop-status").textContent = "Crop isn't available for this recording. Send keeps the whole take.";
    $("play-btn").disabled = false;
    syncCardSend();
    renderReviewTime();
  }
}

function closeReview() {
  const review = state.review;
  if (!review) return;
  cancelAnimationFrame(review.raf);
  review.audio.pause();
  review.audio.src = "";
  URL.revokeObjectURL(review.url);
  state.review = null;
  setPlayIcon(false);
  $("card-send").dataset.busy = "";
  $("crop-box").hidden = false;
  $("crop-box").classList.remove("busy");
  $("crop-playhead").hidden = true;
  setRecPhase("idle");
}

function setReviewBusy(on) {
  $("play-btn").disabled = on;
  $("review-discard").disabled = on;
  $("card-send").dataset.busy = on ? "1" : "";
  $("crop-box").classList.toggle("busy", on);
  if (on) $("card-send-label").textContent = "Preparing…";
  syncCardSend();
}

async function trimmedBlob(review) {
  if (cropIsWhole(review)) return review.blob;
  const buffer = review.buffer;
  const rate = buffer.sampleRate;
  const start = Math.max(0, Math.floor(review.start * rate));
  const end = Math.min(buffer.length, Math.ceil(review.end * rate));
  const length = Math.max(1, end - start);
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  if (ctx.state === "suspended") await ctx.resume();
  const sliced = ctx.createBuffer(buffer.numberOfChannels, length, rate);
  for (let ch = 0; ch < buffer.numberOfChannels; ch++) {
    sliced.getChannelData(ch).set(buffer.getChannelData(ch).subarray(start, end));
  }
  const dest = ctx.createMediaStreamDestination();
  const source = ctx.createBufferSource();
  source.buffer = sliced;
  source.connect(dest);
  const mime = pickMime() || "";
  let recorder;
  try {
    recorder = new MediaRecorder(dest.stream, mime ? { mimeType: mime } : undefined);
  } catch (err) {
    await ctx.close().catch(() => {});
    throw err;
  }
  const chunks = [];
  const blob = await new Promise((resolve, reject) => {
    const limit = Math.ceil(length / rate * 1000) + 2500;
    const timer = setTimeout(() => { try { recorder.stop(); } catch { /* already stopped */ } }, limit);
    recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    recorder.onerror = () => { clearTimeout(timer); reject(new Error("trim")); };
    recorder.onstop = () => {
      clearTimeout(timer);
      resolve(new Blob(chunks, { type: recorder.mimeType || mime || "audio/mp4" }));
    };
    recorder.start();
    source.onended = () => setTimeout(() => { try { recorder.stop(); } catch { /* already stopped */ } }, 200);
    source.start();
  });
  dest.stream.getTracks().forEach((t) => t.stop());
  await ctx.close().catch(() => {});
  if (!blob.size) throw new Error("empty trim");
  return blob;
}

async function sendReview() {
  const review = state.review;
  if (!review?.ready) return;
  review.audio.pause();
  setPlayIcon(false);
  const cropped = !cropIsWhole(review);
  setReviewBusy(true);
  if (!cropped) $("card-send-label").textContent = "Send";
  if (cropped) $("crop-status").textContent = "Trimming… this takes about as long as the part you kept.";
  try {
    const blob = await trimmedBlob(review);
    const kept = cropped ? review.end - review.start : (review.duration || review.seconds);
    const item = {
      capture_id: captureId("rec", review.started),
      kind: "recording",
      created: Date.now(),
      fields: { ...baseFields(review.started), ...(review.coords || {}) },
      audio: blob,
      audioName: `audio${extensionFor(blob.type || "")}`,
      photos: takePhotos("recPhotos", "rec-thumbs", "rec-photo-count"),
      seconds: Math.max(1, Math.round(kept)),
    };
    closeReview();
    await queueAndSend(item);
  } catch {
    toast("Couldn't crop. Drag both handles to the ends, then Send.", true);
    setReviewBusy(false);
    layoutCrop();
  }
}

function discardReview() {
  if (!state.review || !confirm("Discard this recording?")) return;
  closeReview();
  toast("Recording discarded.");
}

async function sendPhotosOnly() {
  if (state.phase !== "idle" || !state.recPhotos.length) return;
  const started = new Date();
  const btn = $("card-send");
  btn.dataset.busy = "1";
  syncCardSend();
  try {
    const coords = await getCoords();
    const item = {
      capture_id: captureId("note", started),
      kind: "note",
      created: Date.now(),
      fields: { ...baseFields(started), ...(coords || {}) },
      audio: null,
      photos: takePhotos("recPhotos", "rec-thumbs", "rec-photo-count"),
    };
    await queueAndSend(item);
  } finally {
    btn.dataset.busy = "";
    syncCardSend();
  }
}

function onCardSend() {
  if (state.phase === "review") sendReview();
  else sendPhotosOnly();
}

async function uploadAudio(input) {
  const file = input.files[0];
  input.value = "";
  if (!file) return;
  if (state.recorder || state.review) {
    toast("Send or discard the recording first.", true);
    return;
  }
  // The file's time is when it was recorded or saved; it picks the day unless one is chosen.
  const saved = new Date(file.lastModified || Date.now());
  const started = saved > new Date() ? new Date() : saved;
  const day = state.date || localDate(started);
  const size = file.size < 1048576
    ? `${Math.max(1, Math.round(file.size / 1024))} KB`
    : `${(file.size / 1048576).toFixed(1)} MB`;
  if (!confirm(`Send "${file.name}" (${size}) as Log My Day for ${dayLabel(day)}?`)) return;
  const ext = (file.name.match(/\.[a-z0-9]{1,5}$/i) || [extensionFor(file.type)])[0].toLowerCase();
  const item = {
    capture_id: captureId("rec", started),
    kind: "recording",
    created: Date.now(),
    fields: baseFields(started),
    audio: file,
    audioName: `audio${ext}`,
    photos: takePhotos("recPhotos", "rec-thumbs", "rec-photo-count"),
    seconds: await audioSeconds(file),
  };
  await queueAndSend(item);
}

async function discardRecording() {
  if (!state.recorder || !confirm("Discard this recording?")) return;
  await finishRecording();
  state.recorder = null;
  state.recording = null;
  setRecPhase("idle");
  toast("Recording discarded.");
}

// --- history, banner and summary -----------------------------------------------------------

const IN_JOURNAL = new Set(["full", "update", "unchanged"]);

function statusChip(capture) {
  if (capture.status === "failed") return ["failed", "Failed · retry"];
  if (capture.status === "queued") {
    return capture.retry_at ? ["queue", "Retrying…"] : ["queue", "Queued"];
  }
  if (capture.status === "processing") {
    return ["proc", capture.kind === "recording" ? "Transcribing…" : "Saving…"];
  }
  if (capture.status === "done") {
    if (IN_JOURNAL.has(capture.generation)) return ["done", "In journal"];
    if (capture.generation === "failed") return ["bad", "Journal failed"];
    return ["saved", "Not in journal"];
  }
  return ["queue", capture.status];
}

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

function filedDay(entryDate, capturedAt) {
  if (entryDate) return String(entryDate).slice(0, 10);
  return localDate(new Date(capturedAt));
}

function groupLabel(day) {
  if (day === localDate()) return "Today";
  const yesterday = localDate(new Date(Date.now() - 86400000));
  if (day === yesterday) return "Yesterday";
  return dayLabel(day);
}

function clockTime(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

let generatingDay = "";

function captureRow({ kind, capturedAt, photos, local, chip, onChip }) {
  const row = el("div", "item");
  const [icon, title] = describe(kind, local, photos);
  row.append(el("div", "ico", icon));
  const meta = el("div", "meta");
  const line = el("div", "a");
  line.append(el("span", "when", clockTime(capturedAt)), document.createTextNode(title));
  meta.append(line);
  const bits = [];
  if (photos) bits.push(`${photos} photo${photos === 1 ? "" : "s"}`);
  if (local?.place) bits.push(local.place);
  if (local?.preview) bits.push(`“${local.preview}”`);
  if (bits.length) meta.append(el("div", "b", bits.join(" · ")));
  row.append(meta);
  const status = el(onChip ? "button" : "span", `st ${chip[0]}`, chip[1]);
  if (onChip) {
    status.type = "button";
    status.addEventListener("click", onChip);
  }
  row.append(status);
  return row;
}

async function generateJournal(day) {
  const label = groupLabel(day);
  const question = `Generate or update ${label} from the recordings and My notes? ` +
    "Existing journal words, notes, and recordings stay.";
  if (!confirm(question)) return;
  generatingDay = day;
  await renderCaptures();
  try {
    await flushOutbox();
    const body = await api("/journal", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date: day }),
    });
    toast(body.message || "Journal written.");
    refreshSummary();
  } catch (err) {
    toast(err instanceof HttpError ? err.message : "Can't reach the server.", true);
  } finally {
    generatingDay = "";
    await refreshCaptures();
  }
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
      day: filedDay(item.fields.date, item.fields.captured_at),
      at: item.fields.captured_at,
      node: captureRow({
        kind: item.kind, capturedAt: item.fields.captured_at, photos: item.photos.length,
        local: { preview: (item.fields.text || "").slice(0, 80), seconds: item.seconds, place: item.fields.place },
        chip: item.error ? ["failed", "Not accepted"] : ["offline", "Waiting"],
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
      day: filedDay(c.entry_date, c.captured_at),
      at: c.captured_at,
      node: captureRow({
        kind: c.kind, capturedAt: c.captured_at, photos: c.photos.length || local[c.capture_id]?.photos || 0,
        local: local[c.capture_id], chip: statusChip(c),
        onChip: c.status === "failed" ? () => retryCapture(c.capture_id) : null,
      }),
    });
  }
  const byDay = new Map();
  for (const row of rows) {
    if (!byDay.has(row.day)) byDay.set(row.day, []);
    byDay.get(row.day).push(row);
  }
  const days = [...byDay.keys()].sort((a, b) => (a < b ? 1 : a > b ? -1 : 0));
  const groups = days.map((day) => {
    const group = el("div", "day-group");
    const head = el("div", "day-head");
    head.append(el("b", "", groupLabel(day)));
    const button = el("button", "btn small", generatingDay === day ? "Writing…" : "Generate");
    button.type = "button";
    button.disabled = generatingDay === day;
    button.setAttribute("aria-label", `Generate journal for ${groupLabel(day)}`);
    button.addEventListener("click", () => generateJournal(day));
    head.append(button);
    const items = byDay.get(day).sort((a, b) => new Date(b.at) - new Date(a.at));
    group.append(head, ...items.map((row) => row.node));
    return group;
  });
  box.replaceChildren(...groups);
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

// --- connected AI apps (Settings) ------------------------------------------------------------

function stamp(iso) {
  const d = new Date(iso);
  const day = localDate(d);
  if (day === localDate() || day === localDate(new Date(Date.now() - 86400000))) return when(iso);
  const date = d.toLocaleDateString([], { month: "short", day: "numeric" });
  return `${date}, ${d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
}

function appRow(app) {
  const row = el("div", "item");
  row.append(el("div", "ico", "✦"));
  const meta = el("div", "meta");
  const name = el("div", "a", app.name || "Unnamed app");
  name.append(el("span", `st ${app.signed_in ? "done" : "queue"}`, app.signed_in ? "Connected" : "Disconnected"));
  const from = app.hosts.length ? app.hosts.join(", ") : "unknown address";
  const used = app.last_used_at ? ` · used ${stamp(app.last_used_at)}` : "";
  meta.append(name, el("div", "b", `${from}${used}`));
  meta.append(el("div", "b", app.signed_in
    ? `Signed in ${stamp(app.signed_in_at)} · ends ${new Date(app.session_ends_at).toLocaleDateString([], { month: "short", day: "numeric" })}`
    : `Added ${stamp(app.registered_at)}`));
  row.append(meta);
  if (app.signed_in) {
    const button = el("button", "btn small", "Disconnect");
    button.type = "button";
    button.addEventListener("click", () => disconnectApp(app));
    row.append(button);
  }
  return row;
}

async function refreshApps() {
  const box = $("apps");
  try {
    const { apps, session_days: days } = await api("/lens/apps");
    $("apps-sub").textContent = `Sessions last ${days} day${days === 1 ? "" : "s"}`;
    box.replaceChildren(...apps.map(appRow));
    $("apps-empty").textContent = "No AI app has connected yet.";
    $("apps-empty").hidden = apps.length > 0;
    $("apps-sign-out-all").hidden = !apps.some((a) => a.signed_in);
  } catch (err) {
    box.replaceChildren();
    $("apps-empty").textContent = err instanceof HttpError
      ? `Can't load the apps: ${err.message}.`
      : "Can't reach the server. Check your connection (or VPN).";
    $("apps-empty").hidden = false;
    $("apps-sign-out-all").hidden = true;
  }
}

async function appAction(path, options, done) {
  try {
    await api(path, options);
    toast(done);
  } catch (err) {
    toast(`That didn't work: ${err.message}`, true);
  }
  await refreshApps();
}

function disconnectApp(app) {
  const name = app.name || "this app";
  if (!confirm(`Disconnect ${name} now? It needs the Lens password to connect again.`)) return;
  appAction(`/lens/apps/${encodeURIComponent(app.id)}/sign-out`, { method: "POST" }, `${name} disconnected.`);
}

function disconnectAllApps() {
  if (!confirm("Disconnect every AI app now? Each needs the Lens password to connect again.")) return;
  appAction("/lens/apps/sign-out-all", { method: "POST" }, "All AI apps disconnected.");
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
  if (tab === "settings") refreshApps();
}

function wire() {
  $("login-form").addEventListener("submit", login);
  $("logout").addEventListener("click", logout);
  $("gear").addEventListener("click", () => go(document.body.dataset.tab === "settings" ? "capture" : "settings"));
  document.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => go(b.dataset.go)));

  $("rec-btn").addEventListener("click", toggleRecording);
  $("pause-btn").addEventListener("click", togglePause);
  $("discard-btn").addEventListener("click", discardRecording);
  $("play-btn").addEventListener("click", togglePlayback);
  $("card-send").addEventListener("click", onCardSend);
  $("review-discard").addEventListener("click", discardReview);
  bindCropHandle("crop-start", "start");
  bindCropHandle("crop-end", "end");
  $("rec-photos").addEventListener("change", (e) => addPhotos(e.target, "recPhotos", "rec-thumbs", "rec-photo-count"));
  $("rec-upload").addEventListener("change", (e) => uploadAudio(e.target));
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
  $("apps-refresh").addEventListener("click", refreshApps);
  $("apps-sign-out-all").addEventListener("click", disconnectAllApps);
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
  window.addEventListener("beforeunload", (e) => { if (state.recorder || state.review) e.preventDefault(); });
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
