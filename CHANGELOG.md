# Changelog

All notable changes. Format: [Keep a Changelog](https://keepachangelog.com/). Each work stream
edits only its own subsection under *Unreleased* to avoid merge conflicts.

## [Unreleased]

### Foundation

- Cloud Agent notes in `AGENTS.md`: uv 0.13.0 on `/usr/local/bin`, `uv sync --frozen`, and
  tmux sessions for Prism, Spectrum, and Lens with a generated offline `.env` when none exists.
- **Renamed the project from Lumen to Lumitrace** (decision 0042, supersedes 0009), everywhere;
  the module names (Flash, Prism, Frames, Spectrum, Lens) are unchanged. Entries below this one
  use the Lumen names.
  - Package `lumen` → `lumitrace` (git mv); commands `lumitrace-prism`, `lumitrace-spectrum`,
    `lumitrace-lens`, `lumitrace-drive-login`.
  - Environment prefix `LUMEN_` → `LUMITRACE_`; Drive root folder `Lumitrace`, local root
    `data/Lumitrace`, index `lumitrace.sqlite` (backup `_system/index-backup/lumitrace.sqlite`).
  - Docker image `lumitrace`, volume `lumitrace-data`; Lightsail instance `lumitrace`, static IP
    `lumitrace-ip`, key pair `lumitrace-key`, server folder `/opt/lumitrace`, Tailscale name
    `lumitrace`.
  - Day files are written with `lumitrace:` markers and `lumitrace_format`; `lumen:` files (and the
    two older generations) are still read, and the compatibility test covers all three. Prompt
    markers are `lumitrace-prompt:`; the OAuth scope is `lumitrace`; AI apps list "Lumitrace".
  - Shortcut **Send to Lumen** → **Send to Lumitrace**. Upgrading: `docs/runbook.md` →
    *Upgrading from LifeLog, Bookshelf or Lumen*.
- `docs/tech-stack.md`: every language, library, tool, AI provider, service and client Lumen
  uses, grouped by module (shared, Flash, Prism, Frames, Spectrum, Lens, deployment,
  development), with versions, what each is for, and whether it is open source (license).
  Linked from README.
- **Renamed the project from Bookshelf to Lumen** (decision 0009, supersedes 0008): *A Flash
  captures the moment, the Prism splits it into its colors, each day becomes a Frame, the
  Spectrum lays everything out in order, and the Lens lets you zoom into any day.* Name map in
  README and AGENTS.md.
  - Package `bookshelf` → `lumen` (git mv): `typewriter` → `lumen/prism/` (pipeline in
    `lumen/prism/pipeline/`), `books` → `lumen/frames/`, `bookmarks` → `lumen/spectrum/`,
    `reading_lamp` → `lumen/lens/` (`ReadingLampTools` → `LensTools`). Shared modules stay at
    the top. Tests mirror the layout (`tests/prism/`, `tests/frames/`, `tests/spectrum/`,
    `tests/lens/`).
  - Commands `lumen-prism`, `lumen-spectrum`, `lumen-lens`, `lumen-drive-login` replace the
    `bookshelf-*` commands.
  - Environment prefix `BOOKSHELF_` → `LUMEN_`; default Drive root folder `Lumen`, local root
    `data/Lumen`, index `data/index/lumen.sqlite` (backup `_system/index-backup/lumen.sqlite`).
    `_system/` subfolders unchanged.
  - Docker: image `lumen`, services `prism`, `spectrum` (port still internal) and `lens`, volume
    `lumen-data`.
  - The Lens shows itself to AI apps as "Lumen"; OAuth scope `lumen`.
  - Day files are written with `lumen:` markers and `lumen_format`; files with `bookshelf:` or
    `lifelog:` markers and `bookshelf_format` or `lifelog_format` are still read (the
    compatibility test now covers both). Prompt markers are `lumen-prompt:`.
  - Docs renamed: `prism.md`, `spectrum.md`, `lens.md`, `flash.md`, `frames-format.md`.
    Shortcuts **Flash Config**, **Flash Inbox** and **Send to Lumen** replace Notepad Config,
    Notepad Inbox and Send to Bookshelf; Log My Day, Quick Note and Send pending keep their
    names.
  - Upgrading an existing setup (from LifeLog or Bookshelf): `docs/runbook.md` → *Upgrading
    from LifeLog or Bookshelf*. The repository folder is renamed to `lumen` separately.
- **Renamed the project from LifeLog to Bookshelf** (decision 0008, superseded by the Lumen
  rename above; names in this entry are the Bookshelf ones): *you jot it on the
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
- **Day file format 2** (decision 0040): the facts move from the front matter into an
  `## At a glance` section under the title (`lumen:facts` markers): Mood, City and Weather
  lines, then Food, Places, People, Activities, Family and Highlights. New facts `places` and
  `family` (one `#### name` block per family member: Mood, Ate, Went to, Did, Moments, Health,
  School/work); `family_events` is removed. Values are normalised so render and parse agree,
  and hand edits are tolerated (unplaceable lines move into My notes). Format 1 files are still
  read: their `family_events` go into highlights and an unedited day stays unedited. New
  setting `LUMEN_FAMILY` (comma-separated names; `Settings.family_members`).
- **Strict, identical layout every day:** "At a glance" always has the same lines in the same
  order, with `none` for empty ones (all six sections, five Food lines, seven lines per family
  member; `NONE_TEXT`). Meal types are fixed (`MEAL_TYPES`: breakfast, lunch, dinner, snacks,
  drinks; synonyms mapped, anything else → snacks). Generated journals only use the headings
  Summary, Morning, Afternoon, Evening, Thoughts and Later (`normalize_journal`, applied by
  `apply_generation`); additions to edited days go under `## Later` with a bold time label
  (`merge_generation_additive(addendum_label=...)`, formerly `addendum_heading`, which wrote a
  `###` heading). `render_facts_section(..., include_empty=False)` gives the view without
  `none` lines.
- Index schema version 2: new tables `places` and `family_facts`, `family_events` removed.
- **AWS Lightsail deployment** (decision 0041): `deploy/lightsail/` scripts create a 2 GB
  instance in `us-east-2` (SSH key, daily snapshots, static IP, SSH-only firewall), deploy the
  committed code with ports bound to localhost, and publish the Prism on the tailnet and the
  Lens through Tailscale Funnel. Steps in `docs/runbook.md` → *Deploying on AWS Lightsail*.
  Fixed after the first real run: the SSH key pair is named `lumen-key` (Lightsail names are
  unique across resource types), and `cloud-init.sh` is POSIX sh running the setup under bash
  (Lightsail runs user data with `/bin/sh`, where `pipefail` failed); it can be re-run by hand.
  `deploy.sh` now gives the uploaded `secrets/` to the container user (uid 10001), which
  otherwise could not read or refresh the Google Drive token. `.env.example` and the runbook
  warn that a Docker `.env` must not set the path settings (they override the image's container
  paths). `docs/flash.md` now uses the Prism address `tailscale.sh` serves
  (`https://<machine>.<tailnet>.ts.net:8443`).

### Prism (recording API)

- Documented that an empty `LUMEN_STT_LANGUAGE` lets the speech model detect the language per
  recording, for mixed speech such as Telugu and English (`.env.example`, `docs/prism.md`).
- Prompt `extract_facts` v2: extracts `places` and per-member `family` facts for the names in
  `LUMEN_FAMILY` (new `{{family}}` placeholder); anyone else is dropped and names are spelled as
  configured (`keep_family`). Every configured member gets a block, empty if the day says
  nothing about them. Meal types in the prompt are the fixed five. Additive generation also
  merges places and family blocks, and late additions go under `## Later`.

### Spectrum (indexer)

- Indexes `places` and `family_facts` from the day file's "At a glance" section; facts
  passages are that section's rendered text without its `none` lines, one passage per heading
  (one per family member with facts).
- Rebuilds automatically when the index's schema version differs from the current one.

### Lens (MCP server)

- `query_facts` kinds `places` and `family` (replacing `family_events`), with a `person`
  filter for family and aggregates `by_place`, `by_person_and_category` and `top_items`.
  `on_this_day` returns `places` and `family` rows.

## [0.1.0] - 2026-10-10

Released as **LifeLog**; the names below are the ones it shipped with (see *Unreleased* for the
renames to Bookshelf and then Lumen).

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
