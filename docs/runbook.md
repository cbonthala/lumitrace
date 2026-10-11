# Runbook

Maintenance procedures. Each work stream fills in its own steps; keep commands copy-pasteable
and never paste real tokens or personal content here.

## First-run checklist

1. **Google OAuth client:** in Google Cloud Console create a project, enable the **Google Drive
   API**, configure the OAuth consent screen (External, add yourself as a user) and **publish it
   (In production)**: in Testing mode refresh tokens expire after 7 days. `drive.file` is a
   non-sensitive scope, so no verification is needed. Create an OAuth client of type **Desktop
   app** and save its JSON as `secrets/gdrive_client_secret.json`.
2. **Drive login:** set `LIFELOG_STORAGE_BACKEND=gdrive` in `.env`, then on a machine with a
   browser run `uv run lifelog-gdrive-login` (`--no-browser` prints the URL). It writes
   `secrets/gdrive_token.json`; copy `secrets/` to the server.
3. **Strong secrets:** `openssl rand -hex 32` for `LIFELOG_API_TOKEN` and
   `LIFELOG_MCP_AUTH_TOKEN`, and a long passphrase for `LIFELOG_MCP_OWNER_PASSWORD` (oauth mode).
   With `change-me` or anything under 16 characters the API answers `503` and the MCP server
   refuses to start.
4. **Providers:** pick `LIFELOG_STT_PROVIDER` / `LIFELOG_STT_MODEL`, the `LIFELOG_LLM_*` models
   and `LIFELOG_EMBEDDING_MODEL` / `LIFELOG_EMBEDDING_DIMENSION`, and put the provider keys in
   `.env`. **Turn on the training opt-outs:** OpenAI API data is not used for training by default
   (check the organisation's data controls); for Amazon Transcribe / Bedrock enable the AWS
   Organizations **AI services opt-out policy**; for other providers check their API data terms.
   To try everything first without any provider, use `fake` for all of them.
5. **Deploy:** `docker compose up -d --build`. Check `curl localhost:8000/health` and
   `curl localhost:8002/health`; the indexer has no published port (`docker compose logs
   indexer`). Put HTTPS in front of the API (Tailscale or a reverse proxy,
   `docs/iphone-shortcuts.md`) and of the MCP server (`docs/mcp-server.md`); in oauth mode set
   `LIFELOG_MCP_PUBLIC_URL` to the MCP server's public `https://` root.
6. **iPhone Shortcuts:** build LifeLog Config, Log My Day, Quick Note, Send pending, Send to
   LifeLog and the nightly reminder (`docs/iphone-shortcuts.md`). Send a test Quick Note and
   check that the day file appears in Drive (and in Obsidian).
7. **Connect the AI app:** add the MCP server as a connector in Claude or ChatGPT (oauth), or in
   Cursor / Claude Desktop (`docs/mcp-server.md`). Turn off "use my chats for training" in that
   app. Ask about the test note and check that the answer cites its date.

## Rotating tokens

* **Recording API token:** generate (`openssl rand -hex 32`), set `LIFELOG_API_TOKEN` in `.env`,
  restart `api` (`docker compose up -d api`), then update `token` in the **LifeLog Config**
  shortcut on the iPhone (the other shortcuts read it from there; `docs/iphone-shortcuts.md`).
  Captures waiting in the phone's LifeLog Inbox are sent with the new token by Send pending.
* **MCP token / owner password:** set `LIFELOG_MCP_AUTH_TOKEN` or `LIFELOG_MCP_OWNER_PASSWORD`,
  restart `mcp`, reconnect the AI apps. Both must be 16+ characters (`openssl rand -hex 32`) or
  the server refuses to start.
  * A new **static token** takes effect on restart; update Cursor / `mcp-remote` configs.
  * A new **owner password** does *not* end existing OAuth sessions (apps hold refresh tokens).
    To disconnect every app (lost phone, suspected leak):
    `docker compose run --rm mcp lifelog-mcp reset-oauth`, then `docker compose restart mcp`,
    then reconnect each app (Claude: Settings → Connectors → LifeLog → Connect; ChatGPT:
    Settings → Apps & Connectors → LifeLog). This deletes `mcp-oauth-state.json` next to the
    index; the journal and index are untouched.
* **Provider API keys:** update `OPENAI_API_KEY` / AWS credentials in `.env`, restart all services.

## Renewing Google sign-in

* Symptom: storage errors mentioning an invalid or expired token.
* Make sure the OAuth consent screen is **In production** (Testing-mode refresh tokens expire
  after 7 days). `drive.file` is a non-sensitive scope, so no verification is needed.
* On a machine with a browser: `uv run lifelog-gdrive-login` (or `--no-browser` and open the
  printed URL). It writes `LIFELOG_GDRIVE_TOKEN_FILE` with mode 0600.
* Copy the token file to the server's `./secrets/` folder and restart the services.
* The app must keep using the **same OAuth client**; with `drive.file`, a different client cannot
  see the existing `LifeLog` folder.

## Rebuilding the index

* When: after changing `LIFELOG_EMBEDDING_MODEL` / `LIFELOG_EMBEDDING_DIMENSION`, after a schema
  version bump, or if the index looks wrong.
* `docker compose run --rm indexer lifelog-indexer rebuild` (the running `indexer` can stay up;
  SQLite serialises the writers). Locally: `uv run lifelog-indexer rebuild`.
* Keeps `feedback` and `edit_signals`; everything else is re-read from storage. Expect roughly
  one storage download per day file plus one embedding call per 16 days; with the `fake`
  embedding model a year of days takes seconds. Search is incomplete while it runs.
* Verify: the command prints `{"kind": "rebuild", "indexed": N, ..., "malformed": [...],
  "failed": [...]}`. `indexed` should equal the number of day files; fix any `malformed` file in
  Obsidian (the log names it) and run `lifelog-indexer sync`. Exit status 1 means some files
  failed transiently; run `sync` again. `curl http://localhost:8001/health` inside the Docker
  network shows the last result of the running indexer.

### Recovering from a lost or corrupt index

1. Stop `indexer` and `mcp` (`docker compose stop indexer mcp`).
2. Either restore the backup (see *Restoring backups*) or delete the index file
   (`LIFELOG_INDEX_PATH`, plus any `-wal`/`-shm` files next to it).
3. Start `indexer`. Without a file it indexes everything from storage on its first cycle; with a
   restored backup it catches up from the backup's sync token. Then start `mcp`.
4. Deleting the file without a backup loses `feedback` and `edit_signals` (the rest is rebuilt).
   Feedback also has JSON copies under `_system/feedback/`; edit signals come back for every day
   whose snapshot and day file still differ.

### Changing the embedding model

1. Set `LIFELOG_EMBEDDING_MODEL` and `LIFELOG_EMBEDDING_DIMENSION` (the model's vector size) in
   `.env`, with the provider's API key.
2. `docker compose up -d indexer` first. On start it sees the change, logs "rebuilding the
   index", and rebuilds automatically (feedback and edit signals stay).
3. When `/health` (or the log) shows the rebuild finished, `docker compose up -d mcp` so it embeds
   queries with the same model. Until then, search fails (new dimension) or returns poor results
   (same dimension, different model).

## Switching AI or speech providers

1. Change the `LIFELOG_LLM_*`, `LIFELOG_STT_*` or `LIFELOG_EMBEDDING_*` settings and provider
   keys in `.env`.
2. Run the answer-quality check (once it exists) and compare with the previous run.
3. Restart the services. For embedding changes, rebuild the index.
4. Record the change and the quality result in `CHANGELOG.md` and `docs/learnings.md`.

## Moving servers

1. Stop the services on the old server.
2. Copy `.env`, `secrets/` and (optionally) the `lifelog-data` volume. The index can instead be
   rebuilt from storage.
3. `docker compose up -d --build` on the new server, update DNS / HTTPS proxy, and point the
   iPhone Shortcuts and MCP clients at the new URLs if they changed.
4. Check `GET /health`, then record a test Quick Note and confirm it appears in Drive and search.

## Restoring backups

* **Index:** stop `indexer` and `mcp`, copy `_system/index-backup/lifelog.sqlite` from Drive to
  `LIFELOG_INDEX_PATH`, start them; the indexer catches up from its sync token. Or just rebuild.
* **Journal files:** restore the `LifeLog` folder from the off-site backup (not built yet; first
  item after version one), then rebuild the index.
* Test a restore at least once a quarter.

## Checking health

* `GET /health` on the API; container logs (`docker compose logs -f`).
* Activity records in `LifeLog/_system/activity/YYYY/MM.jsonl` show per-step errors, timing and
  cost (one line per capture attempt).

## Recording API

Reference: `docs/recording-api.md`. Logs: `docker compose logs -f api` (no journal text is
logged).

* **A capture's status:** `curl -H "Authorization: Bearer $TOKEN" $API/captures/<id>`. `done` with
  `errors` means the transcript is saved but an AI step failed (see the activity record);
  `queued` with `retry_at` means an automatic retry is scheduled.
* **Failed captures:** they stay in `LifeLog/_system/inbox/<id>/` with status `failed`. Fix the
  cause (provider key, quota, a day file whose front matter was broken in Obsidian), then
  `curl -X POST -H "Authorization: Bearer $TOKEN" $API/captures/<id>/retry`. Or just re-send from
  the phone with the same `capture_id`.
* **Find stuck captures:** list `LifeLog/_system/inbox/`; each folder is one capture not yet
  `done`. Restarting the API (`docker compose restart api`) re-queues all of them except
  `failed` ones.
* **Audio not compressed** (warning "audio kept uncompressed" in the log / activity record): the
  container lacks ffmpeg (rebuild the image) or the input format is unreadable. The original is
  kept and embedded, so nothing is lost; to compress it later, convert with
  `ffmpeg -i in -ac 1 -c:a aac -b:a 32k out.m4a` and fix the name in the day file's `audio` list
  and capture block.
* **Switching speech to Amazon Transcribe:** set `LIFELOG_STT_PROVIDER=aws_transcribe`,
  `LIFELOG_AWS_REGION`, `LIFELOG_AWS_TRANSCRIBE_BUCKET` (a private bucket; the API deletes its
  objects under `lifelog-stt/` after each job), AWS credentials with `s3:PutObject/GetObject/
  DeleteObject` on that prefix and `transcribe:StartTranscriptionJob/GetTranscriptionJob/
  DeleteTranscriptionJob`. Enable the AWS Organizations **AI services opt-out policy** for
  Amazon Transcribe. Restart `api`.
* **Trying it offline:** `LIFELOG_STT_PROVIDER=fake` and all three `LIFELOG_LLM_*_MODEL=fake`;
  then `curl -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json'
  -d '{"text": "Test note"}' localhost:8000/notes`.
* **Costs:** sum `cost_usd` from the month's activity file, e.g.
  `jq -s 'map(.cost_usd // 0) | add' 10.jsonl`.

## MCP server

Setup and client configs: `docs/mcp-server.md`.

* **Health:** `curl https://journal.example.com/health` → `status`, `auth_mode`,
  `index_present`. Logs: `docker compose logs -f mcp` (no journal text is logged).
* **Server won't start, "configuration error":** the token or password is empty, a placeholder
  or too short; or in `oauth` mode `LIFELOG_MCP_PUBLIC_URL` is not `https://` or has a path.
* **AI app says "unauthorized" / keeps asking to sign in:** check `LIFELOG_MCP_PUBLIC_URL`
  matches the URL the app uses (scheme and host), and that the proxy forwards
  `/.well-known/*`, `/register`, `/authorize`, `/token`, `/revoke` and `/oauth/login` as well as
  `/mcp`. Then reconnect the app.
* **"Too many wrong passwords":** wait 15 minutes (the lockout is in memory; restarting `mcp`
  also clears it).
* **Answers say the index has not been built / is empty:** check the indexer
  (`docker compose logs indexer`, `lifelog-indexer sync`). `get_day` still works from storage.
* **"index uses dimension N":** the MCP and indexer settings disagree on
  `LIFELOG_EMBEDDING_DIMENSION`; fix `.env` and rebuild the index.
* **Feedback:** each `feedback` call is in `LifeLog/_system/feedback/YYYY/MM/*.json` and in the
  index's `feedback` table (kept across rebuilds).
