# Shared contracts

The interfaces the recording API, indexer and MCP server build on. They are implemented and
tested (`tests/`); this page is the quick reference. Changing any of them is a cross-cutting
change: update every caller, the tests, this page and `CHANGELOG.md` in one commit.

## Config: `lifelog.config`

`Settings` (pydantic-settings, env prefix `LIFELOG_`, reads `.env`), `get_settings()` (cached).
Tests construct `Settings(_env_file=None, ...)` directly; the `settings` fixture in
`tests/conftest.py` gives an offline configuration.

| Group | Fields |
|---|---|
| General | `log_level`, `timezone` (`"America/Chicago"`), `day_rollover_hour` (4), `prompts_dir`, property `tz -> ZoneInfo` |
| API | `api_token: SecretStr`, `api_host`, `api_port` (8000), `api_max_upload_mb`, `audio_bitrate_kbps` (32), `photo_max_dimension` (2048), `photo_jpeg_quality` (85) |
| Storage | `storage_backend: "local" \| "gdrive"`, `local_root` (`data/LifeLog`), `gdrive_client_secrets_file`, `gdrive_token_file`, `gdrive_root_folder` (`"LifeLog"`) |
| Speech | `stt_provider: "litellm" \| "aws_transcribe" \| "fake"`, `stt_model`, `stt_language`, `aws_region`, `aws_transcribe_bucket` |
| LLM | `llm_extract_facts_model`, `llm_write_journal_model`, `llm_fallback_model` (LiteLLM strings), `llm_timeout_seconds`, `llm_max_retries` |
| Embeddings | `embedding_model` (`"fake"` = offline), `embedding_dimension` |
| Index | `index_path`, `indexer_host`, `indexer_port` (8001), `indexer_poll_interval_seconds` (300), `indexer_nudge_url`, `indexer_backup_interval_hours` (24) |
| MCP | `mcp_transport: "stdio" \| "streamable-http"`, `mcp_host`, `mcp_port` (8002), `mcp_path` (`/mcp`), `mcp_public_url`, `mcp_auth_mode: "none" \| "token" \| "oauth"`, `mcp_auth_token: SecretStr`, `mcp_owner_password: SecretStr` |

## Storage: `lifelog.storage`

`get_storage(settings=None) -> Storage`. Paths are relative to the LifeLog root, POSIX style;
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
changes API, `GDriveStorage.from_settings(settings)`, `login_main()` = `lifelog-gdrive-login`).

## Day files: `lifelog.dayfile`

Format details and an example: `docs/day-file-format.md`.

Paths: `day_dir(d)`, `day_file_path(d)`, `audio_file_name(d, local_time)`,
`audio_file_path(d, local_time)`, `photo_file_name(n)`, `photo_file_path(d, n)`,
`next_photo_names(existing, count)`, `unique_file_name(name, existing)`, `system_path(*parts)`,
`generated_snapshot_path(d)`, `parse_day_file_path(path) -> date | None`,
`date_of_path(path) -> date | None`, `classify_path(path) -> "day"|"audio"|"photo"|"system"|"other"`.
Constants: `SYSTEM_DIR = "_system"`, `FORMAT_VERSION = 1`.

Dates: `entry_date(captured_at, tz="America/Chicago", rollover_hour=4) -> date`,
`default_title(d)`.

Models (pydantic):

* `Meal(type: str, items: list[str])`, `Activity(kind: str, minutes: int | None)`
* `DayFacts`: `mood`, `mood_score` (1–5), `city`, `weather`, `people`, `meals`, `activities`,
  `family_events`, `highlights`. Also the output schema of fact extraction. `FACT_FIELDS`.
* `FrontMatter(DayFacts)`: + `date`, `audio`, `photos`, `prompt_version`, `models_used`
  (task → model), `generated_at`, `generated_hash`, `lifelog_format`; unknown keys preserved.
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

## Index: `lifelog.index.schema`

Details: `docs/index-schema.md`.

* `connect(path, embedding_dimension, *, embedding_model=None, read_only=False) -> sqlite3.Connection`
  (loads sqlite-vec, creates schema, WAL, foreign keys, `sqlite3.Row`)
* `create_schema(conn, dim, *, embedding_model=None)`, `reset_derived(conn, *, embedding_dimension=None, embedding_model=None)`
* `get_meta(conn, key)`, `set_meta(conn, key, value)`, `serialize_embedding(vector) -> bytes`,
  `load_sqlite_vec(conn)`
* `SCHEMA_VERSION`, `META_*` keys, `DERIVED_TABLES`, `PRESERVED_TABLES`,
  `EmbeddingDimensionMismatch`

## Embeddings: `lifelog.embeddings`

`embed_texts(texts, settings, batch_size=64) -> list[list[float]]` (LiteLLM, or deterministic
`fake_embedding` when `embedding_model == "fake"`). The indexer embeds passages and the MCP
server embeds queries with this same function.

## Indexer nudge: `lifelog.nudge`

`nudge_indexer(settings, paths=(), *, timeout=2.0, client=None) -> bool` (never raises).
Wire contract: `POST {LIFELOG_INDEXER_NUDGE_URL}` with JSON `{"paths": [...]}`; the indexer
answers `202 Accepted` and syncs soon.

## Entry points

| Script | Target | Status |
|---|---|---|
| `lifelog-api` | `lifelog.api.__main__:main` (uvicorn on `lifelog.api.app:app`; `create_app(settings)`) | `/health` only |
| `lifelog-indexer` | `lifelog.indexer.__main__:main` (`run` \| `sync` \| `rebuild`) | placeholder |
| `lifelog-mcp` | `lifelog.mcp_server.__main__:main` | placeholder `ping` tool |
| `lifelog-gdrive-login` | `lifelog.storage.gdrive:login_main` | done |

## Files under `_system/`

| Path | Writer | Content |
|---|---|---|
| `_system/generated/YYYY/MM/YYYY-MM-DD.md` | recording API | exact day file as last written by the system (`generated_snapshot_path`) |
| `_system/runs/YYYY/MM/<timestamp>-<capture id>.json` | recording API | activity record: models, prompt version, per-step time/cost, errors |
| `_system/feedback/YYYY/MM/<timestamp>-<id>.json` | MCP server | copy of each feedback row |
| `_system/index-backup/lifelog.sqlite` | indexer | daily index backup |
