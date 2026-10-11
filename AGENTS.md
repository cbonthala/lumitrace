# AGENTS.md

Context for AI coding agents (and humans) working on Bookshelf. Read this first, then
`docs/architecture.md` and `docs/contracts.md`.

## What this is

**Bookshelf** (formerly LifeLog): record your day on an iPhone; an API turns it into one Markdown
journal file per day in Google Drive; read it in Obsidian; ask questions from any AI app through
an MCP server. The story line: *you jot it on the Notepad, the Typewriter turns it into Books,
Bookmarks mark every page worth finding, and the Reading Lamp lets you read any of it.*

### Name map

Use these names in code, docs and commit messages (decision 0008). The plain descriptions
(recording API, indexer, MCP server) are fine next to them.

| Name | What it is | Code |
|---|---|---|
| Bookshelf | the project; one package, one Docker image | `bookshelf/` |
| Notepad | the iPhone Shortcuts (**Log My Day**, **Quick Note**, **Notepad Config**, ...) | none in the repo; `docs/notepad.md` |
| Typewriter | recording API + processing pipeline | `bookshelf/typewriter/`, `bookshelf/typewriter/pipeline/`, `prompts/` |
| Books | the day files in storage: format + storage layer | `bookshelf/books/dayfile.py`, `bookshelf/books/storage/` |
| Bookmarks | the indexer (SQLite index) | `bookshelf/bookmarks/`; schema shared in `bookshelf/index/schema.py` |
| Reading Lamp | the MCP server | `bookshelf/reading_lamp/` |

Three Python programs share the package and the image:

| Program | Entry point | Docker service | Purpose | Status | Reference |
|---|---|---|---|---|---|
| Typewriter (recording API) | `bookshelf-typewriter` | `typewriter` | Receive audio/photos/notes, transcribe, extract facts, write the day file, nudge Bookmarks | implemented (0.1.0) | `docs/typewriter.md`, `docs/notepad.md` |
| Bookmarks (indexer) | `bookshelf-bookmarks` | `bookmarks` | Watch storage for changes, build the SQLite index, record edit signals, rebuild | implemented (0.1.0) | `docs/bookmarks.md` |
| Reading Lamp (MCP server) | `bookshelf-reading-lamp` | `reading-lamp` | Tools for AI apps: `search`, `get_day`, `query_facts`, `on_this_day`, `feedback` | implemented (0.1.0) | `docs/reading-lamp.md` |

`bookshelf-drive-login` (in `bookshelf/books/storage/gdrive.py`) is the one-time Google Drive
sign-in.

Data flow: Notepad → Typewriter → Books (Drive) → Bookmarks → SQLite index ← Reading Lamp ← AI
app. `tests/e2e/test_full_flow.py` exercises the whole chain offline; keep it green when you
change any component. Not yet verified with real providers, real Google Drive, the Notepad
shortcuts on a device or the Claude/ChatGPT OAuth connectors (see "Not verified yet" in the
component docs).

## Key rules

1. **The Markdown day files are the source of truth.** The index is disposable and can always be
   rebuilt (except the `feedback` and `edit_signals` tables, which `reset_derived` keeps).
2. **Never overwrite the owner's edits.** Use `bookshelf.books.dayfile` helpers: `merge_capture`,
   `apply_generation` (refuses on edits) and `merge_generation_additive`. Never write a day file
   by string manipulation.
3. **Keep the raw transcript and the audio.**
4. **Storage, speech-to-text and AI models are swappable through config** (`bookshelf/config.py`).
   Never import a backend directly; use `get_storage(settings)` and LiteLLM model strings.
5. **No personal content in the repository**: no real journal text, transcripts, names, photos,
   audio, tokens, or index files. Tests and docs use fictional data. Activity records, reports and
   feedback live in the owner's storage under `Bookshelf/_system/`.
6. **Update docs, decisions and changelog with every change, in the same commit**: the relevant
   `docs/*.md`, a new `docs/decisions/NNNN-*.md` for any non-obvious choice, `CHANGELOG.md`
   (under *Unreleased*, in your area's subsection), and `docs/learnings.md` when you learned
   something about quality.
7. AI answers must come only from the owner's entries, with dates cited.
8. **Every new or changed test must be described in `docs/test-cases.md`**: one plain-English
   line ("Checks that ...") under a section whose `File:` line names the test file, ending with
   the test name. `tests/test_docs_test_cases.py` fails on missing or stale entries.

## Shared contracts (do not change casually)

These modules are used by more than one program. Changing them requires updating all callers,
their docs, and the tests. Full summary in `docs/contracts.md`.

| Module | Contract |
|---|---|
| `bookshelf/config.py` | `Settings` (env prefix `BOOKSHELF_`), `get_settings()`; document every field in `.env.example` |
| `bookshelf/books/storage/` | `Storage` ABC, `FileInfo`, `Change`, `get_storage()`; `local.py`, `gdrive.py` |
| `bookshelf/books/dayfile.py` | Paths, `entry_date`, `DayFile` model, `parse`/`render`, merge helpers (`docs/books-format.md`) |
| `bookshelf/index/schema.py` | SQLite schema and `connect()` (`docs/index-schema.md`). Kept outside `bookshelf/bookmarks/` because Bookmarks writes the index and the Reading Lamp reads it |
| `bookshelf/embeddings.py` | `embed_texts()`; Bookmarks and the Reading Lamp must embed the same way |
| `bookshelf/nudge.py` | `nudge_indexer()`; Bookmarks serves `POST /nudge` |

Cross-component rules that are not visible in any one module:

* Every time the Typewriter writes a day file it writes the identical text to
  `generated_snapshot_path(date)` right after (same `generated_at`). Bookmarks' edit signals
  depend on this (`docs/bookmarks.md` → Edit signals).
* Bookmarks is the only writer of the derived index tables and `edit_signals`; the Reading Lamp
  only writes `feedback`. The `_system/` folders and their writers are listed in
  `docs/contracts.md`.
* The Bookmarks port (8001) is never published outside the Docker network (`/nudge` has no auth).

## Module ownership (parallel work streams)

| Area | Owns | Docs it maintains |
|---|---|---|
| foundation (incl. Books) | shared contracts above (`bookshelf/config.py`, `bookshelf/books/**`, `bookshelf/index/**`, `embeddings.py`, `nudge.py`, `logging_setup.py`), `pyproject.toml`, `uv.lock`, Docker files, `tests/conftest.py`, `tests/books/**`, `tests/index/**`, `tests/test_*.py` | `AGENTS.md`, `README.md`, `docs/architecture.md`, `docs/contracts.md`, `docs/books-format.md`, `docs/index-schema.md`, ADRs 0001–0009 |
| typewriter | `bookshelf/typewriter/**` (incl. `pipeline/`: STT, LLM, audio, photos), `prompts/**`, `tests/typewriter/**` | `docs/typewriter.md`, `docs/notepad.md`, ADRs 0010–0019 |
| bookmarks | `bookshelf/bookmarks/**`, `tests/bookmarks/**` | `docs/bookmarks.md`, ADRs 0020–0029 |
| reading-lamp | `bookshelf/reading_lamp/**`, `tests/reading_lamp/**` | `docs/reading-lamp.md`, ADRs 0030–0039 |
| integration | `tests/e2e/**` | `docs/architecture.md` (with foundation) |

Shared files everyone edits (keep edits inside your own subsection to avoid merge conflicts):
`CHANGELOG.md`, `docs/learnings.md`, `docs/runbook.md`, `docs/test-cases.md`. If you need a new
dependency or a contract change, say so in your final report instead of editing `pyproject.toml`
or shared modules in parallel.

## Conventions

* Python 3.12, type hints everywhere, `from __future__ import annotations`.
* Pydantic v2 models for data crossing module boundaries.
* Storage paths are relative to the Bookshelf root, POSIX style (`2026/10/2026-10-10/...`).
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
.tools/bin/uv run pytest tests/e2e  # the end-to-end flow only
.tools/bin/uv run ruff check .      # lint
.tools/bin/uv run ruff format .     # format

cp .env.example .env                # then edit (every variable starts with BOOKSHELF_)
.tools/bin/uv run bookshelf-typewriter     # Typewriter: http://localhost:8000/health
.tools/bin/uv run bookshelf-bookmarks      # Bookmarks: run | sync | rebuild | backup
.tools/bin/uv run bookshelf-reading-lamp   # Reading Lamp: :8002/mcp (or --transport stdio)
docker compose up --build           # services typewriter, bookmarks, reading-lamp; shared /data
```

(`uv` may also be on your PATH; then plain `uv run ...` works.) The repository folder may still
be called `lifelog`; that does not matter to the code.
