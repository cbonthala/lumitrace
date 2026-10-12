# Learnings

What we learned about quality, models, prompts and operations, and what to change next.
Personal details are always removed; the full weekly reports live in `Lumen/_system/reports/`.

Entry format: `- YYYY-MM-DD — observation → action (link to PR/ADR)`.

## Foundation

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

## Prism (recording API)

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
