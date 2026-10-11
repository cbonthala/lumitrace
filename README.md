# LifeLog

Talk about your day into your iPhone. LifeLog turns it into a daily Markdown journal in Google
Drive, which you read in Obsidian and can ask questions about from an AI app like Claude
("What did I eat last Tuesday?").

> Status: 0.1.0. The recording API, indexer and MCP server are implemented and tested offline
> end to end (`tests/e2e/`). Not yet verified with real providers, real Google Drive, the iPhone
> Shortcuts on a device, or the Claude/ChatGPT connectors. See `CHANGELOG.md`.

## How it works

1. **Record:** an iPhone Shortcut sends your voice note, location and today's photos to the
   recording API (`POST /recordings`, or `POST /notes` for quick notes).
2. **Journal:** the API transcribes the audio, extracts facts (meals, people, activities, mood),
   writes the day's Markdown file and stores a compressed copy of the audio and photos in
   `LifeLog/YYYY/MM/YYYY-MM-DD/` in Google Drive. Anything before 4 a.m. counts as the previous day.
3. **Read:** open the Drive folder in Obsidian. Each day embeds its audio with a play button.
4. **Ask:** the indexer keeps a small SQLite search index; the MCP server lets AI apps search it.

Details: `docs/architecture.md`. Day file format: `docs/day-file-format.md`.

## Quick start

The first time on a real deployment, follow the **First-run checklist** in `docs/runbook.md`.

### 1. Set up

Requirements: Python 3.12 via [uv](https://docs.astral.sh/uv/), or Docker.

```bash
uv sync                 # or see AGENTS.md for a workspace-local uv install
cp .env.example .env    # then edit (below)
uv run pytest           # everything runs offline
```

In `.env`, set `LIFELOG_API_TOKEN` and `LIFELOG_MCP_AUTH_TOKEN` to `openssl rand -hex 32` values:
with `change-me` or anything under 16 characters the API refuses every request (`503`) and the
MCP server refuses to start. Choose the speech, AI and embedding providers and add their keys
(`OPENAI_API_KEY`, AWS credentials, ...). To try it without any provider, set
`LIFELOG_STT_PROVIDER=fake`, the three `LIFELOG_LLM_*_MODEL=fake` and `LIFELOG_EMBEDDING_MODEL=fake`.

### 2. Storage and Google Drive login

* **Local (default):** files go to `LIFELOG_LOCAL_ROOT` (`data/LifeLog`). Good for trying it out.
* **Google Drive:** create a Google Cloud OAuth client of type *Desktop app* with the Drive API
  enabled and the consent screen set to **In production**, save the JSON as
  `secrets/gdrive_client_secret.json`, set `LIFELOG_STORAGE_BACKEND=gdrive`, then run
  `uv run lifelog-gdrive-login` once. LifeLog only asks for the `drive.file` scope, so it can see
  only the files it creates. Token renewal: `docs/runbook.md`.

### 3. Run the three services

```bash
uv run lifelog-api        # recording API on :8000 (GET /health)
uv run lifelog-indexer    # indexer: poll loop + nudge endpoint on :8001 (keep it internal)
uv run lifelog-mcp        # MCP server on :8002/mcp
# or all three, sharing a /data volume (only 8000 and 8002 are published):
docker compose up -d --build
```

Try it: `curl -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json'
-d '{"text": "Fish tacos for lunch."}' localhost:8000/notes`, then look in `data/LifeLog/`.

### 4. Connect Claude, ChatGPT or Cursor (MCP)

* **Claude Desktop / Cursor on the same machine:** run `lifelog-mcp --transport stdio` from the
  app's MCP config.
* **Claude (web and phone) / ChatGPT:** serve the MCP server over HTTPS with
  `LIFELOG_MCP_AUTH_MODE=oauth`, then add `https://<your host>/mcp` as a custom connector and
  sign in with the owner password.
* **Cursor remote:** the URL plus `Authorization: Bearer <LIFELOG_MCP_AUTH_TOKEN>`.

Exact configs: `docs/mcp-server.md`. Turn off "use my chats for training" in the app you connect.

### 5. iPhone Shortcuts

Build **LifeLog Config**, **Log My Day**, **Quick Note**, **Send pending**, **Send to LifeLog**
and the nightly reminder automation, and reach the API over HTTPS (Tailscale or a reverse proxy):
`docs/iphone-shortcuts.md`.

## Everyday use

* **Log My Day** Shortcut at night (the nightly reminder starts it), **Quick Note** during the day.
* No signal? The Shortcut saves to a "LifeLog Inbox" folder in Files; "Send pending" uploads later.
* Edit any day in Obsidian. Your edits are kept: LifeLog never overwrites them, and it never
  touches the **My notes** section. Later captures for an edited day are added, not rewritten.
* Ask your AI app about your days; answers cite the dates they come from. If an answer is wrong,
  say so and the app records feedback.

## Privacy

No personal content is ever stored in this repository. Your journal, audio, photos, activity
records and feedback stay in your own storage (`LifeLog/` and `LifeLog/_system/`). The index lives
on the server's disk and is backed up to your Drive. Logs never contain journal text.

## Documentation

| Topic | Where |
|---|---|
| Conventions and context for AI coding agents | `AGENTS.md` |
| How the pieces fit | `docs/architecture.md`, `docs/contracts.md` |
| Recording API and iPhone Shortcuts | `docs/recording-api.md`, `docs/iphone-shortcuts.md` |
| Indexer | `docs/indexer.md`, `docs/index-schema.md` |
| MCP server and AI-app setup | `docs/mcp-server.md` |
| Day file format | `docs/day-file-format.md` |
| Why things are the way they are | `docs/decisions/` |
| Maintenance, first run | `docs/runbook.md` |
| What each test checks, in plain English | `docs/test-cases.md` |
| What we learned | `docs/learnings.md`, `CHANGELOG.md` |
