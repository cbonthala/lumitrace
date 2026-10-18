# Index schema (schema version 3)

One SQLite file (`LUMITRACE_INDEX_PATH`, default `data/index/lumitrace.sqlite`) with FTS5 keyword
search and sqlite-vec vector search. Code: `lumitrace/index/schema.py` (shared: Spectrum writes,
the Lens reads). Open it only with `connect(path, embedding_dimension)`, which loads
sqlite-vec, creates the schema, turns on foreign keys and WAL, sets a 5-second busy timeout and
returns `sqlite3.Row` rows.

The index is **disposable**: everything except `feedback` and `edit_signals` can be rebuilt from
the Markdown files with `reset_derived(conn)` followed by a full sync.

## Writers

* **Spectrum** (indexer): all derived tables, `meta`, `edit_signals`.
* **Lens** (MCP server): `feedback` only (and reads everything else).

## Tables

### `meta(key PRIMARY KEY, value)`

| key | value |
|---|---|
| `schema_version` | `"3"`; Spectrum rebuilds the index when it differs from `SCHEMA_VERSION` |
| `embedding_model` | model the vectors were made with |
| `embedding_dimension` | vector size; `connect` raises `EmbeddingDimensionMismatch` if settings differ |
| `sync_token` | last `Storage.list_changes` token (cleared by `reset_derived`) |
| `last_sync_at`, `last_rebuild_at` | ISO-8601 UTC |
| `indexer_retry_paths` | JSON list of paths that failed transiently; retried next sync (indexer) |
| `last_full_scan_at`, `last_backup_at` | ISO-8601 UTC (indexer; see `docs/spectrum.md`) |

### `files`: every storage file seen (incremental updates)

`path` (PK, storage path), `kind` (`classify_path`: day/audio/photo/system/other), `date`
(YYYY-MM-DD or NULL), `content_hash` (sha256 hex of the bytes; skip re-indexing when unchanged),
`size`, `modified_at`, `indexed_at`. The indexer currently records day files only (including
malformed ones, so they aren't re-read until they change); audio, photos and `_system/` files
are not downloaded.

### `days`: one row per day file

`date` (PK), `path`, `title`, `mood`, `mood_score`, `city`, `weather`, `audio_json`,
`photos_json` (JSON lists of file names), `prompt_version`, `models_used_json`, `generated_at`,
`generated_hash`, `user_edited` (0/1), `capture_count`.

### Fact tables (all `ON DELETE CASCADE` from `days.date`)

| Table | Columns (plus `id`, `date`, `position`) |
|---|---|
| `meals` | `person` (`''` for the `Everyone` block: each item names who had it, e.g. `oatmeal (Maya, Leo)`), `meal_type` (`breakfast`, `lunch`, `dinner` or `snacks`), `item` (one row per item) |
| `activities` | `kind`, `minutes` |
| `people` | `name` (index with `COLLATE NOCASE`) |
| `places` | `name` (index with `COLLATE NOCASE`) |
| `family_facts` | `person`, `category`, `text`, `minutes` (index on `person COLLATE NOCASE, category`) |
| `highlights` | `text` |

`days.remember` holds the day's one-line `Remember` recap. `family_facts` has one row per item
under a person's block: `category` is `feelings`, `health` or `moments` (their memories); the
family's shared memories (`#### Together`) are rows with `person` = `Together`. Schema version 2
had the categories `mood`, `food`, `places`, `activities` and `school` (now meals, places and
things we did) and no `meals.person`; version 1 had `family_events(text)`. `reset_derived`
drops and recreates all fact tables, so an index from an older schema is rebuilt with the
current columns.

Re-indexing a day = `DELETE FROM days WHERE date = ?` (cascades) then insert again.

### `passages`: searchable chunks

`id` (PK; also the rowid in `passages_fts` and `passages_vec`), `path` (FK → `files.path`,
cascade), `date`, `section` (`title` | `journal` | `notes` | `transcript` | `facts`), `heading`,
`capture_id` (for transcript passages), `ordinal`, `text`, `text_hash` (sha256 of the embedded
input, `heading + "\n" + text` or just `text`; reuse an existing embedding when unchanged).

### `passages_fts`: FTS5, external content

`fts5(text, section UNINDEXED, date UNINDEXED, content='passages', content_rowid='id',
tokenize='porter unicode61 remove_diacritics 2')`. Kept in sync by triggers on `passages`;
never write to it directly. Query: `SELECT rowid, bm25(passages_fts) FROM passages_fts WHERE
passages_fts MATCH ? ORDER BY bm25(passages_fts)`.

### `passages_vec`: sqlite-vec

`vec0(embedding float[N] distance_metric=cosine)` where `N = embedding_dimension`; rowid =
`passages.id`. Insert with `serialize_embedding(vector)`. Deleting a passage deletes its vector
(trigger). Query: `SELECT rowid, distance FROM passages_vec WHERE embedding MATCH ? AND k = ?
ORDER BY distance`.

### `edit_signals`: the owner's edits (preserved on rebuild)

`id`, `date`, `path`, `detected_at`, `section` (facts/title/journal/notes/transcript), `field`
(fact name for facts, capture id for transcript, NULL otherwise), `before` (system version; JSON for facts), `after` (owner's version),
`diff` (unified diff for text), `prompt_version`, `models_used_json`, `signal_hash` (UNIQUE;
sha256 of date|section|field|before|after; insert with `INSERT OR IGNORE`).

### `feedback`: MCP `feedback` tool (preserved on rebuild)

`id`, `created_at`, `rating` (`wrong` | `incomplete` | `good` | `other`), `question`, `answer`,
`comment`, `dates_json`, `tool`, `client`, `storage_path` (the JSON copy under
`_system/feedback/`, which is the durable record).

## Changing the schema

Bump `SCHEMA_VERSION`. Because the index is disposable, the simplest migration is a rebuild,
and Spectrum does it on its own when the stored `schema_version` differs (`open_index`); if `feedback` or `edit_signals` change, write a real migration that keeps their rows. Update this
page, `docs/contracts.md` and `CHANGELOG.md`.
