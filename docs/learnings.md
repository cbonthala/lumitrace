# Learnings

What we learned about quality, models, prompts and operations, and what to change next.
Personal details are always removed; the full weekly reports live in `Lumen/_system/reports/`.

Entry format: `- YYYY-MM-DD — observation → action (link to PR/ADR)`.

## Foundation

- 2026-10-18 — Replacing separate facts and journal regions with a richer typed family page
  changes storage, search, exact queries and edit signals together → keep the Format 5 projection
  for old callers, and add canonical passages, `content_facts`, Lens content output and
  top-level content edit signals in the same Format 6 change (ADR 0061).
- 2026-10-18 — Removing the visible facts region also removed the only structured source for
  precise meal, place, people and family queries → keep the narrative journal and structured
  facts together, and test both search and `query_facts` end to end (ADR 0059).
- 2026-10-10 — mcp resolved to 2.x, where `FastMCP` is now `mcp.server.mcpserver.MCPServer`;
  v1 examples online won't work as-is → use the 2.x API.
- 2026-10-10 — With the `drive.file` scope, files created outside Lumen are invisible to it →
  reading self-written Obsidian notes needs a decision (open question in the plan).
- 2026-10-10 — Photos are embedded as `![[photo-NN.jpg]]`, a name that repeats in every day
  folder. Obsidian should resolve it to the file next to the note, but this is unverified →
  check in Obsidian; if wrong, switch embeds to relative Markdown links.
- 2026-10-10 — Integration pass: the three streams built against the written contracts fit
  together on the first end-to-end run (`tests/e2e/`); the gaps were at the edges: the API
  accepted the `.env.example` placeholder token while the MCP server refused it, and
  `pyproject.toml` allowed mcp 1.x → one shared rule for secrets (refuse placeholders and < 16
  characters everywhere) and lower bounds that match the API the code actually uses.
- 2026-10-10 — MCP tests built their own index fixture, so indexer → MCP compatibility (e.g.
  lower-cased meal types) was only proven by the end-to-end test → keep `tests/e2e/` running
  every component for real, no hand-built fixtures.
- 2026-10-11 — Renaming the project (LifeLog → Bookshelf) touched the day-file markers and the
  `lifelog_format` key, which are part of the file format, not just code names → `parse` accepts
  both marker prefixes and the old key, and a test parses a pre-rename file (ADR 0008). The data
  folder `data/Bookshelf` differs from the `bookshelf/` package only by case, so `.gitignore`
  must never list `Bookshelf/` (case-insensitive filesystems would ignore the package).
- 2026-10-11 — Second rename (Bookshelf → Lumen, ADR 0009): day files now exist with three
  marker generations → `MARKER_PREFIXES` and `LEGACY_FORMAT_KEYS` are lists, and the
  compatibility test is parametrized over every old name. A search for "reading lamp" missed the
  CamelCase class `ReadingLampTools` → when renaming, also search each old name without
  separators. `data/Lumen` vs the `lumen/` package has the same case-only clash as before.
- 2026-10-11 — First real Lightsail provisioning found two problems the scripts never hit
  offline: Lightsail names are unique across resource types (a key pair called `lumen` blocked
  the instance `lumen`), and Lightsail appends user data to its own `/bin/sh` launch script, so
  `#!/bin/bash` is ignored and `set -o pipefail` killed the first-boot setup in dash → key pair
  is `lumen-key`; `cloud-init.sh` is POSIX sh that runs the setup under bash, and can be re-run
  by hand (ADR 0041).
- 2026-10-11 — Bind-mounted secrets keep the host owner, not the container's: files uploaded by
  `ubuntu` (uid 1000) with mode 0600 are unreadable to the image's `lumen` user (uid 10001), so
  `deploy.sh` chowns `/opt/lumen/secrets` to 10001. The token file must also be writable,
  because `load_credentials` saves the refreshed token back.
- 2026-10-12 — Compose `env_file` values override the image's `ENV`, so a production `.env`
  copied from `.env.example` replaced `/secrets/...` and `/data/...` with relative paths that do
  not exist in the container (no Drive token, index outside the volume) → `.env.example` and
  the runbook say to delete the path lines from a Docker `.env`.
- 2026-10-12 — Third rename (Lumen → Lumitrace, ADR 0042): a blanket text replace also rewrote
  the compatibility lists, the compatibility test and the link to ADR 0009's file name → after
  the replace, add the old name back to `MARKER_PREFIXES` / `LEGACY_FORMAT_KEYS` and the test,
  and restore links to historical files. Lightsail cannot rename instances or static IPs, so an
  "everywhere" rename means replacing the server.

## Prism (recording API)

- 2026-10-19 — A photo-only Send on a closed day wrote `photo-01.jpg` and merged an eighth
  capture, then fill_day re-read an older Frame and wrote seven captures back → merge the
  in-memory captures into the fresh file before applying generated content, and include
  photo-only takes in `format_captures` (ADR 0065).
- 2026-10-19 — The Flash Home Screen app keeps a live page, so a capture from Shortcuts (or
  another device) does not show in History until a full reload, and iOS makes that reload
  awkward → a Refresh control on Recent captures fetches `/captures` in place, and opening the
  History tab does the same.
- 2026-10-19 — A take filed under the wrong day before Generate still sat in History with no
  way to remove it, and deleting only the audio would leave the transcript as source → discard
  the whole unused capture from the day file, media and status, and refuse once it is in the
  journal (ADR 0064).
- 2026-10-19 — Filing under defaulted to today and treating “today” as no date let a recording
  about yesterday land on the wrong day → require an explicit day, including today, before Send,
  and show a Select the date sheet if the chip is still untouched (ADR 0063).
- 2026-10-19 — A spoken Log My Day take only fills Format 6 cells the owner actually says, and a
  bullet checklist is too long to read at the microphone → a glanceable tile map stays on screen
  while talking, one card per speakable day-file field, opened by the red button (ADR 0062).
- 2026-10-19 — Sarvam returns HTTP 400 if any keyterm contains a comma or semicolon, including
  a long family-file name → split those separators into separate array items for STT only.
- 2026-10-19 — LiteLLM `num_retries` imports tenacity at call time; the image did not install it,
  so Gemini 3.8 Flash failed and a blank 3.6 Flash fill wrote an empty Format 6 day → add
  `tenacity` as a direct dependency and reject blank fill-day replies.
- 2026-10-19 — `--replace-generated` on a Format 5 day used `update_day` because the facts JSON
  had no journal, so the projection looked owner-edited and the story stayed in Time not stated
  → fill Format 6 from transcripts for a format upgrade or `--replace-generated`, then three-way
  merge owner edits (ADR 0061).
- 2026-10-19 — Format 5 generated-facts JSON has facts and journal but no `content`; constructing
  an empty `DayFile()` as the merge base raises `ValidationError` on every production day →
  project the previous model page with `from_legacy_day` (ADR 0061).
- 2026-10-19 — A model-owned Format 6 rewrite still has to three-way merge if the owner typed
  while generation ran; replacing the page would drop that sentence → apply complete content
  through `merge_content_generation_three_way` whenever the live page is already edited
  (ADR 0061).
- 2026-10-18 — Asking a model to rewrite a journal cannot guarantee that manual corrections stay;
  even a preservation prompt can paraphrase them → track processed source separately and let the
  model classify only new bullets while code inserts them into existing sections (ADR 0058).
- 2026-10-17 — Re-encoding a cropped voice note in the browser plays the slice back through
  `MediaRecorder`, so it takes as long as the kept audio and is a second encode → send the
  original blob when the handles are still at the ends (ADR 0054).
- 2026-10-17 — A second facts call plus an addendum, gated on whether the owner edited, did
  not match the day: transcripts wait until 4:05 a.m., then one fill, and a recording days
  later should only add what it says → `fill_day` and `update_day` only (ADR 0050).
- 2026-10-17 — Rewriting the journal on every short recording repeats the same day and spends a
  model call each time → save transcripts as they arrive and write the journal once, five
  minutes after the day rollover (ADR 0046).
- 2026-10-10 — pydantic `ValidationError` and `json.JSONDecodeError` messages echo their input,
  which for AI replies is content about the owner's day → activity records keep only the error
  type and count (`safe_error`, ADR 0012).
- 2026-10-10 — LiteLLM's `fallbacks` only react to provider errors, not to a reply that is not
  valid JSON or fails `DayFacts` → own task-model → fallback loop that treats invalid replies as
  failures (ADR 0014). An out-of-range `mood_score` alone is nulled instead of failing the reply.
- 2026-10-10 — `afconvert -d aac` encodes AAC fine on macOS, but inside a sandboxed process the
  AAC encoder is invisible (`afconvert -hf` lists no data formats for `m4af`) and it exits 2 →
  compression falls back to keeping the original; the real-encoder test skips there (ADR 0013).
- 2026-10-10 — Apple Shortcuts has no error handling: a failed "Get Contents of URL" just stops
  the shortcut → save to the Flash Inbox folder *before* uploading and delete only after the
  API returns a `capture_id` (`docs/flash.md`).
- 2026-10-10 — Unverified on a real iPhone: that a Form file field holding several photos sends
  one part per photo, and which Shortcuts actions run on Apple Watch → check on first use and
  correct `docs/flash.md`.

## Spectrum (indexer)

- 2026-10-10 — The API writes the day file and its `_system/generated/` snapshot one after the
  other, so a sync can see a new day file next to an old snapshot and blame the owner for the
  system's change → compare only when `generated_at` matches, ignore captures that exist only in
  the live file (ADR 0022).
- 2026-10-10 — Obsidian saves while you type, so each sync can see a half-finished edit → keep one
  edit-signal row per baseline and replace it with the newest version (ADR 0022).
- 2026-10-10 — The Drive change feed only knows files it has seen since the indexer started, so
  a deletion between restarts can be missed → daily full scan with reconciliation (ADR 0020).
- 2026-10-10 — sqlite-vec returns a stored vector by rowid (`SELECT embedding FROM passages_vec
  WHERE rowid = ?`), so unchanged passages can reuse vectors instead of re-embedding (ADR 0021).

## Lens (MCP server)

- 2026-10-10 — In mcp 2.x, sync tool functions run in a worker thread, so SQLite and LiteLLM
  calls in tools don't block the event loop → keep tools sync; open a connection per call.
- 2026-10-10 — sqlite-vec 0.1.9 accepts `rowid IN (subquery)` inside a vec0 KNN query → date
  filters apply before picking the k nearest (no post-filtering) (ADR 0030).
- 2026-10-10 — Passing raw AI-written queries to FTS5 `MATCH` breaks on quotes, `-`, `NEAR(`
  etc. → quote every word and OR them (ADR 0030).
- 2026-10-10 — The fake embedding is a hashed bag of words, so tests can't show meaning-only
  recall; RRF ordering and date filters are tested, retrieval quality needs the real model and
  the answer-quality check.
- 2026-10-10 — Browsers apply CSP `form-action` to the redirect after a form post, which would
  block the OAuth redirect back to the AI app → the login page sets no `form-action`.
- 2026-10-10 — OAuth not yet tried with the real Claude / ChatGPT connectors → on first
  connection, record any client quirks here.

## Models and prompts

- 2026-10-18 — A large family template invites a model to fill empty tables from routine or
  implication → make evidence boundaries, allowed small inferences, canonical field placement,
  exact update patches and a final validation checklist part of both prompts, then validate the
  reply into typed Format 6 content before rendering (ADR 0061).
- 2026-10-18 — Appending a complete new fact list onto an edited day, and refusing to change any
  journal sentence, left duplicate facts and a journal that contradicted the facts. The same
  fact has to collapse to one line, and a generated sentence a newer recording contradicts has
  to be replaceable, while a sentence the owner rewrote stays (ADR 0060). A duration the speaker
  gave as a range ("two or three episodes, half an hour each") was being stored as 90 minutes;
  minutes are only a number that was spoken.
- 2026-10-17 — Two model calls (facts, then journal) let the journal copy a bad fact list. One
  call should see the transcript and the day template and fill both (ADR 0049).
- 2026-10-17 — Sarvam's English translation kept assigning actions to the wrong person, so the
  journal was reading a second, worse text. Drop the translate job and give the journal the
  code-mixed Telugu transcript plus the glossary and keyterms (ADR 0048).
- 2026-10-12 — A real Telugu-English recording through `gpt-4o-transcribe` (language detection)
  came out as English words spelled in Telugu script with broken word boundaries and misheard
  names; `extract_facts-v2` on `gpt-4o-mini` then read a phrase meaning "in the car itself" as a
  lunch called "Carlone", gave the wife's park trip to the owner, missed that the child's "Dad"
  was the owner, and the journal model copied those facts and filled gaps ("got up early",
  "consoled her"). Causes: speech-to-text weak on code-mixed speech, prompts that didn't know
  the speaker, the relations or the language, and a journal prompt that trusted the facts →
  Sarvam with a code-mixed transcript plus an English translation (ADR 0015), prompts with the
  speaker, relations and who-did-what rules (ADR 0016). Fixing the day by hand recorded the
  corrections as edit signals, which give a before/after to compare the new versions against.
- 2026-10-13 — First real Sarvam recordings came back with `chars: 0` and no error: the
  Docker image's `mimetypes` has no `.m4a` type, the upload went out as
  `application/octet-stream`, and Sarvam "succeeded" on noise (6 characters vs 1,555 with
  `audio/x-m4a`, same file). macOS guessed `audio/mp4a-latm`, which Sarvam refuses outright, so
  it only showed in production → fixed content types per extension, an empty transcript is now a
  warning, and a new provider gets one real recording replayed against it before deploying.
  The same check showed `httpx` logging signed URLs at INFO → quieted in `setup_logging`.
- 2026-10-13 — With good Sarvam transcripts, the remaining errors came from the prompts and the
  facts model: "drop what the translation and original disagree on" dropped the parts the
  machine translation got wrong (pronouns, a parent calling himself "Dad", an idiom read as
  "excited"), and `gpt-4o-mini` copied breakfast into lunch and left the author's block empty.
  A dry run on one real day (generate only, no writes) compared models and prompt versions
  side by side in minutes → prompts follow the original (ADR 0018), `gpt-4.1` for facts and
  journal; dry-run any prompt change on a real day before deploying it.
- 2026-10-17 — A second agent reviewing Oct 12 to 15 found the same errors again: the machine
  translation gave actions to the wrong person ("Nanna" as "my father"), misheard words (potty
  → "party"), and mixed up similar names (a child and her daycare friend); the journal then
  invented meals, visits and health facts, and facts counted deliveries as visits. Lesson: the
  translation is a hint, the Telugu wins; relation words and names need a glossary; "unsure"
  must be written as unsure. Captured in the day template and the `lumitrace-telugu-day-journal`
  skill (ADR 0045); the prompts still need a version with the Nanna rules.
- 2026-10-18 — A long day's journal stopped before the last part of the recording, and an "I"
  drink was written as shared. The fill-day call already sent the whole transcript. The prompt
  capped the journal around 300 words and did not require the final third, and the model's
  output ceiling was left at the provider default. Day-level meals stayed empty because only
  per-person meals are in the JSON → cover the transcript to its last sentence, give an item
  to someone only when they are named or the speaker says "we", ask for the model's maximum
  output tokens, and fill the Everyone meals in code (ADR 0056).
- 2026-10-17 — Family names and the notes that fix mishearings were split across an environment
  variable and a skill file the server cannot read. One `secrets/family.md` feeds both. Usual
  routines in that file are easy for a model to write as if they happened today, so the prompt
  has to say they are background only (ADR 0047).
