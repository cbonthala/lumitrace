# Bookshelf

Talk about your day into your iPhone. Bookshelf turns it into a daily Markdown journal in Google
Drive, which you read in Obsidian and can ask questions about from an AI app like Claude
("What did I eat last Tuesday?").

> You jot it on the **Notepad**, the **Typewriter** turns it into **Books**, **Bookmarks** mark
> every page worth finding, and the **Reading Lamp** lets you read any of it.

> Status: 0.1.0. The Typewriter, Bookmarks and the Reading Lamp are implemented and tested
> offline end to end (`tests/e2e/`). Not yet verified with real providers, real Google Drive, the
> Notepad shortcuts on a device, or the Claude/ChatGPT connectors. See `CHANGELOG.md`.

## The names

| Name | What it is | Where the code lives |
|---|---|---|
| **Bookshelf** | the whole project: one Python package, one Docker image | `bookshelf/` |
| **Notepad** | the iPhone Shortcuts you capture with (**Log My Day**, **Quick Note**, ...) | on your phone; build guide `docs/notepad.md` |
| **Typewriter** | the recording API and processing pipeline: transcribes, extracts facts, writes the journal | `bookshelf/typewriter/` (pipeline in `bookshelf/typewriter/pipeline/`), `prompts/` |
| **Books** | the day files in Google Drive (one Markdown file per day), their format and the storage layer | `bookshelf/books/dayfile.py`, `bookshelf/books/storage/` |
| **Bookmarks** | the indexer: keeps a SQLite search index of the Books | `bookshelf/bookmarks/` (schema shared in `bookshelf/index/`) |
| **Reading Lamp** | the MCP server: lets AI apps search and read your Books | `bookshelf/reading_lamp/` |

## How it works

1. **Jot (Notepad):** an iPhone Shortcut sends your voice note, location and today's photos to the
   Typewriter (`POST /recordings`, or `POST /notes` for quick notes).
2. **Type (Typewriter):** it transcribes the audio, extracts facts (meals, people, activities,
   mood), writes the day's Markdown file and stores a compressed copy of the audio and photos in
   `Bookshelf/YYYY/MM/YYYY-MM-DD/` in Google Drive. Anything before 4 a.m. counts as the previous
   day.
3. **Read the Books:** open the Drive folder in Obsidian. Each day embeds its audio with a play
   button.
4. **Ask (Bookmarks + Reading Lamp):** Bookmarks keeps a small SQLite search index; the Reading
   Lamp lets AI apps search it.

Details: `docs/architecture.md`. Day file format: `docs/books-format.md`.

## Quick start

The first time on a real deployment, follow the **First-run checklist** in `docs/runbook.md`.

### 1. Set up

Requirements: Python 3.12 via [uv](https://docs.astral.sh/uv/), or Docker.

```bash
uv sync                 # or see AGENTS.md for a workspace-local uv install
cp .env.example .env    # then edit (below)
uv run pytest           # everything runs offline
```

In `.env`, set `BOOKSHELF_API_TOKEN` and `BOOKSHELF_MCP_AUTH_TOKEN` to `openssl rand -hex 32`
values: with `change-me` or anything under 16 characters the Typewriter refuses every request
(`503`) and the Reading Lamp refuses to start. Choose the speech, AI and embedding providers and
add their keys (`OPENAI_API_KEY`, AWS credentials, ...). To try it without any provider, set
`BOOKSHELF_STT_PROVIDER=fake`, the three `BOOKSHELF_LLM_*_MODEL=fake` and
`BOOKSHELF_EMBEDDING_MODEL=fake`.

### 2. Storage and Google Drive login

* **Local (default):** files go to `BOOKSHELF_LOCAL_ROOT` (`data/Bookshelf`). Good for trying it
  out.
* **Google Drive:** create a Google Cloud OAuth client of type *Desktop app* with the Drive API
  enabled and the consent screen set to **In production**, save the JSON as
  `secrets/gdrive_client_secret.json`, set `BOOKSHELF_STORAGE_BACKEND=gdrive`, then run
  `uv run bookshelf-drive-login` once. Bookshelf only asks for the `drive.file` scope, so it can
  see only the files it creates (in a `Bookshelf` folder in My Drive). Token renewal:
  `docs/runbook.md`.

### 3. Run the three services

```bash
uv run bookshelf-typewriter     # Typewriter (recording API) on :8000 (GET /health)
uv run bookshelf-bookmarks      # Bookmarks (indexer): poll loop + nudge endpoint on :8001 (keep it internal)
uv run bookshelf-reading-lamp   # Reading Lamp (MCP server) on :8002/mcp
# or all three (services typewriter, bookmarks, reading-lamp), sharing a /data volume
# (only 8000 and 8002 are published):
docker compose up -d --build
```

Try it: `curl -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json'
-d '{"text": "Fish tacos for lunch."}' localhost:8000/notes`, then look in `data/Bookshelf/`.

### 4. Connect Claude, ChatGPT or Cursor (Reading Lamp)

* **Claude Desktop / Cursor on the same machine:** run
  `bookshelf-reading-lamp --transport stdio` from the app's MCP config.
* **Claude (web and phone) / ChatGPT:** serve the Reading Lamp over HTTPS with
  `BOOKSHELF_MCP_AUTH_MODE=oauth`, then add `https://<your host>/mcp` as a custom connector and
  sign in with the owner password.
* **Cursor remote:** the URL plus `Authorization: Bearer <BOOKSHELF_MCP_AUTH_TOKEN>`.

Exact configs: `docs/reading-lamp.md`. Turn off "use my chats for training" in the app you
connect.

### 5. Notepad (iPhone Shortcuts)

Build **Notepad Config**, **Log My Day**, **Quick Note**, **Send pending**, **Send to Bookshelf**
and the nightly reminder automation, and reach the Typewriter over HTTPS (Tailscale or a reverse
proxy): `docs/notepad.md`.

## Everyday use

* **Log My Day** Shortcut at night (the nightly reminder starts it), **Quick Note** during the day.
* No signal? The Shortcut saves to a "Notepad Inbox" folder in Files; "Send pending" uploads later.
* Edit any day in Obsidian. Your edits are kept: Bookshelf never overwrites them, and it never
  touches the **My notes** section. Later captures for an edited day are added, not rewritten.
* Ask your AI app about your days; answers cite the dates they come from. If an answer is wrong,
  say so and the app records feedback.

## Privacy

No personal content is ever stored in this repository. Your journal, audio, photos, activity
records and feedback stay in your own storage (`Bookshelf/` and `Bookshelf/_system/`). The index
lives on the server's disk and is backed up to your Drive. Logs never contain journal text.

## Documentation

| Topic | Where |
|---|---|
| Conventions and context for AI coding agents | `AGENTS.md` |
| How the pieces fit | `docs/architecture.md`, `docs/contracts.md` |
| Typewriter (recording API) and Notepad (iPhone Shortcuts) | `docs/typewriter.md`, `docs/notepad.md` |
| Bookmarks (indexer) | `docs/bookmarks.md`, `docs/index-schema.md` |
| Reading Lamp (MCP server) and AI-app setup | `docs/reading-lamp.md` |
| Books (day file format) | `docs/books-format.md` |
| Why things are the way they are | `docs/decisions/` (names: `0008-project-and-module-names.md`) |
| Maintenance, first run, upgrading from LifeLog | `docs/runbook.md` |
| What each test checks, in plain English | `docs/test-cases.md` |
| What we learned | `docs/learnings.md`, `CHANGELOG.md` |
