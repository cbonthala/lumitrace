# Lumen

Talk about your day into your iPhone. Lumen turns it into a daily Markdown journal in Google
Drive, which you read in Obsidian and can ask questions about from an AI app like Claude
("What did I eat last Tuesday?").

> A **Flash** captures the moment, the **Prism** splits it into its colors, each day becomes a
> **Frame**, the **Spectrum** lays everything out in order, and the **Lens** lets you zoom into
> any day.

> Status: 0.1.0. The Prism, the Spectrum and the Lens are implemented and tested
> offline end to end (`tests/e2e/`). Not yet verified with real providers, real Google Drive, the
> Flash shortcuts on a device, or the Claude/ChatGPT connectors. See `CHANGELOG.md`.

## The names

| Name | What it is | Where the code lives |
|---|---|---|
| **Lumen** | the whole project: one Python package, one Docker image | `lumen/` |
| **Flash** | the iPhone Shortcuts you capture with (**Log My Day**, **Quick Note**, ...) | on your phone; build guide `docs/flash.md` |
| **Prism** | the recording API and processing pipeline: splits one beam of raw voice into its colors (facts, journal, mood, transcript) | `lumen/prism/` (pipeline in `lumen/prism/pipeline/`), `prompts/` |
| **Frames** | the day files in Google Drive (one Markdown file per day, one Frame per day), their format and the storage layer | `lumen/frames/dayfile.py`, `lumen/frames/storage/` |
| **Spectrum** | the indexer: keeps a SQLite search index of the Frames | `lumen/spectrum/` (schema shared in `lumen/index/`) |
| **Lens** | the MCP server: lets AI apps search and read your Frames | `lumen/lens/` |

## How it works

1. **Capture (Flash):** an iPhone Shortcut sends your voice note, location and today's photos to
   the Prism (`POST /recordings`, or `POST /notes` for quick notes).
2. **Split (Prism):** it transcribes the audio, extracts facts (meals, people, activities,
   mood), writes the day's Markdown file and stores a compressed copy of the audio and photos in
   `Lumen/YYYY/MM/YYYY-MM-DD/` in Google Drive. Anything before 4 a.m. counts as the previous
   day.
3. **Look at the Frames:** open the Drive folder in Obsidian. Each day embeds its audio with a
   play button.
4. **Zoom in (Spectrum + Lens):** the Spectrum keeps a small SQLite search index; the Lens lets AI
   apps search it.

Details: `docs/architecture.md`. Day file format: `docs/frames-format.md`.

## Quick start

The first time on a real deployment, follow the **First-run checklist** in `docs/runbook.md`.

### 1. Set up

Requirements: Python 3.12 via [uv](https://docs.astral.sh/uv/), or Docker.

```bash
uv sync                 # or see AGENTS.md for a workspace-local uv install
cp .env.example .env    # then edit (below)
uv run pytest           # everything runs offline
```

In `.env`, set `LUMEN_API_TOKEN` and `LUMEN_MCP_AUTH_TOKEN` to `openssl rand -hex 32`
values: with `change-me` or anything under 16 characters the Prism refuses every request
(`503`) and the Lens refuses to start. Choose the speech, AI and embedding providers and
add their keys (`OPENAI_API_KEY`, AWS credentials, ...). To try it without any provider, set
`LUMEN_STT_PROVIDER=fake`, the three `LUMEN_LLM_*_MODEL=fake` and
`LUMEN_EMBEDDING_MODEL=fake`.

### 2. Storage and Google Drive login

* **Local (default):** files go to `LUMEN_LOCAL_ROOT` (`data/Lumen`). Good for trying it
  out.
* **Google Drive:** create a Google Cloud OAuth client of type *Desktop app* with the Drive API
  enabled and the consent screen set to **In production**, save the JSON as
  `secrets/gdrive_client_secret.json`, set `LUMEN_STORAGE_BACKEND=gdrive`, then run
  `uv run lumen-drive-login` once. Lumen only asks for the `drive.file` scope, so it can
  see only the files it creates (in a `Lumen` folder in My Drive). Token renewal:
  `docs/runbook.md`.

### 3. Run the three services

```bash
uv run lumen-prism      # Prism (recording API) on :8000 (GET /health)
uv run lumen-spectrum   # Spectrum (indexer): poll loop + nudge endpoint on :8001 (keep it internal)
uv run lumen-lens       # Lens (MCP server) on :8002/mcp
# or all three (services prism, spectrum, lens), sharing a /data volume
# (only 8000 and 8002 are published):
docker compose up -d --build
```

Try it: `curl -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json'
-d '{"text": "Fish tacos for lunch."}' localhost:8000/notes`, then look in `data/Lumen/`.

### 4. Connect Claude, ChatGPT or Cursor (Lens)

* **Claude Desktop / Cursor on the same machine:** run
  `lumen-lens --transport stdio` from the app's MCP config.
* **Claude (web and phone) / ChatGPT:** serve the Lens over HTTPS with
  `LUMEN_MCP_AUTH_MODE=oauth`, then add `https://<your host>/mcp` as a custom connector and
  sign in with the owner password.
* **Cursor remote:** the URL plus `Authorization: Bearer <LUMEN_MCP_AUTH_TOKEN>`.

Exact configs: `docs/lens.md`. Turn off "use my chats for training" in the app you
connect.

### 5. Flash (iPhone Shortcuts)

Build **Flash Config**, **Log My Day**, **Quick Note**, **Send pending**, **Send to Lumen**
and the nightly reminder automation, and reach the Prism over HTTPS (Tailscale or a reverse
proxy): `docs/flash.md`.

## Everyday use

* **Log My Day** Shortcut at night (the nightly reminder starts it), **Quick Note** during the day.
* No signal? The Shortcut saves to a "Flash Inbox" folder in Files; "Send pending" uploads later.
* Edit any day in Obsidian. Your edits are kept: Lumen never overwrites them, and it never
  touches the **My notes** section. Later captures for an edited day are added, not rewritten.
* Ask your AI app about your days; answers cite the dates they come from. If an answer is wrong,
  say so and the app records feedback.

## Privacy

No personal content is ever stored in this repository. Your journal, audio, photos, activity
records and feedback stay in your own storage (`Lumen/` and `Lumen/_system/`). The index
lives on the server's disk and is backed up to your Drive. Logs never contain journal text.

## Documentation

| Topic | Where |
|---|---|
| Conventions and context for AI coding agents | `AGENTS.md` |
| How the pieces fit | `docs/architecture.md`, `docs/contracts.md` |
| Tech stack, services and licenses | `docs/tech-stack.md` |
| Prism (recording API) and Flash (iPhone Shortcuts) | `docs/prism.md`, `docs/flash.md` |
| Spectrum (indexer) | `docs/spectrum.md`, `docs/index-schema.md` |
| Lens (MCP server) and AI-app setup | `docs/lens.md` |
| Frames (day file format) | `docs/frames-format.md` |
| Why things are the way they are | `docs/decisions/` (names: `0009-rename-to-lumen.md`) |
| Maintenance, first run, upgrading from LifeLog or Bookshelf | `docs/runbook.md` |
| What each test checks, in plain English | `docs/test-cases.md` |
| What we learned | `docs/learnings.md`, `CHANGELOG.md` |
