# Spectrum (indexer)

The Spectrum lays everything out in order: it keeps the SQLite index (`docs/index-schema.md`)
in step with the Frames (the day files in storage). Command: `lumitrace-spectrum`; Docker service:
`spectrum` (port 8001, never published). Code: `lumitrace/spectrum/`; the schema module stays
shared in `lumitrace/index/schema.py`. Spectrum is the only writer of the derived tables and of
`edit_signals`; the Lens (MCP server) reads them.

| Module | What it does |
|---|---|
| `core.py` | `Indexer`: `sync`, `index_paths`, `rebuild`, `backup`; legacy fact rows and flattened Format 6 `content_facts` |
| `passages.py` | splits canonical Format 6 content or legacy facts/journal into passages |
| `edits.py` | compares Format 6 top-level content (or legacy facts/journal) with the generated snapshot |
| `backup.py` | SQLite backup API → `_system/index-backup/lumitrace.sqlite` |
| `service.py` | `run`: worker thread + FastAPI app (`POST /nudge`, `GET /health`) |
| `__main__.py` | the `lumitrace-spectrum` CLI |

## Commands

```bash
uv run lumitrace-spectrum run          # default: HTTP server + poll loop + daily backup
uv run lumitrace-spectrum sync         # one incremental sync, then exit
uv run lumitrace-spectrum sync --full  # list every file instead of using the sync token
uv run lumitrace-spectrum rebuild      # empty derived tables (keeps feedback, edit_signals), index all
uv run lumitrace-spectrum backup       # copy the index to storage now
```

`sync` and `rebuild` print a JSON summary such as
`{"kind": "sync", "indexed": 1, "skipped": 0, "deleted": 0, "edit_signals": 0, "malformed": [],
"failed": [], "seconds": 0.4}` and exit with status 1 if a file failed with a transient error
(it is retried on the next sync). In Docker: `docker compose run --rm spectrum lumitrace-spectrum sync`.

Settings used: `LUMITRACE_INDEX_PATH`, `LUMITRACE_EMBEDDING_MODEL`, `LUMITRACE_EMBEDDING_DIMENSION`,
`LUMITRACE_INDEXER_HOST`, `LUMITRACE_INDEXER_PORT`, `LUMITRACE_INDEXER_POLL_INTERVAL_SECONDS`,
`LUMITRACE_INDEXER_BACKUP_INTERVAL_HOURS`, plus the storage settings.

## HTTP interface (`run`)

| Method | Path | Body | Reply |
|---|---|---|---|
| `POST` | `/nudge` | `{"paths": ["2026/10/2026-10-10/2026-10-10.md", ...]}` (optional, may be empty) | `202 {"accepted": true, "paths": <n queued>}`; `422` if `paths` is not a list of strings |
| `GET` | `/health` | | `200` with worker state, `pending_paths`, `last_cycle_at`, `last_result` (counts and storage paths only), `last_error` (exception type); `503` if the worker thread died |

No authentication: the indexer is internal (`expose`, not `ports`, in `docker-compose.yml`), and a
nudge can only make it re-read storage sooner. Don't publish port 8001.

## Sync loop and nudges

One worker thread owns the index connection and does every write, one cycle at a time:

1. Index the nudged paths directly (`index_paths`): `stat` each one, index it if it exists,
   remove it from the index if it doesn't. Nudged paths don't wait for the storage change feed,
   which on Google Drive can lag by a few seconds.
2. `sync`: `storage.list_changes(meta.sync_token)`, then process the changes (below). Once every
   24 hours the cycle is a **full scan** instead (`list_changes(None)`), which also removes index
   entries for day files that no longer exist, so a missed deletion is repaired within a day.
3. Back up if `LUMITRACE_INDEXER_BACKUP_INTERVAL_HOURS` have passed (see Backups).
4. Sleep until the next poll (`LUMITRACE_INDEXER_POLL_INTERVAL_SECONDS`) or until a nudge arrives,
   then wait one second so a burst of writes (day file, snapshot, activity record) is handled
   in one cycle.

Processing changes:

* **Day files** (`YYYY/MM/YYYY-MM-DD/YYYY-MM-DD.md`, `classify_path == "day"`) are indexed.
* **Generated snapshots** (`_system/generated/YYYY/MM/YYYY-MM-DD.md`) only trigger an edit-signal
  check for that day when the day file itself did not change in the same batch.
* **Everything else** (audio, photos, other Markdown such as Obsidian notes in day folders, the
  rest of `_system/`) is ignored and never downloaded.
* **Unchanged files are skipped twice over:** if the modification time equals `files.modified_at`
  the file is not downloaded; otherwise its sha256 is compared with `files.content_hash`.
* **Deletions** remove the `days` row (fact tables cascade) and the `files` row (passages, FTS
  and vectors cascade). `feedback` and `edit_signals` are never touched.
* **Malformed files** (invalid front matter, bad capture metadata, not UTF-8): a warning names
  the path and the error type (never the content), the file's hash is recorded so it isn't
  re-read until it changes, and the day keeps its last good index. The path is listed in the
  result's `malformed`.
* **Transient failures** (storage errors, embedding API errors) put the path in
  `meta.indexer_retry_paths`; the next sync retries it even if storage reports nothing new.
* **A rejected sync token** (for example after switching storage backends) falls back to a full
  scan.
* **Front matter date ≠ folder date:** the folder wins (with a warning), so one file per date.

Each day file is written in **one transaction**: `files` upsert, `days` and fact rows replaced,
passages and vectors replaced, edit signals. The MCP server always sees a whole day, old or new.

Spectrum stores both contracts:

* Existing `days`, meals, activities, people, places, family facts and highlights come from
  `DayFile.facts`. For Format 5 and older this is the parsed At a glance section; for Format 6 it
  is the compatibility projection from `DayContent`.
* Schema version 4 adds `content_facts`. `content_for_day` gives every readable file a canonical
  `DayContent`, then Spectrum flattens its timeline, context, every family tracker, pregnancy
  tracker and tags into rows with `scope`, optional `person`, `category`, `field`, text, number,
  meal status, optional complete JSON details and stable position.

The legacy fact schema keeps `meals.meal_type` as one of `breakfast`, `lunch`, `dinner`,
`snacks`; one `meals` row per item with the `person` whose block it is under (`''` for
`Everyone`); `not mentioned` placeholders never become rows; one `places`, `people` and
`activities` row per bullet; one `family_facts` row per item under a person (`category` =
`feelings`, `health` or `moments`; `person` = `Together` for the shared memories);
`days.remember` is the Remember line; and `position` keeps the order in the file. `days.user_edited` is `DayFile.is_user_edited()`.

**Schema changes:** if the index's `meta.schema_version` differs from `SCHEMA_VERSION` (for
example schema 4 added `content_facts` for Format 6), `sync` and `run` rebuild automatically,
like an embedding model change below.

## Passages and embeddings

`build_passages(day)` produces, in order (max 1,000 characters each, `ordinal` counts within a
section):

| Section | Content | `heading` | `capture_id` |
|---|---|---|---|
| `title` | the `# title` | | |
| `content` | Format 6 canonical content rendered from `DayContent`, split at timeline and tracker headings | `Highlight`, `Morning`, `Food`, `Pregnancy and baby`, `Tags`, ... | |
| `facts` | legacy facts without empty lines (`render_facts_section(facts, include_empty=False)`), split at headings | heading text (`Food`, ..., the member's name) | |
| `journal` | legacy journal split at Markdown headings | heading text | |
| `notes` | same as journal; a heading with no text under it is its own passage | heading text | |
| `transcript` | one or more passages per capture, then its English translation (if any) as more passages | `21:30 · Log My Day`; translation: `21:30 · Log My Day · English` | capture id |

Long text is cut at paragraph, then sentence, then word boundaries (`chunk_text`).

The embedded text is `heading + "\n" + text` (or just `text`), and `passages.text_hash` is the
sha256 of exactly that. When a day is re-indexed, vectors whose hash is unchanged are reused, so
adding a quick note only embeds the new passages. New passages from up to 16 changed files are
embedded together with `lumitrace.embeddings.embed_texts` (which batches API calls by 64).

The FTS5 and vec rows follow `passages` through the schema triggers (and an explicit insert into
`passages_vec` with the same rowid).

## Embedding model changes

`meta.embedding_model` and `meta.embedding_dimension` record what the vectors were made with.
If the settings differ when the indexer opens the index, `sync` and `run` **rebuild
automatically** (logged as a warning): vectors from two models can't be compared, and the MCP
server must embed queries with the same model. `rebuild` recreates `passages_vec` with the new
dimension. See `docs/runbook.md` → *Changing the embedding model*.

## Edit signals

When a day file is indexed (or its snapshot changes), it is compared with
`_system/generated/YYYY/MM/YYYY-MM-DD.md`, the exact file the recording API last wrote:

* Format 6 `content`: one comparison for each top-level field (`timeline`, `family`,
  `pregnancy_baby`, `tags`); `before`/`after` are JSON and `diff` is empty.
* Legacy `facts`: one comparison per fact field; `field` = fact name, `before`/`after` = JSON,
  no diff.
* `title`, legacy `journal`, `notes`: whole text; `diff` = unified diff
  (`--- generated` / `+++ edited`).
* `transcript`: one comparison per capture in the snapshot; `field` = capture id. Captures only
  in the live file are new system captures, not edits; a deleted capture has `after = ""`.
* `prompt_version` and `models_used_json` come from the snapshot (what produced the text).

Rules (ADR 0022):

* Compare only if both files have the same `generated_at`. Otherwise they come from different
  system writes (for example, the indexer read the new day file before the API wrote its new
  snapshot) and the difference isn't the owner's.
* **One row per (date, section, field, before):** a later edit of the same text replaces the
  earlier row; reverting the edit deletes it. Rows whose `before` belongs to an older snapshot
  are kept. `signal_hash` = sha256 of `date|section|field|before|after`, inserted with
  `INSERT OR IGNORE`, so re-indexing and rebuilds never duplicate.
* No snapshot (owner-created day, or a day written before snapshots existed) → no signals.

Signals stay in the index (and its backup) in the owner's storage; nothing goes to the repo.

`days.user_edited` uses `DayFile.is_user_edited()`, whose Format 6 hash covers the complete typed
content. The content signal granularity is deliberately top-level, not one row per nested table
cell.

## Backups

Every `LUMITRACE_INDEXER_BACKUP_INTERVAL_HOURS` (default 24; `0` disables) the `run` loop copies
the index with SQLite's online backup API to a temporary file, switches the copy to
rollback-journal mode (one self-contained file), and writes it to
`_system/index-backup/lumitrace.sqlite` (one file, overwritten; Drive keeps earlier revisions for
a while). The time is stored in `meta.last_backup_at`. `lumitrace-spectrum backup` does it now.
The backup includes `feedback` and `edit_signals`, the only data that a rebuild can't restore.

## Meta keys written by Spectrum

`sync_token`, `last_sync_at`, `last_rebuild_at`, `embedding_model`, `embedding_dimension` (see
`docs/index-schema.md`), plus `indexer_retry_paths` (JSON list), `last_full_scan_at` and
`last_backup_at` (ISO-8601 UTC).

## Known limits

* A rebuild is done in place, file by file: while it runs, search results are incomplete.
* An owner edit the indexer has not seen yet when the next capture for that day is processed
  produces no edit signal: the API's new snapshot already contains the edit (the edit itself is
  kept). With the default 5-minute poll this needs an edit and a capture minutes apart; Obsidian
  edits don't nudge the indexer.
* Notes the owner creates in Obsidian (other `.md` files) are not indexed (open question in the
  plan; `drive.file` can't see them anyway).
* The daily full scan on Google Drive lists every file in the `Lumitrace` folder; it only downloads
  day files whose modification time changed.
