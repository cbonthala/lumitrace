# AGENTS.md

Context for AI coding agents (and humans) working on LifeLog. Read this first, then
`docs/architecture.md` and `docs/contracts.md`.

## What this is

Record your day on an iPhone; an API turns it into one Markdown journal file per day in Google
Drive; read it in Obsidian; ask questions from any AI app through an MCP server. Three Python
programs share one package (`lifelog/`) and one Docker image:

| Program | Entry point | Package | Purpose |
|---|---|---|---|
| Recording API | `lifelog-api` | `lifelog/api/` | Receive audio/photos/notes, transcribe, extract facts, write the day file, nudge the indexer |
| Indexer | `lifelog-indexer` | `lifelog/indexer/` | Watch storage for changes, build the SQLite index, record edit signals, rebuild |
| MCP server | `lifelog-mcp` | `lifelog/mcp_server/` | Tools for AI apps: `search`, `get_day`, `query_facts`, `on_this_day`, `feedback` |

Data flow: Phone → Recording API → Storage (Drive) → Indexer → SQLite index ← MCP server ← AI app.

## Key rules

1. **The Markdown day files are the source of truth.** The index is disposable and can always be
   rebuilt (except the `feedback` and `edit_signals` tables, which `reset_derived` keeps).
2. **Never overwrite the owner's edits.** Use `lifelog.dayfile` helpers: `merge_capture`,
   `apply_generation` (refuses on edits) and `merge_generation_additive`. Never write a day file
   by string manipulation.
3. **Keep the raw transcript and the audio.**
4. **Storage, speech-to-text and AI models are swappable through config** (`lifelog/config.py`).
   Never import a backend directly; use `get_storage(settings)` and LiteLLM model strings.
5. **No personal content in the repository**: no real journal text, transcripts, names, photos,
   audio, tokens, or index files. Tests and docs use fictional data. Activity records, reports and
   feedback live in the owner's storage under `LifeLog/_system/`.
6. **Update docs, decisions and changelog with every change, in the same commit**: the relevant
   `docs/*.md`, a new `docs/decisions/NNNN-*.md` for any non-obvious choice, `CHANGELOG.md`
   (under *Unreleased*, in your area's subsection), and `docs/learnings.md` when you learned
   something about quality.
7. AI answers must come only from the owner's entries, with dates cited.

## Shared contracts (do not change casually)

These modules are used by more than one program. Changing them requires updating all callers,
their docs, and the tests. Full summary in `docs/contracts.md`.

| Module | Contract |
|---|---|
| `lifelog/config.py` | `Settings` (env prefix `LIFELOG_`), `get_settings()`; document every field in `.env.example` |
| `lifelog/storage/` | `Storage` ABC, `FileInfo`, `Change`, `get_storage()`; `local.py`, `gdrive.py` |
| `lifelog/dayfile.py` | Paths, `entry_date`, `DayFile` model, `parse`/`render`, merge helpers (`docs/day-file-format.md`) |
| `lifelog/index/schema.py` | SQLite schema and `connect()` (`docs/index-schema.md`) |
| `lifelog/embeddings.py` | `embed_texts()`; indexer and MCP must embed the same way |
| `lifelog/nudge.py` | `nudge_indexer()`; the indexer serves `POST /nudge` |

## Module ownership (parallel work streams)

| Area | Owns | Docs it maintains |
|---|---|---|
| foundation | shared contracts above, `pyproject.toml`, `uv.lock`, Docker files, `tests/conftest.py` | `AGENTS.md`, `README.md`, `docs/architecture.md`, `docs/contracts.md`, `docs/day-file-format.md`, `docs/index-schema.md` |
| recording-api | `lifelog/api/**`, `lifelog/pipeline/**` (new: STT, LLM, audio, photos), `prompts/**`, `tests/api/**` | `docs/recording-api.md`, ADRs 0010–0019 |
| indexer | `lifelog/indexer/**`, `tests/indexer/**` | `docs/indexer.md`, ADRs 0020–0029 |
| mcp | `lifelog/mcp_server/**`, `tests/mcp_server/**` | `docs/mcp-server.md`, ADRs 0030–0039 |

Shared files everyone edits (keep edits inside your own subsection to avoid merge conflicts):
`CHANGELOG.md`, `docs/learnings.md`, `docs/runbook.md`. If you need a new dependency or a
contract change, say so in your final report instead of editing `pyproject.toml` or shared modules
in parallel.

## Conventions

* Python 3.12, type hints everywhere, `from __future__ import annotations`.
* Pydantic v2 models for data crossing module boundaries.
* Storage paths are relative to the LifeLog root, POSIX style (`2026/10/2026-10-10/...`).
* Dates are `YYYY-MM-DD` strings in SQLite, `datetime.date` in Python. Timestamps are
  timezone-aware; store UTC ISO-8601 in SQLite.
* Logging via `logging.getLogger(__name__)`; never log transcript or journal text at INFO or above.
* Ruff (line length 100) for lint and formatting.
* Tests must run offline: use `LocalStorage` on `tmp_path`, `embedding_model="fake"`,
  `stt_provider="fake"`, and fakes/mocks for LiteLLM and HTTP. Mark anything that needs real
  credentials with `@pytest.mark.network` (skipped by default).
* MCP SDK is **mcp 2.x**: `from mcp.server.mcpserver import MCPServer` (FastMCP was renamed).
* Async tests: use `anyio` (`anyio.run(...)` or `@pytest.mark.anyio`); pytest-asyncio is not
  installed.
* Test packages: every `tests/<area>/` folder has an `__init__.py`.

## How to run and test

```bash
# one-time: tools live inside the workspace
python3 -m venv .tools && .tools/bin/pip install uv
export UV_PYTHON_INSTALL_DIR=$PWD/.tools/python UV_CACHE_DIR=$PWD/.tools/cache
.tools/bin/uv sync

.tools/bin/uv run pytest            # all tests (offline)
.tools/bin/uv run ruff check .      # lint
.tools/bin/uv run ruff format .     # format

cp .env.example .env                # then edit
.tools/bin/uv run lifelog-api       # http://localhost:8000/health
.tools/bin/uv run lifelog-indexer
.tools/bin/uv run lifelog-mcp
docker compose up --build           # all three with a shared /data volume
```

(`uv` may also be on your PATH; then plain `uv run ...` works.)
