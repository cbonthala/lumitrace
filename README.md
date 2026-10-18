# Lumitrace

Talk about your day into your iPhone. Lumitrace turns it into a daily Markdown journal in Google
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
| **Lumitrace** | the whole project: one Python package, one Docker image | `lumitrace/` |
| **Flash** | what you capture with: the web app at `/flash/` (phone or laptop, add it to the Home Screen) and the iPhone Shortcuts (**Log My Day**, **Send pending**, ...) | `lumitrace/prism/web/`; Shortcuts on your phone; guide `docs/flash.md` |
| **Prism** | the recording API and processing pipeline: splits one beam of raw voice into its colors (facts, journal, mood, transcript) | `lumitrace/prism/` (pipeline in `lumitrace/prism/pipeline/`), `prompts/` |
| **Frames** | the day files in Google Drive (one Markdown file per day, one Frame per day), their format and the storage layer | `lumitrace/frames/dayfile.py`, `lumitrace/frames/storage/` |
| **Spectrum** | the indexer: keeps a SQLite search index of the Frames | `lumitrace/spectrum/` (schema shared in `lumitrace/index/`) |
| **Lens** | the MCP server: lets AI apps search and read your Frames | `lumitrace/lens/` |

## How it works

1. **Capture (Flash):** the Flash web app or an iPhone Shortcut sends your voice, location
   and photos to the Prism (`POST /recordings`). A photo with no recording uses `POST /notes`.
2. **Split (Prism):** it transcribes the audio, writes the day's journal from that Telugu
   transcript, and stores a compressed copy of the audio and photos in
   `Lumitrace/YYYY/MM/YYYY-MM-DD/` in Google Drive. Anything before 4 a.m. counts as the previous
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

In `.env`, set `LUMITRACE_API_TOKEN` to an `openssl rand -hex 32` value and
`LUMITRACE_MCP_OWNER_PASSWORD` to a long passphrase: with `change-me` or anything under 16
characters the Prism refuses every request (`503`) and the Lens refuses to start. Choose the speech, AI and embedding providers and
add their keys (`GEMINI_API_KEY`, `LUMITRACE_SARVAM_API_KEY`, ...). To try it without any provider, set
`LUMITRACE_STT_PROVIDER=fake`, the three `LUMITRACE_LLM_*_MODEL=fake` and
`LUMITRACE_EMBEDDING_MODEL=fake`.

### 2. Storage and Google Drive login

* **Local (default):** files go to `LUMITRACE_LOCAL_ROOT` (`data/Lumitrace`). Good for trying it
  out.
* **Google Drive:** create a Google Cloud OAuth client of type *Desktop app* with the Drive API
  enabled and the consent screen set to **In production**, save the JSON as
  `secrets/gdrive_client_secret.json`, set `LUMITRACE_STORAGE_BACKEND=gdrive`, then run
  `uv run lumitrace-drive-login` once. Lumitrace only asks for the `drive.file` scope, so it can
  see only the files it creates (in a `Lumitrace` folder in My Drive). Token renewal:
  `docs/runbook.md`.

### 3. Run the three services

```bash
uv run lumitrace-prism      # Prism (recording API) on :8000 (GET /health)
uv run lumitrace-spectrum   # Spectrum (indexer): poll loop + nudge endpoint on :8001 (keep it internal)
uv run lumitrace-lens       # Lens (MCP server) on :8002/mcp
# or all three (services prism, spectrum, lens), sharing a /data volume
# (only 8000 and 8002 are published):
docker compose up -d --build
```

Try it: `curl -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json'
-d '{"text": "Fish tacos for lunch."}' localhost:8000/notes`, then look in `data/Lumitrace/`.

### 4. Connect Claude, ChatGPT or Cursor (Lens)

* **Claude Desktop / Cursor on the same machine:** run
  `lumitrace-lens --transport stdio` from the app's MCP config.
* **Claude (web and phone) / ChatGPT / Cursor remote:** serve the Lens over HTTPS, then add
  `https://<your host>/mcp` as a connector and sign in with the owner password (OAuth is the
  only login; sessions last `LUMITRACE_MCP_SESSION_DAYS`, default 7).

Exact configs: `docs/lens.md`. Turn off "use my chats for training" in the app you
connect.

### 5. Flash (web app and iPhone Shortcuts)

Quickest: set `LUMITRACE_FLASH_USERNAME` and `LUMITRACE_FLASH_PASSWORD`, open
`https://<prism address>/flash/`, sign in and add it to the Home Screen (`docs/flash.md` →
section 0). For Siri, the Action Button and the share sheet, also build **Flash Config**, **Log My Day**, **Quick Note**, **Send pending**, **Send to Lumitrace**
and the nightly reminder automation, and reach the Prism over HTTPS (Tailscale or a reverse
proxy): `docs/flash.md`.

## Everyday use

* **Log My Day** Shortcut at night (the nightly reminder starts it), **Quick Note** during the day.
* No signal? The Shortcut saves to a "Flash Inbox" folder in Files; "Send pending" uploads later.
  The web app keeps captures in the browser and sends them when you're back online.
* Add extra source material under **My notes**. Generate and the 4:05 a.m. run read it alongside
  every recording but never modify it. **Generate** beside a day in Flash History writes the
  first journal and structured facts now; later clicks process changed source or repair a
  format-4 day whose facts are missing.
* Edit the title, journal or At a glance facts in Obsidian after the first generation. Those
  edits are kept. New
  recordings or changed My notes add bullets directly to Morning, Afternoon, Evening, Thoughts
  or Summary, and merge complete new facts with owner changes winning—there is no Later section
  and no full rewrite. A journal typed before its first generation is still replaced. The file
  has no English translation.
* Ask your AI app about your days; answers cite the dates they come from. If an answer is wrong,
  say so and the app records feedback.

## Privacy

No personal content is ever stored in this repository. Your journal, audio, photos, activity
records and feedback stay in your own storage (`Lumitrace/` and `Lumitrace/_system/`). The index
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
| Why things are the way they are | `docs/decisions/` (names: `0042-rename-to-lumitrace.md`) |
| Maintenance, first run, upgrading from LifeLog, Bookshelf or Lumen | `docs/runbook.md` |
| Trying the APIs by hand (Bruno collection, one folder per module) | `bruno/`, `docs/runbook.md` |
| What each test checks, in plain English | `docs/test-cases.md` |
| What we learned | `docs/learnings.md`, `CHANGELOG.md` |
