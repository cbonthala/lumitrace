# Shared contracts

The interfaces the Prism (recording API), Spectrum (indexer) and the Lens (MCP
server) build on. They are implemented and
tested (`tests/`); this page is the quick reference. Changing any of them is a cross-cutting
change: update every caller, the tests, this page and `CHANGELOG.md` in one commit.

## Config: `lumitrace.config`

`Settings` (pydantic-settings, env prefix `LUMITRACE_`, reads `.env`), `get_settings()` (cached).
Field names keep their technical prefixes (`api_*` = Prism, `indexer_*` = Spectrum,
`mcp_*` = Lens), so `LUMITRACE_API_TOKEN` is the Prism's token.
Tests construct `Settings(_env_file=None, ...)` directly; the `settings` fixture in
`tests/conftest.py` gives an offline configuration.

| Group | Fields |
|---|---|
| General | `log_level`, `timezone` (`"America/Chicago"`), `day_rollover_hour` (4), `prompts_dir`, property `tz -> ZoneInfo`. Family is not a setting: `get_settings()` reads `secrets/family.md` (or `/secrets/family.md` in Docker) into properties `family_members -> list[str]`, `family_relations -> dict[str, str]`, `owner_name -> str \| None` (relation `me` or `self`), and `glossary_text -> str` (the Markdown notes, or `(none)`). `Settings()` in tests does not read that file; pass `household=` |
| API (Prism) | `api_token: SecretStr`, `api_host`, `api_port` (8000), `api_max_upload_mb`, `audio_bitrate_kbps` (32), `photo_max_dimension` (2048), `photo_jpeg_quality` (85) |
| Storage | `storage_backend: "local" \| "gdrive"`, `local_root` (`data/Lumitrace`), `gdrive_client_secrets_file`, `gdrive_token_file`, `gdrive_root_folder` (`"Lumitrace"`) |
| Speech | `stt_provider: "litellm" \| "aws_transcribe" \| "sarvam" \| "fake"`, `stt_model`, `stt_language`, `stt_keyterms` (comma- or semicolon-separated; property `stt_keyterm_list` = family-file names + these, split on those separators so Sarvam receives one term per array item), `aws_region`, `aws_transcribe_bucket`, `sarvam_api_key: SecretStr`, `sarvam_model` (`saaras:v4`), `sarvam_mode: "transcribe" \| "codemix" \| "verbatim" \| "translit"` (`codemix`). One Sarvam job, the transcript (ADR 0048) |
| LLM | `llm_write_journal_model`, `llm_fallback_model` (LiteLLM strings), `llm_timeout_seconds`, `llm_max_retries`. The journal model fills the day at 4:05 a.m. and updates it when a later recording arrives (ADR 0050) |
| Embeddings | `embedding_model` (`"fake"` = offline; default `gemini/gemini-embedding-2`), `embedding_dimension` (1536). The call asks the provider for that many values (ADR 0053) |
| Index (Spectrum) | `index_path` (`data/index/lumitrace.sqlite`), `indexer_host`, `indexer_port` (8001), `indexer_poll_interval_seconds` (300), `indexer_nudge_url`, `indexer_backup_interval_hours` (24) |
| MCP (Lens) | `mcp_transport: "stdio" \| "streamable-http"`, `mcp_host`, `mcp_port` (8002), `mcp_path` (`/mcp`), `mcp_public_url`, `mcp_auth_mode: "oauth" \| "none"` (`oauth`), `mcp_owner_password: SecretStr`, `mcp_session_days` (7), `mcp_admin_host` (`127.0.0.1`), `mcp_admin_port` (8003, 0 = off), `mcp_admin_url` (`http://127.0.0.1:8003`, read by the Prism) |

## Frames, storage: `lumitrace.frames.storage`

`get_storage(settings=None) -> Storage`. Paths are relative to the Lumitrace root, POSIX style;
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
changes API, `GDriveStorage.from_settings(settings)`, `login_main()` = `lumitrace-drive-login`).

## Frames, Format 6 content: `lumitrace.frames.daycontent`

`FORMAT_VERSION = 6`. This module has no dependency on `dayfile`; it owns the typed generated
content, canonical Markdown inside the content markers and field-level merge behavior.

Models (Pydantic, unknown JSON fields ignored):

* Timeline: `PlaceContext`, `PersonContext`, `DayContext`, `Timeline` (highlight, context,
  Morning/Afternoon/Evening/Night/Time not stated lists, Remember).
* Trackers: `Meal(status: "consumed" | "skipped" | "not_recorded", items)`, `FoodTracker`,
  `ExerciseMovement`, `Rating`, `HealthFitness`, `DailyRoutine`, `InterestsPreferences`,
  `GrowthLearning`, `FamilyTracker`, `PregnancyBaby`.
* Root: `DayContent(timeline, family, pregnancy_baby, tags)`. It accepts either its direct shape
  or the fill-day prompt's `trackers` envelope. Text is collapsed to one line, empty list items
  are removed and leading `#` is removed from tags.
* Timeline patches: `TimelineAddition`, `TimelineDeletion`, `TimelineReplacement`; valid
  sections are Morning, Afternoon, Evening, Night and Time not stated.

Functions:

* `render(content) -> str`, `parse(markdown) -> DayContent`: canonical Format 6 Markdown.
  Empty cells use `—`; multiple cell values use `<br>`.
* `merge_three_way(base, current, incoming) -> DayContent`: owner-safe scalar, list, nested-row
  and table-cell merge. Text identity ignores a parenthetical gloss and `[uncertain: ...]`.
* `add_timeline_bullet`, `delete_timeline_bullet`, `replace_timeline_bullet`,
  `move_timeline_bullet`, `apply_timeline_patches`: exact timeline operations; the batch order
  is replacements, deletions, additions.
* `from_fill_day`, `from_legacy_facts`, `from_legacy_day`, `to_legacy_facts`: prompt validation
  and conservative Format 5 compatibility projections.

## Frames, day files: `lumitrace.frames.dayfile`

Format details and an example: `docs/frames-format.md`.

Paths: `day_dir(d)`, `day_file_path(d)`, `audio_file_name(d, local_time)`,
`audio_file_path(d, local_time)`, `photo_file_name(n)`, `photo_file_path(d, n)`,
`next_photo_names(existing, count)`, `unique_file_name(name, existing)`, `system_path(*parts)`,
`generated_snapshot_path(d)`, `generated_facts_path(d)`, `parse_day_file_path(path) -> date | None`,
`date_of_path(path) -> date | None`, `classify_path(path) -> "day"|"audio"|"photo"|"system"|"other"`.
Constants: `SYSTEM_DIR = "_system"`, `FORMAT_VERSION = 6`, `LEGACY_FORMAT_VERSION = 5`,
`CONTENT_START`, `CONTENT_END`, legacy `FACTS_HEADING = "## At a glance"`,
`FACT_SECTIONS`, `MEAL_TYPES` (breakfast, lunch, dinner, snacks),
`NONE_TEXT = "not mentioned"`, `JOURNAL_SECTIONS` (Summary, Morning, Afternoon, Evening, Thoughts),
`MARKER_PREFIXES = ("lumitrace", "lumen",
"bookshelf", "lifelog")` (`parse` accepts all; `render` writes `lumitrace:`), `FORMAT_KEY =
"lumitrace_format"`, `LEGACY_FORMAT_KEYS = ("lumen_format", "bookshelf_format",
"lifelog_format")`.

Dates: `entry_date(captured_at, tz="America/Chicago", rollover_hour=4) -> date`.

Models (pydantic):

* `Meal(type: str, items: list[str])` (`type` is one of `MEAL_TYPES`),
  `Activity(kind: str, minutes: int | None)`
* `FamilyMember`: `name`, `meals: list[Meal]` (breakfast, lunch, dinner, snacks), `health`,
  `feelings`, `moments` (memories); `.has_facts()`.
* `DayFacts`: `mood`, `mood_score` (1–5), `city`, `weather`, `highlights`, `remember`,
  `places`, `people`, `memories` (shared), `activities` (things we did), `meals` (the Everyone
  block: union of family meals, each item tagged with who had it), `family: list[FamilyMember]`;
  `.is_empty()`. Format 1/2 shaped data is converted by a
  validator (`docs/frames-format.md` → Older formats). Also the output
  schema of fact extraction. Values are normalised (one line; a comma splits meal items except
  inside parentheses) so
  render and parse agree. `FACT_FIELDS`.
* `GeneratedFactsState`: `date`, `source_hash`, legacy `facts`, optional legacy `journal`,
  optional `content: DayContent`, optional `title`; the model-owned base for three-way merging.
  A state written by Format 6 stores complete content, the last model title (ADR 0066) and its
  Format 5 facts projection.
* `FrontMatter`: `date`, `audio`, `photos`, `prompt_version`, `models_used` (task → model),
  `generated_at`, `generated_hash`, `generated_source_hash`, `lumitrace_format` (read from `lumen_format`,
  `bookshelf_format` or `lifelog_format` in files written under the earlier names); unknown keys preserved. Facts are
  not in the front matter since format 2. `render` writes Format 6 only when `DayFile.content`
  exists; a legacy day stays Format 5. No format writes a translation. `parse` reads all older
  formats.
* `Capture`: `id`, `kind: "recording" | "note"`, `captured_at` (aware), `text`, `translation`
  (read from an older file; `render` always writes `""`),
  `audio`, `photos`, `location`; `Capture.make_id(kind, captured_at)`.
* `DayFile`: `meta: FrontMatter`, `facts: DayFacts`, `title`, `journal`,
  `content: DayContent | None`, `notes`, `captures`; `.date`,
  `DayFile.new(d)`, `.compute_generated_hash()`, `.compute_source_hash()`,
  `.is_user_edited()`, `.capture_ids()`. In Format 6, `facts` is a compatibility projection and
  `journal` is empty; the generated hash covers complete content and title.

Functions:

* `parse(markdown, *, fallback_date=None) -> DayFile` (raises `DayFileParseError`)
* `render(day) -> str` (Format 6 content when present; otherwise Format 5 compatibility; no
  translation)
* `render_facts_section(facts, *, include_empty=True) -> str` (every line, `none` when empty;
  `include_empty=False` is the index's view without them),
  `parse_facts_section(markdown) -> (DayFacts, stray)` (the "At a glance" region; Spectrum makes
  its facts passages from the `include_empty=False` text)
* `merge_capture(day | None, capture, day_date) -> DayFile` (idempotent by `capture.id`)
* `remove_capture(day, capture_id) -> DayFile` (no-op if missing; never touches journal or notes)
* `content_for_day(day) -> DayContent` (copy Format 6 content or conservatively project a legacy
  day)
* `default_title(d)`, `composed_title(d, headline="")`, `resolve_generated_title(current, *,
  incoming, base)` (ADR 0066: apply a new heading only when `current` still equals `base`)
* `apply_content_generation(day, *, content, title=None, prompt_version=None, models_used=None,
  generated_at=None, generated_source_hash=None, force=False) -> DayFile`
* `merge_content_generation_three_way(day, *, base_content, content, title=None, base_title=None,
  prompt_version=None, models_used=None, generated_at=None,
  generated_source_hash=None) -> DayFile`
* The following facts/journal APIs remain for Format 5 compatibility:
* `apply_generation(day, *, facts, journal, title=None, prompt_version=None, models_used=None,
  generated_at=None, generated_source_hash=None, force=False) -> DayFile`
  (raises `UserEditsDetected`)
* `normalize_journal(markdown) -> str` (fixed `JOURNAL_SECTIONS` headings; used by
  `apply_generation`)
* `merge_journal_sections(markdown, additions) -> str` (mechanically inserts bullets into
  Summary, Morning, Afternoon, Evening or Thoughts without changing existing words)
* `merge_generation_additive(day, *, facts, journal_sections=None, prompt_version=None,
  models_used=None, generated_at=None, generated_source_hash=None) -> DayFile`
* `fact_key(text) -> str` (one fact, ignoring a parenthetical gloss and `[uncertain: ...]`)
* `journals_match(left, right) -> bool`
* `apply_journal_replacements(journal, replacements, *, model_journal) -> str`
* `next_model_journal(previous, *, replaced_with=None, replacements=None, sections=None) -> str | None`
* `merge_facts_three_way(base, current, incoming) -> DayFacts`
* `merge_generation_three_way(day, *, base_facts, facts, journal_sections=None,
  journal_replacements=None, replacement_journal=None, model_journal=None,
  prompt_version=None, models_used=None, generated_at=None,
  generated_source_hash=None) -> DayFile`

## Index: `lumitrace.index.schema`

Details: `docs/index-schema.md`. Shared rather than inside `lumitrace/spectrum/`: Spectrum
writes the index, the Lens reads it.

* `connect(path, embedding_dimension, *, embedding_model=None, read_only=False) -> sqlite3.Connection`
  (loads sqlite-vec, creates schema, WAL, foreign keys, `sqlite3.Row`)
* `create_schema(conn, dim, *, embedding_model=None)`, `reset_derived(conn, *, embedding_dimension=None, embedding_model=None)`
* `get_meta(conn, key)`, `set_meta(conn, key, value)`, `serialize_embedding(vector) -> bytes`,
  `load_sqlite_vec(conn)`
* `SCHEMA_VERSION = 4`, `META_*` keys, `DERIVED_TABLES`, `PRESERVED_TABLES`,
  `EmbeddingDimensionMismatch`
* `content_facts`: flattened canonical `DayContent` rows with `scope`
  (`timeline|family|pregnancy|tags`), optional `person`, `category`, `field`, text/number/status,
  optional `details_json` and stable position. Spectrum projects legacy days through
  `content_for_day`, so the table covers every readable format. The legacy fact tables remain.

## Embeddings: `lumitrace.embeddings`

`embed_texts(texts, settings, batch_size=64) -> list[list[float]]` (LiteLLM, or deterministic
`fake_embedding` when `embedding_model == "fake"`). The provider is asked for
`embedding_dimension` values. Spectrum embeds passages and the Lens embeds queries with this same function.

## Spectrum nudge: `lumitrace.nudge`

`nudge_indexer(settings, paths=(), *, timeout=2.0, client=None) -> bool` (never raises).
Wire contract: `POST {LUMITRACE_INDEXER_NUDGE_URL}` with JSON `{"paths": [...]}`; Spectrum
answers `202 Accepted` and syncs soon.

## Lens admin API (connected AI apps)

The Prism's `/lens/apps` routes (`lumitrace/prism/lens_apps.py`) call the Lens's private
admin API (`lumitrace/lens/admin.py`) at `LUMITRACE_MCP_ADMIN_URL` with
`Authorization: Bearer <LUMITRACE_API_TOKEN>`, so both services need the same API token. Routes
and response shapes: `docs/lens.md` → Connected apps; decision 0036. The admin port (8003) is
never published or funnelled.

## Entry points

| Script | Target | Docker service |
|---|---|---|
| `lumitrace-prism` | `lumitrace.prism.__main__:main` (uvicorn on `lumitrace.prism.app:app`; `create_app(settings)`; `docs/prism.md`) | `prism` |
| `lumitrace-spectrum` | `lumitrace.spectrum.__main__:main` (`run` \| `sync` \| `rebuild` \| `backup`; `docs/spectrum.md`) | `spectrum` |
| `lumitrace-lens` | `lumitrace.lens.__main__:main` (`--transport stdio`, `reset-oauth`; `docs/lens.md`) | `lens` |
| `lumitrace-drive-login` | `lumitrace.frames.storage.gdrive:login_main` (one-time Google Drive sign-in) | run by hand |

## Files under `_system/`

Everything here lives in the owner's storage, never in the repository. `classify_path` returns
`"system"` for all of it; Spectrum reads only `generated/`.

| Path | Writer | Content |
|---|---|---|
| `_system/inbox/<capture id>/` | Prism | raw uploads (`audio.<ext>`, `photo-NN.<ext>`, `manifest.json` last) waiting to be processed; deleted when the capture is `done` |
| `_system/captures/<capture id>.json` | Prism | capture status (`queued` / `processing` / `done` / `failed`), no journal content; kept for `GET /captures/{id}` |
| `_system/generated/YYYY/MM/YYYY-MM-DD.md` | Prism | exact day file as last written by the system (`generated_snapshot_path`); written right after every day-file write, same text and `generated_at` |
| `_system/generated-facts/YYYY/MM/YYYY-MM-DD.json` | Prism | previous complete Format 6 model content, source hash and a Format 5 facts projection; base for owner-safe content merges (older files may instead have facts and a model journal) |
| `_system/journal-due/YYYY-MM-DD.txt` | Prism | a day whose transcripts are saved and whose journal has not been written yet; removed when the morning run, Generate in Flash, or a late capture for a closed day finishes (ADR 0046, 0055) |
| `_system/activity/YYYY/MM.jsonl` | Prism | activity records, one JSON line per processing attempt: models, per-step time/cost, errors; no journal content |
| `_system/feedback/YYYY/MM/<UTC timestamp>-<id>.json` | Lens | copy of each `feedback` call (also a row in the index) |
| `_system/index-backup/lumitrace.sqlite` | Spectrum | daily index backup (includes `feedback` and `edit_signals`) |
| `_system/reports/` | weekly report job (later) | self-improvement reports |
