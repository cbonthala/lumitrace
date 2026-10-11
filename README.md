# LifeLog

Talk about your day into your iPhone. LifeLog turns it into a daily Markdown journal in Google
Drive, which you read in Obsidian and can ask questions about from an AI app like Claude
("What did I eat last Tuesday?").

> Status: foundation only. The recording API, indexer and MCP server are being built; see
> `CHANGELOG.md`.

## How it works

1. **Record:** an iPhone Shortcut sends your voice note, location and today's photos to the
   recording API (`POST /recordings`, or `POST /notes` for quick notes).
2. **Journal:** the API transcribes the audio, extracts facts (meals, people, activities, mood),
   writes the day's Markdown file and stores a compressed copy of the audio and photos in
   `LifeLog/YYYY/MM/YYYY-MM-DD/` in Google Drive. Anything before 4 a.m. counts as the previous day.
3. **Read:** open the Drive folder in Obsidian. Each day embeds its audio with a play button.
4. **Ask:** the indexer keeps a small SQLite search index; the MCP server lets AI apps search it.

Details: `docs/architecture.md`. Day file format: `docs/day-file-format.md`.

## Setup

Requirements: Python 3.12 via [uv](https://docs.astral.sh/uv/), or Docker.

```bash
uv sync                 # or see AGENTS.md for a workspace-local uv install
cp .env.example .env    # set LIFELOG_API_TOKEN, models, provider keys
uv run pytest           # everything runs offline
```

### Storage

* **Local (default):** files go to `LIFELOG_LOCAL_ROOT` (`data/LifeLog`). Good for trying it out.
* **Google Drive:** create a Google Cloud OAuth client of type *Desktop app* with the Drive API
  enabled, save the JSON as `secrets/gdrive_client_secret.json`, set
  `LIFELOG_STORAGE_BACKEND=gdrive`, then run `uv run lifelog-gdrive-login` once. LifeLog only
  asks for the `drive.file` scope, so it can see only the files it creates. Details and token
  renewal: `docs/runbook.md`.

### Run

```bash
uv run lifelog-api        # recording API on :8000 (GET /health)
uv run lifelog-indexer    # indexer (nudge endpoint on :8001)
uv run lifelog-mcp        # MCP server on :8002/mcp
# or
docker compose up --build
```

## Everyday use

* **Log My Day** Shortcut at night (the nightly reminder starts it), **Quick Note** during the day.
* No signal? The Shortcut saves to a "LifeLog Inbox" folder in Files; "Send pending" uploads later.
* Edit any day in Obsidian. Your edits are kept: LifeLog never overwrites them, and it never
  touches the **My notes** section.
* In Claude (or another MCP app), add the LifeLog MCP server and ask away. Turn off "use my chats
  for training" in that app.

## Privacy

No personal content is ever stored in this repository. Your journal, audio, photos, activity
records and feedback stay in your own storage (`LifeLog/` and `LifeLog/_system/`). The index lives
on the server's disk and is backed up to your Drive.

## Documentation

* `AGENTS.md`: conventions and context for AI coding agents.
* `docs/architecture.md`, `docs/contracts.md`, `docs/day-file-format.md`, `docs/index-schema.md`
* `docs/decisions/`: why things are the way they are.
* `docs/runbook.md`: maintenance. `docs/learnings.md`: what we learned. `CHANGELOG.md`.
