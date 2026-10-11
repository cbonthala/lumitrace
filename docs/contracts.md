# Shared contracts

The interfaces the Typewriter (recording API), Bookmarks (indexer) and the Reading Lamp (MCP
server) build on. They are implemented and
tested (`tests/`); this page is the quick reference. Changing any of them is a cross-cutting
change: update every caller, the tests, this page and `CHANGELOG.md` in one commit.

## Config: `bookshelf.config`

`Settings` (pydantic-settings, env prefix `BOOKSHELF_`, reads `.env`), `get_settings()` (cached).
Field names keep their technical prefixes (`api_*` = Typewriter, `indexer_*` = Bookmarks,
`mcp_*` = Reading Lamp), so `BOOKSHELF_API_TOKEN` is the Typewriter's token.
Tests construct `Settings(_env_file=None, ...)` directly; the `settings` fixture in
`tests/conftest.py` gives an offline configuration.

| Group | Fields |
|---|---|
| General | `log_level`, `timezone` (`"America/Chicago"`), `day_rollover_hour` (4), `prompts_dir`, property `tz -> ZoneInfo` |
| API (Typewriter) | `api_token: SecretStr`, `api_host`, `api_port` (8000), `api_max_upload_mb`, `audio_bitrate_kbps` (32), `photo_max_dimension` (2048), `photo_jpeg_quality` (85) |
| Storage | `storage_backend: "local" \| "gdrive"`, `local_root` (`data/Bookshelf`), `gdrive_client_secrets_file`, `gdrive_token_file`, `gdrive_root_folder` (`"Bookshelf"`) |
| Speech | `stt_provider: "litellm" \| "aws_transcribe" \| "fake"`, `stt_model`, `stt_language`, `aws_region`, `aws_transcribe_bucket` |
| LLM | `llm_extract_facts_model`, `llm_write_journal_model`, `llm_fallback_model` (LiteLLM strings), `llm_timeout_seconds`, `llm_max_retries` |
| Embeddings | `embedding_model` (`"fake"` = offline), `embedding_dimension` |
| Index (Bookmarks) | `index_path` (`data/index/bookshelf.sqlite`), `indexer_host`, `indexer_port` (8001), `indexer_poll_interval_seconds` (300), `indexer_nudge_url`, `indexer_backup_interval_hours` (24) |
| MCP (Reading Lamp) | `mcp_transport: "stdio" \| "streamable-http"`, `mcp_host`, `mcp_port` (8002), `mcp_path` (`/mcp`), `mcp_public_url`, `mcp_auth_mode: "none" \| "token" \| "oauth"`, `mcp_auth_token: SecretStr`, `mcp_owner_password: SecretStr` |

## Books, storage: `bookshelf.books.storage`

`get_storage(settings=None) -> Storage`. Paths are relative to the Bookshelf root, POSIX style;
`normalize_path()` validates them (`InvalidPathError`, a `ValueError`). Hidden entries (any
component starting with `.`) are never listed. Missing files raise `FileNotFoundError`; backend
failures raise `StorageError`.

```python
@dataclass(frozen=True)
class FileInfo: path: str; size: int; modified: datetime  # UTC; id: str | None = None
@dataclass(frozen=True)
class Change: path: str; kind: Literal["upserted", "deleted"]; modified: datetime | None = None

class Storage(ABC):
    def read_bytes(self, path: str) -> bytes
    def write_bytes(self, path: str, data: bytes, content_type: str | None = None) -> FileInfo
    def read_text(self, path: str, encoding: str = "utf-8") -> str
    def write_text(self, path: str, text: str, content_type: str | None = None,
                   encoding: str = "utf-8") -> FileInfo
    def exists(self, path: str) -> bool                  # files only
    def stat(self, path: str) -> FileInfo
    def list(self, prefix: str = "") -> list[FileInfo]   # recursive, sorted; prefix is a folder
    def delete(self, path: str, missing_ok: bool = False) -> None   # Drive: moves to trash
    def list_changes(self, since_token: str | None) -> tuple[list[Change], str]
    def get_share_link(self, path: str) -> str           # Drive webViewLink / file:// URI
```

`list_changes(None)` returns every file as `upserted` plus a fresh token; later calls return
changes since the token (latest state per path, renames = deleted + upserted). Tokens are opaque.

Backends: `LocalStorage(root)` (atomic writes; mtime-snapshot tokens) and
`GDriveStorage(root_folder_name, *, credentials=None, service=None)` (`drive.file` scope, Drive
changes API, `GDriveStorage.from_settings(settings)`, `login_main()` = `bookshelf-drive-login`).

## Books, day files: `bookshelf.books.dayfile`

Format details and an example: `docs/books-format.md`.

Paths: `day_dir(d)`, `day_file_path(d)`, `audio_file_name(d, local_time)`,
`audio_file_path(d, local_time)`, `photo_file_name(n)`, `photo_file_path(d, n)`,
`next_photo_names(existing, count)`, `unique_file_name(name, existing)`, `system_path(*parts)`,
`generated_snapshot_path(d)`, `parse_day_file_path(path) -> date | None`,
`date_of_path(path) -> date | None`, `classify_path(path) -> "day"|"audio"|"photo"|"system"|"other"`.
Constants: `SYSTEM_DIR = "_system"`, `FORMAT_VERSION = 1`, `MARKER_PREFIXES = ("bookshelf",
"lifelog")` (`parse` accepts both; `render` writes `bookshelf:`), `LEGACY_FORMAT_KEY`.

Dates: `entry_date(captured_at, tz="America/Chicago", rollover_hour=4) -> date`,
`default_title(d)`.

Models (pydantic):

* `Meal(type: str, items: list[str])`, `Activity(kind: str, minutes: int | None)`
* `DayFacts`: `mood`, `mood_score` (1–5), `city`, `weather`, `people`, `meals`, `activities`,
  `family_events`, `highlights`. Also the output schema of fact extraction. `FACT_FIELDS`.
* `FrontMatter(DayFacts)`: + `date`, `audio`, `photos`, `prompt_version`, `models_used`
  (task → model), `generated_at`, `generated_hash`, `bookshelf_format` (read from
  `lifelog_format` in files written before the rename); unknown keys preserved.
  `.facts() -> DayFacts`.
* `Capture`: `id`, `kind: "recording" | "note"`, `captured_at` (aware), `text`, `audio`,
  `photos`, `location`; `Capture.make_id(kind, captured_at)`.
* `DayFile`: `meta: FrontMatter`, `title`, `journal`, `notes`, `captures`; `.date`,
  `DayFile.new(d)`, `.compute_generated_hash()`, `.is_user_edited()`, `.capture_ids()`.

Functions:

* `parse(markdown, *, fallback_date=None) -> DayFile` (raises `DayFileParseError`)
* `render(day) -> str` (`parse(render(d)) == d`)
* `merge_capture(day | None, capture, day_date) -> DayFile` (idempotent by `capture.id`)
* `apply_generation(day, *, facts, journal, title=None, prompt_version=None, models_used=None,
  generated_at=None, force=False) -> DayFile` (raises `UserEditsDetected`)
* `merge_generation_additive(day, *, facts, journal_addendum=None, addendum_heading=None,
  prompt_version=None, models_used=None, generated_at=None) -> DayFile`

## Index: `bookshelf.index.schema`

Details: `docs/index-schema.md`. Shared rather than inside `bookshelf/bookmarks/`: Bookmarks
writes the index, the Reading Lamp reads it.

* `connect(path, embedding_dimension, *, embedding_model=None, read_only=False) -> sqlite3.Connection`
  (loads sqlite-vec, creates schema, WAL, foreign keys, `sqlite3.Row`)
* `create_schema(conn, dim, *, embedding_model=None)`, `reset_derived(conn, *, embedding_dimension=None, embedding_model=None)`
* `get_meta(conn, key)`, `set_meta(conn, key, value)`, `serialize_embedding(vector) -> bytes`,
  `load_sqlite_vec(conn)`
* `SCHEMA_VERSION`, `META_*` keys, `DERIVED_TABLES`, `PRESERVED_TABLES`,
  `EmbeddingDimensionMismatch`

## Embeddings: `bookshelf.embeddings`

`embed_texts(texts, settings, batch_size=64) -> list[list[float]]` (LiteLLM, or deterministic
`fake_embedding` when `embedding_model == "fake"`). Bookmarks embeds passages and the Reading
Lamp embeds queries with this same function.

## Bookmarks nudge: `bookshelf.nudge`

`nudge_indexer(settings, paths=(), *, timeout=2.0, client=None) -> bool` (never raises).
Wire contract: `POST {BOOKSHELF_INDEXER_NUDGE_URL}` with JSON `{"paths": [...]}`; Bookmarks
answers `202 Accepted` and syncs soon.

## Entry points

| Script | Target | Docker service |
|---|---|---|
| `bookshelf-typewriter` | `bookshelf.typewriter.__main__:main` (uvicorn on `bookshelf.typewriter.app:app`; `create_app(settings)`; `docs/typewriter.md`) | `typewriter` |
| `bookshelf-bookmarks` | `bookshelf.bookmarks.__main__:main` (`run` \| `sync` \| `rebuild` \| `backup`; `docs/bookmarks.md`) | `bookmarks` |
| `bookshelf-reading-lamp` | `bookshelf.reading_lamp.__main__:main` (`--transport stdio`, `reset-oauth`; `docs/reading-lamp.md`) | `reading-lamp` |
| `bookshelf-drive-login` | `bookshelf.books.storage.gdrive:login_main` (one-time Google Drive sign-in) | run by hand |

## Files under `_system/`

Everything here lives in the owner's storage, never in the repository. `classify_path` returns
`"system"` for all of it; Bookmarks reads only `generated/`.

| Path | Writer | Content |
|---|---|---|
| `_system/inbox/<capture id>/` | Typewriter | raw uploads (`audio.<ext>`, `photo-NN.<ext>`, `manifest.json` last) waiting to be processed; deleted when the capture is `done` |
| `_system/captures/<capture id>.json` | Typewriter | capture status (`queued` / `processing` / `done` / `failed`), no journal content; kept for `GET /captures/{id}` |
| `_system/generated/YYYY/MM/YYYY-MM-DD.md` | Typewriter | exact day file as last written by the system (`generated_snapshot_path`); written right after every day-file write, same text and `generated_at` |
| `_system/activity/YYYY/MM.jsonl` | Typewriter | activity records, one JSON line per processing attempt: models, prompt versions, per-step time/cost, errors; no journal content |
| `_system/feedback/YYYY/MM/<UTC timestamp>-<id>.json` | Reading Lamp | copy of each `feedback` call (also a row in the index) |
| `_system/index-backup/bookshelf.sqlite` | Bookmarks | daily index backup (includes `feedback` and `edit_signals`) |
| `_system/reports/` | weekly report job (later) | self-improvement reports |
