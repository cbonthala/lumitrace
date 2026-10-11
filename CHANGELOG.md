# Changelog

All notable changes. Format: [Keep a Changelog](https://keepachangelog.com/). Each work stream
edits only its own subsection under *Unreleased* to avoid merge conflicts.

## [Unreleased]

### Foundation

- **Renamed the project from LifeLog to Bookshelf** (decision 0008): *you jot it on the
  Notepad, the Typewriter turns it into Books, Bookmarks mark every page worth finding, and the
  Reading Lamp lets you read any of it.* Name map in README and AGENTS.md.
  - Package `lifelog` → `bookshelf`: `api` + `pipeline` → `bookshelf/typewriter/` (pipeline in
    `bookshelf/typewriter/pipeline/`), `indexer` → `bookshelf/bookmarks/`, `mcp_server` →
    `bookshelf/reading_lamp/`, `dayfile.py` + `storage/` → `bookshelf/books/`. `config`,
    `embeddings`, `nudge`, `logging_setup` and `index/schema.py` stay shared at the top. Tests
    mirror the layout (`tests/typewriter/`, `tests/bookmarks/`, `tests/reading_lamp/`,
    `tests/books/`).
  - Commands `bookshelf-typewriter`, `bookshelf-bookmarks`, `bookshelf-reading-lamp`,
    `bookshelf-drive-login` replace `lifelog-api`, `lifelog-indexer`, `lifelog-mcp`,
    `lifelog-gdrive-login`. `bookshelf-typewriter --help` now prints help instead of starting
    the server.
  - Environment prefix `LIFELOG_` → `BOOKSHELF_`; default Drive root folder `Bookshelf`, local
    root `data/Bookshelf`, index `data/index/bookshelf.sqlite` (backup
    `_system/index-backup/bookshelf.sqlite`). `_system/` subfolders unchanged.
  - Docker: image `bookshelf`, services `typewriter`, `bookmarks` (port still internal) and
    `reading-lamp`, volume `bookshelf-data`.
  - Reading Lamp shows itself to AI apps as "Bookshelf"; OAuth scope `bookshelf`.
  - Day files are written with `bookshelf:` markers and `bookshelf_format`; files with the old
    `lifelog:` markers and `lifelog_format` are still read. Prompt markers are
    `bookshelf-prompt:`.
  - Docs renamed: `typewriter.md`, `bookmarks.md`, `reading-lamp.md`, `notepad.md`,
    `books-format.md`. Shortcuts "LifeLog Config", "LifeLog Inbox" and "Send to LifeLog" are now
    **Notepad Config**, **Notepad Inbox** and **Send to Bookshelf**; Log My Day and Quick Note
    keep their names.
  - Upgrading an existing setup: `docs/runbook.md` → *Upgrading from LifeLog*.
- `docs/test-cases.md`: a plain-English catalog of every test, grouped by component and
  feature, with an end-to-end story, a "covered / not covered" line per component and each
  test's name for tracing. `tests/test_docs_test_cases.py` fails when a test is missing from
  the catalog or the catalog names a test that no longer exists. AGENTS.md rule 8 requires
  describing every new or changed test; linked from README and `docs/architecture.md`;
  decision 0007.

### Typewriter (recording API)

### Bookmarks (indexer)

### Reading Lamp (MCP server)

## [0.1.0] - 2026-10-10

Released as **LifeLog**; the names below are the ones it shipped with (see *Unreleased* for the
rename to Bookshelf).

First working version: record on the iPhone, get a Markdown day file in storage, read it in
Obsidian, ask through MCP. Tested offline end to end; not yet verified with real providers, real
Google Drive, the iPhone Shortcuts on a device or the Claude/ChatGPT connectors.

### Foundation

- Project setup: Python 3.12, uv, ruff, pytest; one `lifelog` package.
- `lifelog.config.Settings` covering API, storage, speech, LLM, embeddings, index and MCP
  settings; `.env.example` documents every variable.
- Swappable storage: `Storage` interface, `LocalStorage`, `GDriveStorage` (`drive.file` scope,
  changes API, share links) and the `lifelog-gdrive-login` command.
- Day-file contract `lifelog.dayfile`: paths, 4 a.m. rollover, `DayFile` model, lossless
  parse/render, `merge_capture`, edit-safe `apply_generation` / `merge_generation_additive`.
- Index contract `lifelog.index.schema`: facts, passages, FTS5, sqlite-vec, files, edit signals,
  feedback, meta.
- Shared helpers: `lifelog.embeddings.embed_texts` (with offline `fake` model) and
  `lifelog.nudge.nudge_indexer`.
- Entry points `lifelog-api`, `lifelog-indexer`, `lifelog-mcp`, `lifelog-gdrive-login`.
- Dockerfile (Python 3.12 slim, ffmpeg, uv) and docker-compose with api, indexer and mcp sharing
  a data volume; only the API and MCP ports are published (the indexer's `/nudge` stays inside
  the Compose network).
- Dependencies: `boto3` declared explicitly (Amazon Transcribe); `mcp>=2.0` (the code uses the
  2.x `MCPServer` API).
- Docs: AGENTS.md, README, architecture, contracts, day-file format, index schema, decisions
  0001–0006, runbook, learnings, prompts README.

### Recording API

- `POST /recordings` (multipart: `audio`, `photos`/`photos[]`, `lat`, `lon`, `place`,
  `captured_at`, `capture_id`) and `POST /notes` (`text` and/or an `audio` clip and/or photos;
  multipart, urlencoded or JSON) with bearer-token auth (constant-time, fails closed with `503`
  when the token is missing, `change-me` or shorter than 16 characters). `202` with the capture
  id, entry date and a notification message.
- `GET /captures/{id}` status and `POST /captures/{id}/retry`; `GET /health` unchanged.
- Durable inbox: uploads saved to `_system/inbox/<id>/` (manifest last) and a status file in
  `_system/captures/` before answering; one background worker processes captures in order,
  retries failures after 60 s and 10 min, and resumes the inbox on start-up. Client
  `capture_id`s make retries idempotent (`200 duplicate`).
- Pipeline (`lifelog/pipeline/`): speech to text via `litellm`, `aws_transcribe` (S3 batch job
  with cleanup) or `fake`; audio compressed to mono AAC `.m4a` with ffmpeg → afconvert → original
  kept with a warning; photos (incl. HEIC) resized to JPEG without EXIF and numbered with
  `next_photo_names`; transcript saved to the day file before any AI step.
- AI steps through LiteLLM with JSON validated against `DayFacts`, per-task model plus fallback
  model (also on invalid replies) and an offline `fake` model. Unedited days are fully
  regenerated (`apply_generation`, title with a headline); edited days get additive facts and a
  journal addendum (`merge_generation_additive`); the day is re-read before writing so edits
  made during generation are kept. `prompt_version` and `models_used` recorded in front matter;
  `_system/generated/` snapshot written with every day-file write.
- Prompts `prompts/extract_facts/v1.md`, `write_journal/v1.md`, `journal_addendum/v1.md` (system
  and user parts, `{{placeholders}}`).
- Activity records: one JSON line per attempt in `_system/activity/YYYY/MM.jsonl` with models,
  prompt versions, per-step timings, LiteLLM cost and content-free errors.
- Indexer nudged after each capture (failures recorded, never fatal).
- Docs: `docs/recording-api.md`, `docs/iphone-shortcuts.md` (Log My Day, Quick Note, Send
  pending, share sheet, nightly reminder, triggers, Tailscale/HTTPS, token handling), decisions
  0010–0014, prompts README, runbook and learnings.

### Indexer

- `lifelog-indexer` with `run` (poll loop, `POST /nudge` → 202, `GET /health`, daily backup),
  `sync` (`--full`), `rebuild` and `backup`; JSON summaries, exit 1 on transient failures.
- Incremental sync from the storage change token; skips unchanged files by modification time and
  content hash; handles deletions; retries transient failures (`meta.indexer_retry_paths`);
  daily full scan repairs missed changes; a rejected token falls back to a full scan.
- Day files indexed in one transaction each: `days`, fact tables (meal types lower-cased),
  passages (title, facts, journal/notes by heading, transcript per capture; max 1,000 chars),
  FTS5 and sqlite-vec rows. Unchanged passages reuse their vectors.
- Malformed day files are logged (path and error type only) and keep their last good index.
- Edit signals: live file vs `_system/generated/` snapshot, per fact / title / journal / notes /
  transcript capture, with unified diffs; only for the same `generated_at`; one row per baseline.
- Automatic rebuild when the embedding model or dimension changes; feedback and edit signals kept.
- Index backup to `_system/index-backup/lifelog.sqlite` with SQLite's backup API.
- Docs: `docs/indexer.md`, decisions 0020–0024, runbook steps for rebuilding, recovering a lost
  index and changing the embedding model.

### MCP server

- `lifelog-mcp` replaces the placeholder: tools `search`, `get_day`, `query_facts`,
  `on_this_day` and `feedback`, with server instructions to answer only from the entries, cite
  dates and say when nothing was found. Dates are `YYYY-MM-DD` (plus `today` / `yesterday`, and
  `MM-DD` for `on_this_day`).
- `search`: FTS5 bm25 + sqlite-vec cosine merged with reciprocal rank fusion; date filters in
  SQL on both sides; keyword-only fallback when embedding fails or the model differs.
- `get_day` reads the day file from storage and returns private audio/photo links;
  `query_facts` returns rows plus counts and aggregates; `feedback` writes the `feedback` table
  and a JSON copy under `_system/feedback/`.
- Per-call read-only index connections; missing or empty index returns a friendly note.
- Transports stdio and streamable HTTP; auth modes `none`, `token` (bearer) and `oauth`
  (single-owner OAuth 2.1: dynamic client registration, PKCE, password page, refresh rotation,
  revocation, hashed tokens persisted next to the index). `GET /health`.
  `lifelog-mcp --transport stdio` and `lifelog-mcp reset-oauth`.
- `tests/test_entrypoints.py`: the MCP check now lists the five tools instead of `ping`.
- Docs: `docs/mcp-server.md` (tools, auth, Claude / ChatGPT / Claude Desktop / Cursor setup,
  privacy), decisions 0030–0033, runbook steps for tokens, OAuth reset and troubleshooting.

### Integration

- `tests/e2e/test_full_flow.py`: the three programs in-process on local storage with offline
  providers. Captures (recording with photo, notes, one from last year) go through the API; the
  indexer is updated only by the API's real `/nudge` calls; every MCP tool is called over MCP and
  finds the content under the right date; an owner edit yields edit signals; a later capture for
  the edited day is merged additively and the edit (and its signals) survive.
- The recording API now refuses placeholder and short tokens like the MCP server does (it only
  logged a warning before, so `change-me` from `.env.example` was accepted).
- Docs: README quick start, AGENTS.md status and cross-component rules, architecture, the full
  `_system/` layout in `docs/contracts.md` (activity records are in `_system/activity/`, not
  `_system/runs/`), `.env.example` notes on token refusal and the `fake` models, and a
  first-run checklist in `docs/runbook.md`.
