# Prism (recording API)

The Prism takes what a Flash (the iPhone Shortcuts) captures and splits that one beam of raw
voice into its colors: facts, journal, mood and transcript, written into the day's Frame (the
day file). Command: `lumen-prism`; Docker service: `prism`. Owned by the
prism work stream. Code: `lumen/prism/` (HTTP, inbox, worker) and
`lumen/prism/pipeline/` (speech to text, AI steps, audio, photos, activity records).
Tests: `tests/prism/`. iPhone side: `docs/flash.md`.

```mermaid
flowchart LR
    Phone["Flash: iPhone Shortcut"] -->|"POST /recordings, /notes"| API["API: validate, save to inbox"]
    API -->|"202 + capture_id"| Phone
    API --> Inbox["_system/inbox/ID/"]
    Inbox --> Worker["Worker thread"]
    Worker --> Day["Day folder: .md, .m4a, photos"]
    Worker --> Sys["_system/: snapshot, status, activity"]
    Worker -.->|"POST /nudge"| Indexer["Spectrum: indexer"]
```

## Endpoints

All endpoints except `/health` need `Authorization: Bearer <LUMEN_API_TOKEN>`. A missing or
wrong token gets `401` (with `WWW-Authenticate: Bearer`). If the server's token is missing, still
`change-me` or shorter than 16 characters, it refuses everything with `503` (fails closed) and
logs an error at start-up. The token is compared in constant time.

### `POST /recordings` (Log My Day)

`multipart/form-data`:

| Field | Required | Meaning |
|---|---|---|
| `audio` | yes | the voice recording (any format; iPhone Record Audio gives `.m4a`) |
| `photos` or `photos[]` (or `photo`) | no | any number of image files (HEIC, JPEG, PNG, ...); max 60 |
| `captured_at` | no | when it was recorded: ISO-8601 (`2026-10-10T21:30:00-05:00`; no offset = server timezone) or Unix seconds. Default: now |
| `lat`, `lon` | no | decimal degrees |
| `place` | no | a place name, e.g. the city from Get Details of Locations |
| `capture_id` | no | client id for safe retries: letters, digits, `.`, `_`, `-`, max 128 |

Response `202 Accepted` (new) or `200 OK` (this `capture_id` was already received):

```json
{
  "capture_id": "20261010T213000-recording-3fa2b1",
  "kind": "recording",
  "status": "queued",
  "entry_date": "2026-10-10",
  "duplicate": false,
  "status_url": "/captures/20261010T213000-recording-3fa2b1",
  "message": "Recording saved for Saturday, October 10. Your journal updates in a minute."
}
```

`message` is meant to be shown as the Shortcut's notification.

### `POST /notes` (Quick Note)

Same fields, but `audio` is optional and `text` is added; at least one of `text`, `audio` or a
photo is required (text and audio: the transcript is appended after the text; photos only: e.g.
photos shared from the Photos app). Accepts `multipart/form-data`,
`application/x-www-form-urlencoded` or `application/json` (text-only notes, e.g.
`{"text": "...", "captured_at": "...", "capture_id": "..."}`). Same response.

### `GET /captures/{capture_id}`

```json
{
  "capture_id": "phone-001",
  "kind": "recording",
  "status": "done",
  "entry_date": "2026-10-10",
  "captured_at": "2026-10-10T21:30:00-05:00",
  "received_at": "2026-10-11T02:30:04Z",
  "updated_at": "2026-10-11T02:30:41Z",
  "attempts": 1,
  "retry_at": null,
  "day_file": "2026/10/2026-10-10/2026-10-10.md",
  "audio": "2026-10-10-2130.m4a",
  "photos": ["photo-01.jpg"],
  "generation": "full",
  "errors": [],
  "warnings": []
}
```

* `status`: `queued` → `processing` → `done`, or `failed` after the automatic retries. While an
  automatic retry is waiting, `status` is `queued` and `retry_at` is set.
* `generation`: `full` (facts, title and journal regenerated for the whole day), `additive` (the
  day was edited by the owner, so only additions; see below), `skipped` (no words), or `failed`
  (the transcript is saved but every AI model failed; `errors` says which step).
* `404` for an unknown id.

### `POST /captures/{capture_id}/retry`

Re-queues a `failed` capture whose upload is still in the inbox. `409` if it is not failed,
`410` if the upload is gone (send it again). Returns the status.

### `GET /health`

`{"status": "ok", "service": "api", "version": "0.1.0"}`, no token.

### Errors

`401` / `503` auth, `413` upload larger than `LUMEN_API_MAX_UPLOAD_MB`, `415` unsupported
content type, `422` invalid fields (message in `detail`), `404` unknown capture.

### Examples

```bash
TOKEN=...; API=https://lumen.example.com
curl -H "Authorization: Bearer $TOKEN" -F audio=@memo.m4a -F photos=@a.heic -F photos=@b.heic \
     -F lat=30.2672 -F lon=-97.7431 -F place=Austin -F captured_at=2026-10-10T21:30:00-05:00 \
     -F capture_id=test-001 "$API/recordings"
curl -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"text": "Lunch at the taco truck."}' "$API/notes"
curl -H "Authorization: Bearer $TOKEN" "$API/captures/test-001"
```

## Durable inbox and background processing

The upload is written to storage before the response, and processed afterwards by one worker
thread (ADR 0010):

1. Parse and validate the request (auth first, then size, fields).
2. Write the raw files to `_system/inbox/<capture_id>/` (`audio.<ext>`, `photo-NN.<ext>`), then
   `manifest.json` (a `CaptureRequest`) last. A folder without a manifest is an interrupted
   upload and is ignored.
3. Write `_system/captures/<capture_id>.json` (`CaptureStatus`, status `queued`) and queue it.
4. Answer `202`.

**Idempotency:** a `capture_id` whose status exists and is not `failed` is not stored again; the
response is `200` with `duplicate: true` and the current status. A `failed` one is replaced by the
new upload and queued again. The day file is also idempotent (`merge_capture` ignores a capture
id it already has), so a retry can never duplicate an entry. Without a `capture_id` the server
makes one (`<YYYYMMDDTHHMMSS>-<kind>-<random>`), so every such request is a new capture.

**Worker:** one daemon thread processes captures in arrival order, so two captures for the same
day never race on the day file. A failure is retried after 60 s and 10 min (three attempts),
then left `failed` in the inbox for `POST /captures/{id}/retry` or a re-send.

**Restart:** on start-up the API lists `_system/inbox/`, re-queues `queued` and `processing`
captures (a crash mid-way is safe: a capture already in the day file is not added again, only
regenerated), creates a status for manifests that have none, cleans up `done` leftovers, and
leaves `failed` ones alone. On shutdown the worker finishes the capture in progress.

The status files stay after processing (small, no journal content) so `GET /captures/{id}` and
retries keep working. The inbox folder is deleted once a capture is `done`.

## Pipeline

`lumen.prism.pipeline.processor.CaptureProcessor.process(request)`; each step is timed into the
activity record.

1. **Entry date:** `entry_date(captured_at, LUMEN_TIMEZONE, LUMEN_DAY_ROLLOVER_HOUR)`; before
   4 a.m. counts as the previous day. The capture time is stored in the local timezone.
2. **Audio** (`pipeline/audio.py`, ADR 0013): compress to `.m4a`, AAC, mono, at
   `LUMEN_AUDIO_BITRATE_KBPS` with `ffmpeg`, else macOS `afconvert`. If neither exists or both
   fail, the original is kept unchanged (with its own extension, e.g. `.wav`; MPEG-4 audio keeps
   `.m4a`) and a warning is logged and recorded. If an `.m4a` original is already smaller than
   the compressed copy, the original is kept.
3. **Speech to text** (`pipeline/stt.py`), by `LUMEN_STT_PROVIDER`:
   * `litellm`: `litellm.transcription(model=LUMEN_STT_MODEL, language=LUMEN_STT_LANGUAGE)`.
     An empty `LUMEN_STT_LANGUAGE` omits the language so the model detects it per recording
     (use this for mixed speech such as Telugu and English; `en` forces English).
     The original audio is sent (best quality) unless it is over 24 MB or in a format hosted APIs
     reject; then the compressed copy is sent.
   * `aws_transcribe`: uploads to `LUMEN_AWS_TRANSCRIBE_BUCKET` under `lumen-stt/`, runs a
     batch job, reads the result and deletes the media, the result and the job. `en` is sent as
     `en-US` (also `es`, `fr`, `de`, ... mapped; `xx-YY` codes are used as-is; anything else uses
     language identification). Turn on the **AWS Organizations AI services opt-out policy** so
     AWS does not use the audio to improve its models. Needs `boto3` and AWS credentials.
   * `fake`: offline; uploaded bytes that are UTF-8 text become the transcript.
   If transcription fails nothing has been written yet, so the capture is simply retried.
4. **Photos** (`pipeline/photos.py`): Pillow + pillow-heif (HEIC); rotated upright from EXIF,
   fitted within `LUMEN_PHOTO_MAX_DIMENSION`, saved as JPEG at `LUMEN_PHOTO_JPEG_QUALITY`
   without EXIF (no GPS or device data in the copy). Named with `next_photo_names()` after the
   highest existing `photo-NN.jpg` in the day folder. Files that are not images are skipped with a
   warning.
5. **Save the capture:** audio (`audio_file_name()` + `unique_file_name()`, e.g.
   `2026-10-10-2130.m4a`, `2026-10-10-2130-2.m4a`) and photos go into the day folder; the day file
   is re-read and `merge_capture` adds the transcript block; the day file and its
   `_system/generated/` snapshot are written. From here on the capture is safe even if the AI
   steps fail (ADR 0011).
6. **AI steps** (`pipeline/generate.py`, `pipeline/llm.py`), only if the day has any words:
   * Day **not** edited by the owner → **full**: `extract_facts` over all of the day's captures
     (JSON validated against `DayFacts`; `keep_family` gives every `LUMEN_FAMILY` member a block,
     empty if the day says nothing about them, spelled as configured, and drops anyone else;
     meal types are mapped to the five fixed ones), then `write_journal` (JSON
     `{headline, journal}`), then `apply_generation` with the title
     `"<Weekday, Month D, YYYY> · <headline>"`, which gives the journal the fixed headings
     (`normalize_journal`, `docs/frames-format.md` → The journal).
   * Day **edited** (`DayFile.is_user_edited()`) → **additive**: `extract_facts` over the new
     capture only, `journal_addendum` (a short paragraph about the new entry, given the edited
     journal as context), then `merge_generation_additive`, which appends the paragraph under
     `## Later` with the label `**HH:MM · Quick Note**`.
     Existing facts, title and journal are never changed; new places, people, highlights and
     family items are appended.
   * Before writing, the day file is read **again**. If the owner edited it while the AI was
     working, a full result is thrown away and the additive path runs instead, so a concurrent
     edit is never overwritten.
   * If one step fails on every model, the other step's result is still applied (facts without a
     new journal, or a journal with the old facts). If both fail, the day keeps the transcript
     and `generation` is `failed`.
   * Front matter: `prompt_version` (e.g. `extract_facts-v2+write_journal-v1`) and `models_used`
     (`stt`, `extract_facts`, `write_journal` or `journal_addendum`: the models that actually
     answered), merged with what was there.
7. **Write** the day file and its snapshot again.
8. **Nudge** the indexer (`nudge_indexer` with the day file, audio and photo paths). A failed or
   refused nudge is recorded but never fails the capture; the indexer also polls.
9. **Activity record** appended (also for failed attempts); the worker then marks the status
   `done` and deletes the inbox folder.

### Models and fallback

Each AI call goes to the task's model (`LUMEN_LLM_EXTRACT_FACTS_MODEL`,
`LUMEN_LLM_WRITE_JOURNAL_MODEL`; the addendum uses the journal model) with
`response_format={"type": "json_object"}`, `timeout=LUMEN_LLM_TIMEOUT_SECONDS`,
`num_retries=LUMEN_LLM_MAX_RETRIES` and `drop_params=True` (LiteLLM drops parameters a provider
does not support). A provider error, a reply that is not JSON (code fences and chatter around the
object are tolerated) or a reply that fails validation counts as a failure of that model, and the
same request goes to `LUMEN_LLM_FALLBACK_MODEL` (ADR 0014). An out-of-range `mood_score` is set
to null instead of rejecting the whole reply.

The model string **`fake`** never calls a provider: facts come back empty and the journal is the
day's text under `## Summary`. With `LUMEN_STT_PROVIDER=fake` and the three `LUMEN_LLM_*`
models set to `fake`, the whole API runs offline.

### Prompts

Versioned files in `prompts/<task>/<version>.md` (`prompts/README.md`): `extract_facts/v2.md`
(v2 adds `places` and the per-member `family` blocks; v1 is kept for reference),
`write_journal/v1.md`, `journal_addendum/v1.md`. The current versions are in
`lumen.prism.pipeline.prompts.PROMPT_VERSIONS`. Each file has a system part and a user part separated
by `<!-- lumen-prompt: system -->` / `<!-- lumen-prompt: user -->`, with `{{name}}`
placeholders (`date`, `location`, `captures`, `facts`, `journal`, `capture`, `family` = the
`LUMEN_FAMILY` names). A missing value
raises an error. Prompts tell the model to use only what the entries say and never invent.

## Activity records (`_system/activity/YYYY/MM.jsonl`)

One JSON line per processing attempt, appended to the file for the month the attempt finished
(UTC), written by `lumen.prism.pipeline.activity.ActivityLog` (ADR 0012). Example (fictional):

```json
{"capture_id": "phone-001", "kind": "recording", "attempt": 1, "status": "done",
 "entry_date": "2026-10-10", "received_at": "...", "started_at": "...", "finished_at": "...",
 "generation": "full", "prompt_versions": {"extract_facts": "v2", "write_journal": "v1"},
 "models": {"stt": "openai/gpt-4o-transcribe", "extract_facts": "openai/gpt-4o-mini",
            "write_journal": "openai/gpt-4o"},
 "steps": [
   {"name": "compress_audio", "ms": 812, "ok": true,
    "detail": {"bytes_in": 5242880, "bytes_out": 1468006, "compressor": "ffmpeg"}},
   {"name": "transcribe", "ms": 9120, "ok": true, "model": "openai/gpt-4o-transcribe",
    "cost_usd": 0.036, "detail": {"audio_bytes": 5242880, "chars": 4210}},
   {"name": "write_day", "ms": 640, "ok": true, "detail": {"captures": 2}},
   {"name": "extract_facts", "ms": 3010, "ok": true, "model": "openai/gpt-4o-mini",
    "cost_usd": 0.0009},
   {"name": "write_journal", "ms": 7400, "ok": true, "model": "openai/gpt-4o",
    "cost_usd": 0.012},
   {"name": "write_day", "ms": 590, "ok": true, "detail": {"mode": "full"}},
   {"name": "nudge", "ms": 15, "ok": true, "detail": {"accepted": true}}],
 "cost_usd": 0.0489, "errors": [], "warnings": []}
```

* Steps: `compress_audio`, `transcribe`, `photos`, `write_day`, `extract_facts`,
  `write_journal`, `journal_addendum`, `nudge`. When the fallback model was needed, the step's
  `detail.attempts` lists each model with `ok`, `ms` and the error.
* `cost_usd` comes from LiteLLM (`_hidden_params.response_cost` or `completion_cost`) and is
  missing when LiteLLM does not know the price (e.g. Amazon Transcribe, local models).
* **No journal content**: no transcript, note text, facts, journal, names, places or file
  contents. Only sizes, counts, models, timings and errors. Error texts go through `safe_error`:
  validation and JSON errors keep only their type and count (their messages would echo model
  output), other messages are cut to 200 characters.
* Storage has no append, so each record is a read-modify-write of the month file under a lock
  (the API is the only writer). A failure to write the record is logged and never fails a
  capture.

## Files written

| Path | Content |
|---|---|
| `YYYY/MM/YYYY-MM-DD/YYYY-MM-DD.md` | the day file (`docs/frames-format.md`) |
| `YYYY/MM/YYYY-MM-DD/YYYY-MM-DD-HHMM.m4a` | compressed audio |
| `YYYY/MM/YYYY-MM-DD/photo-NN.jpg` | resized photos |
| `_system/generated/YYYY/MM/YYYY-MM-DD.md` | snapshot of each day file write |
| `_system/inbox/<id>/` | raw uploads waiting to be processed (deleted when done) |
| `_system/captures/<id>.json` | capture status (no journal content) |
| `_system/activity/YYYY/MM.jsonl` | activity records |

## Configuration

| Setting | Use here |
|---|---|
| `LUMEN_API_TOKEN` | bearer token; at least 16 characters (`openssl rand -hex 32`); if it is missing, `change-me` or short, every request except `/health` gets `503` |
| `LUMEN_API_HOST`, `LUMEN_API_PORT` | where uvicorn listens |
| `LUMEN_API_MAX_UPLOAD_MB` | total size of one request (`413` above it) |
| `LUMEN_AUDIO_BITRATE_KBPS` | AAC bitrate of the stored audio |
| `LUMEN_PHOTO_MAX_DIMENSION`, `LUMEN_PHOTO_JPEG_QUALITY` | photo copies |
| `LUMEN_TIMEZONE`, `LUMEN_DAY_ROLLOVER_HOUR` | entry dates and capture times |
| `LUMEN_STT_PROVIDER`, `LUMEN_STT_MODEL`, `LUMEN_STT_LANGUAGE`, `LUMEN_AWS_REGION`, `LUMEN_AWS_TRANSCRIBE_BUCKET` | speech to text |
| `LUMEN_LLM_EXTRACT_FACTS_MODEL`, `LUMEN_LLM_WRITE_JOURNAL_MODEL`, `LUMEN_LLM_FALLBACK_MODEL`, `LUMEN_LLM_TIMEOUT_SECONDS`, `LUMEN_LLM_MAX_RETRIES` | AI steps (`fake` = offline) |
| `LUMEN_FAMILY` | comma-separated family members (`Maya, Leo`) who get their own block under Family; empty = no family blocks |
| `LUMEN_PROMPTS_DIR` | prompt files; a relative path that does not exist falls back to the repository's `prompts/` |
| `LUMEN_INDEXER_NUDGE_URL` | nudge after each capture (empty = off) |
| storage settings | where everything is written (`get_storage`) |

## Testing

`uv run pytest tests/prism` runs offline: `LocalStorage` on `tmp_path`, `stt_provider=fake`, a
scripted fake in place of `litellm.completion` (`tests/prism/conftest.py::FakeLLM`), a fake
compressor and a nudge recorder injected through `create_app(settings, processor=...)`. The
real-compressor test runs only where `ffmpeg` or `afconvert` can encode AAC (it is skipped in
sandboxes that hide the macOS codecs).

## Known limits

* Inbox uploads go to the configured storage; with Google Drive the `202` waits for the raw
  files to reach Drive (a few seconds for a long recording with many photos).
* If the server dies after writing audio/photos but before the day file, the retry writes them
  again under new names and the first copies stay as orphans in the day folder.
* A day file whose front matter the owner broke cannot be merged into; the capture fails with a
  parse error until the file is fixed, then `POST /captures/{id}/retry`.
* No reverse geocoding: the location is the `place` text plus the coordinates.
