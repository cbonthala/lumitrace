# Runbook

Maintenance procedures. Each work stream fills in its own steps; keep commands copy-pasteable
and never paste real tokens or personal content here.

## First-run checklist

1. **Google OAuth client:** in Google Cloud Console create a project, enable the **Google Drive
   API**, configure the OAuth consent screen (External, add yourself as a user) and **publish it
   (In production)**: in Testing mode refresh tokens expire after 7 days. `drive.file` is a
   non-sensitive scope, so no verification is needed. Create an OAuth client of type **Desktop
   app** and save its JSON as `secrets/gdrive_client_secret.json`.
2. **Drive login:** set `LUMEN_STORAGE_BACKEND=gdrive` in `.env`, then on a machine with a
   browser run `uv run lumen-drive-login` (`--no-browser` prints the URL). It writes
   `secrets/gdrive_token.json`; copy `secrets/` to the server.
3. **Strong secrets:** `openssl rand -hex 32` for `LUMEN_API_TOKEN` and
   `LUMEN_MCP_AUTH_TOKEN`, and a long passphrase for `LUMEN_MCP_OWNER_PASSWORD` (oauth mode).
   With `change-me` or anything under 16 characters the Prism answers `503` and the Lens refuses to start.
4. **Providers:** pick `LUMEN_STT_PROVIDER` / `LUMEN_STT_MODEL`, the `LUMEN_LLM_*` models
   and `LUMEN_EMBEDDING_MODEL` / `LUMEN_EMBEDDING_DIMENSION`, and put the provider keys in
   `.env`. **Turn on the training opt-outs:** OpenAI API data is not used for training by default
   (check the organisation's data controls); for Amazon Transcribe / Bedrock enable the AWS
   Organizations **AI services opt-out policy**; for other providers check their API data terms.
   To try everything first without any provider, use `fake` for all of them.
5. **Deploy:** `docker compose up -d --build`. Check `curl localhost:8000/health` and
   `curl localhost:8002/health`; Spectrum has no published port (`docker compose logs
   spectrum`). Put HTTPS in front of the Prism (Tailscale or a reverse proxy,
   `docs/flash.md`) and of the Lens (`docs/lens.md`); in oauth mode set
   `LUMEN_MCP_PUBLIC_URL` to the Lens's public `https://` root.
6. **Flash (iPhone Shortcuts):** build Flash Config, Log My Day, Quick Note, Send pending, Send to
   Lumen and the nightly reminder (`docs/flash.md`). Send a test Quick Note and
   check that the day file appears in Drive (and in Obsidian).
7. **Connect the AI app:** add the Lens as a connector in Claude or ChatGPT (oauth), or in
   Cursor / Claude Desktop (`docs/lens.md`). Turn off "use my chats for training" in that
   app. Ask about the test note and check that the answer cites its date.

## Rotating tokens

* **Prism token:** generate (`openssl rand -hex 32`), set `LUMEN_API_TOKEN` in `.env`,
  restart `prism` (`docker compose up -d prism`), then update `token` in the **Flash Config**
  shortcut on the iPhone (the other shortcuts read it from there; `docs/flash.md`).
  Captures waiting in the phone's Flash Inbox are sent with the new token by Send pending.
* **Lens token / owner password:** set `LUMEN_MCP_AUTH_TOKEN` or `LUMEN_MCP_OWNER_PASSWORD`,
  restart `lens`, reconnect the AI apps. Both must be 16+ characters (`openssl rand -hex 32`) or
  the server refuses to start.
  * A new **static token** takes effect on restart; update Cursor / `mcp-remote` configs.
  * A new **owner password** does *not* end existing OAuth sessions (apps hold refresh tokens).
    To disconnect every app (lost phone, suspected leak):
    `docker compose run --rm lens lumen-lens reset-oauth`, then
    `docker compose restart lens`,
    then reconnect each app (Claude: Settings → Connectors → Lumen → Connect; ChatGPT:
    Settings → Apps & Connectors → Lumen). This deletes `mcp-oauth-state.json` next to the
    index; the journal and index are untouched.
* **Provider API keys:** update `OPENAI_API_KEY` / AWS credentials in `.env`, restart all services.

## Renewing Google sign-in

* Symptom: storage errors mentioning an invalid or expired token.
* Make sure the OAuth consent screen is **In production** (Testing-mode refresh tokens expire
  after 7 days). `drive.file` is a non-sensitive scope, so no verification is needed.
* On a machine with a browser: `uv run lumen-drive-login` (or `--no-browser` and open the
  printed URL). It writes `LUMEN_GDRIVE_TOKEN_FILE` with mode 0600.
* Copy the token file to the server's `./secrets/` folder and restart the services.
* The app must keep using the **same OAuth client**; with `drive.file`, a different client cannot
  see the existing `Lumen` folder.

## Rebuilding the index (Spectrum)

* When: after changing `LUMEN_EMBEDDING_MODEL` / `LUMEN_EMBEDDING_DIMENSION`, after a schema
  version bump, or if the index looks wrong.
* `docker compose run --rm spectrum lumen-spectrum rebuild` (the running `spectrum` can stay up;
  SQLite serialises the writers). Locally: `uv run lumen-spectrum rebuild`.
* Keeps `feedback` and `edit_signals`; everything else is re-read from storage. Expect roughly
  one storage download per day file plus one embedding call per 16 days; with the `fake`
  embedding model a year of days takes seconds. Search is incomplete while it runs.
* Verify: the command prints `{"kind": "rebuild", "indexed": N, ..., "malformed": [...],
  "failed": [...]}`. `indexed` should equal the number of day files; fix any `malformed` file in
  Obsidian (the log names it) and run `lumen-spectrum sync`. Exit status 1 means some files
  failed transiently; run `sync` again. `curl http://localhost:8001/health` inside the Docker
  network shows the last result of the running Spectrum service.

### Recovering from a lost or corrupt index

1. Stop `spectrum` and `lens` (`docker compose stop spectrum lens`).
2. Either restore the backup (see *Restoring backups*) or delete the index file
   (`LUMEN_INDEX_PATH`, plus any `-wal`/`-shm` files next to it).
3. Start `spectrum`. Without a file it indexes everything from storage on its first cycle; with a
   restored backup it catches up from the backup's sync token. Then start `lens`.
4. Deleting the file without a backup loses `feedback` and `edit_signals` (the rest is rebuilt).
   Feedback also has JSON copies under `_system/feedback/`; edit signals come back for every day
   whose snapshot and day file still differ.

### Changing the embedding model

1. Set `LUMEN_EMBEDDING_MODEL` and `LUMEN_EMBEDDING_DIMENSION` (the model's vector size) in
   `.env`, with the provider's API key.
2. `docker compose up -d spectrum` first. On start it sees the change, logs "rebuilding the
   index", and rebuilds automatically (feedback and edit signals stay).
3. When `/health` (or the log) shows the rebuild finished, `docker compose up -d lens` so it embeds
   queries with the same model. Until then, search fails (new dimension) or returns poor results
   (same dimension, different model).

## Switching AI or speech providers

1. Change the `LUMEN_LLM_*`, `LUMEN_STT_*` or `LUMEN_EMBEDDING_*` settings and provider
   keys in `.env`.
2. Run the answer-quality check (once it exists) and compare with the previous run.
3. Restart the services. For embedding changes, rebuild the index.
4. Record the change and the quality result in `CHANGELOG.md` and `docs/learnings.md`.

## Moving servers

1. Stop the services on the old server.
2. Copy `.env`, `secrets/` and (optionally) the `lumen-data` volume. The index can instead be
   rebuilt from storage.
3. `docker compose up -d --build` on the new server, update DNS / HTTPS proxy, and point the
   Flash shortcuts and MCP clients at the new URLs if they changed.
4. Check `GET /health`, then record a test Quick Note and confirm it appears in Drive and search.

## Restoring backups

* **Index:** stop `spectrum` and `lens`, copy `_system/index-backup/lumen.sqlite` from Drive to
  `LUMEN_INDEX_PATH`, start them; Spectrum catches up from its sync token. Or just rebuild.
* **Journal files:** restore the `Lumen` folder from the off-site backup (not built yet; first
  item after version one), then rebuild the index.
* Test a restore at least once a quarter.

## Checking health

* `GET /health` on the Prism; container logs (`docker compose logs -f`).
* Activity records in `Lumen/_system/activity/YYYY/MM.jsonl` show per-step errors, timing and
  cost (one line per capture attempt).

## Prism (recording API)

Reference: `docs/prism.md`. Logs: `docker compose logs -f prism` (no journal text is
logged).

* **A capture's status:** `curl -H "Authorization: Bearer $TOKEN" $API/captures/<id>`. `done` with
  `errors` means the transcript is saved but an AI step failed (see the activity record);
  `queued` with `retry_at` means an automatic retry is scheduled.
* **Failed captures:** they stay in `Lumen/_system/inbox/<id>/` with status `failed`. Fix the
  cause (provider key, quota, a day file whose front matter was broken in Obsidian), then
  `curl -X POST -H "Authorization: Bearer $TOKEN" $API/captures/<id>/retry`. Or just re-send from
  the phone with the same `capture_id`.
* **Find stuck captures:** list `Lumen/_system/inbox/`; each folder is one capture not yet
  `done`. Restarting the Prism (`docker compose restart prism`) re-queues all of them except
  `failed` ones.
* **Audio not compressed** (warning "audio kept uncompressed" in the log / activity record): the
  container lacks ffmpeg (rebuild the image) or the input format is unreadable. The original is
  kept and embedded, so nothing is lost; to compress it later, convert with
  `ffmpeg -i in -ac 1 -c:a aac -b:a 32k out.m4a` and fix the name in the day file's `audio` list
  and capture block.
* **Switching speech to Amazon Transcribe:** set `LUMEN_STT_PROVIDER=aws_transcribe`,
  `LUMEN_AWS_REGION`, `LUMEN_AWS_TRANSCRIBE_BUCKET` (a private bucket; the Prism deletes its
  objects under `lumen-stt/` after each job), AWS credentials with `s3:PutObject/GetObject/
  DeleteObject` on that prefix and `transcribe:StartTranscriptionJob/GetTranscriptionJob/
  DeleteTranscriptionJob`. Enable the AWS Organizations **AI services opt-out policy** for
  Amazon Transcribe. Restart `prism`.
* **Trying it offline:** `LUMEN_STT_PROVIDER=fake` and all three `LUMEN_LLM_*_MODEL=fake`;
  then `curl -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json'
  -d '{"text": "Test note"}' localhost:8000/notes`.
* **Costs:** sum `cost_usd` from the month's activity file, e.g.
  `jq -s 'map(.cost_usd // 0) | add' 10.jsonl`.

## Lens (MCP server)

Setup and client configs: `docs/lens.md`.

* **Health:** `curl https://journal.example.com/health` → `status`, `auth_mode`,
  `index_present`. Logs: `docker compose logs -f lens` (no journal text is logged).
* **Server won't start, "configuration error":** the token or password is empty, a placeholder
  or too short; or in `oauth` mode `LUMEN_MCP_PUBLIC_URL` is not `https://` or has a path.
* **AI app says "unauthorized" / keeps asking to sign in:** check `LUMEN_MCP_PUBLIC_URL`
  matches the URL the app uses (scheme and host), and that the proxy forwards
  `/.well-known/*`, `/register`, `/authorize`, `/token`, `/revoke` and `/oauth/login` as well as
  `/mcp`. Then reconnect the app.
* **"Too many wrong passwords":** wait 15 minutes (the lockout is in memory; restarting
  `lens` also clears it).
* **Answers say the index has not been built / is empty:** check Spectrum
  (`docker compose logs spectrum`, `lumen-spectrum sync`). `get_day` still works from storage.
* **"index uses dimension N":** the Lens and Spectrum settings disagree on
  `LUMEN_EMBEDDING_DIMENSION`; fix `.env` and rebuild the index.
* **Feedback:** each `feedback` call is in `Lumen/_system/feedback/YYYY/MM/*.json` and in the
  index's `feedback` table (kept across rebuilds).

## Upgrading from LifeLog or Bookshelf

The project was renamed twice: LifeLog (0.1.0) → Bookshelf (decision 0008) → Lumen (decision
0009). A deployment set up under either old name needs these one-time steps; nothing in the
journal itself has to change. Below, *OLD* is `LIFELOG` / `LifeLog` / `lifelog` or `BOOKSHELF` /
`Bookshelf` / `bookshelf`, whichever your setup uses.

| | LifeLog (0.1.0) | Bookshelf | Lumen (now) |
|---|---|---|---|
| Env prefix | `LIFELOG_` | `BOOKSHELF_` | `LUMEN_` |
| Drive root / local root | `LifeLog` / `data/LifeLog` | `Bookshelf` / `data/Bookshelf` | `Lumen` / `data/Lumen` |
| Index file | `data/index/lifelog.sqlite` | `data/index/bookshelf.sqlite` | `data/index/lumen.sqlite` |
| Commands | `lifelog-api`, `lifelog-indexer`, `lifelog-mcp`, `lifelog-gdrive-login` | `bookshelf-typewriter`, `bookshelf-bookmarks`, `bookshelf-reading-lamp`, `bookshelf-drive-login` | `lumen-prism`, `lumen-spectrum`, `lumen-lens`, `lumen-drive-login` |
| Docker services / volume | `api`, `indexer`, `mcp` / `lifelog-data` | `typewriter`, `bookmarks`, `reading-lamp` / `bookshelf-data` | `prism`, `spectrum`, `lens` / `lumen-data` |
| Shortcuts | LifeLog Config, LifeLog Inbox, Send to LifeLog | Notepad Config, Notepad Inbox, Send to Bookshelf | Flash Config, Flash Inbox, Send to Lumen |
| OAuth scope / name in AI apps | `lifelog` / LifeLog | `bookshelf` / Bookshelf | `lumen` / Lumen |

1. **`.env`:** rename every old-prefix variable to `LUMEN_` (for example
   `sed -i.bak -E 's/^(LIFELOG|BOOKSHELF)_/LUMEN_/' .env`). Unrenamed variables are silently
   ignored.
2. **Drive folder:** the default root folder is now `Lumen`. Either rename the existing
   `LifeLog` or `Bookshelf` folder in Drive to `Lumen` (the app finds it again because it created
   it), or keep the old name with `LUMEN_GDRIVE_ROOT_FOLDER=Bookshelf` (or `LifeLog`). For local
   storage, move `data/LifeLog` or `data/Bookshelf` to `data/Lumen`, or set `LUMEN_LOCAL_ROOT`.
3. **Index:** move the old index file (`data/index/lifelog.sqlite` or
   `data/index/bookshelf.sqlite`, plus `-wal`/`-shm`) to `data/index/lumen.sqlite`, or set
   `LUMEN_INDEX_PATH` to the old file, so `feedback` and `edit_signals` are kept. New backups go
   to `_system/index-backup/lumen.sqlite`.
4. **Docker:** services are now `prism`, `spectrum` and `lens`, and the volume is `lumen-data`.
   Run `docker compose down` *before* pulling the new compose file, then copy the old volume
   (`lifelog-data` or `bookshelf-data`) into `lumen-data`, or rebuild the index from storage.
   Compose prefixes volume names with the project (folder) name, so after the repository folder
   is renamed to `lumen` look for the old volume with `docker volume ls`.
5. **Commands:** the old commands (see the table) are now `lumen-prism`, `lumen-spectrum`,
   `lumen-lens` and `lumen-drive-login`. Update Claude Desktop / Cursor MCP configs
   (`docs/lens.md`).
6. **OAuth:** the scope is now `lumen` and AI apps list the connector as **Lumen**; run
   `lumen-lens reset-oauth` and reconnect each AI app.
7. **iPhone (Flash):** rename the helper shortcuts to **Flash Config** and **Send to Lumen**,
   and the Files folder iCloud Drive → Shortcuts → old inbox folder to **Flash Inbox**; then
   update the `Run Shortcut` step and the inbox paths in Log My Day, Quick Note and Send pending
   (`docs/flash.md`). Send pending first if the old inbox still holds captures. Log My Day,
   Quick Note and Send pending keep their names.
8. **Day files:** nothing to do. Files with the old `lifelog:` or `bookshelf:` markers and
   `lifelog_format` or `bookshelf_format` key are still read, and are rewritten with the new
   names the next time the Prism writes that day.
