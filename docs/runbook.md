# Runbook

Maintenance procedures. Each work stream fills in its own steps; keep commands copy-pasteable
and never paste real tokens or personal content here.

## First-run checklist

1. **Google OAuth client:** in Google Cloud Console create a project, enable the **Google Drive
   API**, configure the OAuth consent screen (External, add yourself as a user) and **publish it
   (In production)**: in Testing mode refresh tokens expire after 7 days. `drive.file` is a
   non-sensitive scope, so no verification is needed. Create an OAuth client of type **Desktop
   app** and save its JSON as `secrets/gdrive_client_secret.json`.
2. **Drive login:** set `LUMITRACE_STORAGE_BACKEND=gdrive` in `.env`, then on a machine with a
   browser run `uv run lumitrace-drive-login` (`--no-browser` prints the URL). It writes
   `secrets/gdrive_token.json`; copy `secrets/` to the server.
3. **Strong secrets:** `openssl rand -hex 32` for `LUMITRACE_API_TOKEN`, and a long passphrase
   for `LUMITRACE_MCP_OWNER_PASSWORD` (the Lens's only login).
   With `change-me` or anything under 16 characters the Prism answers `503` and the Lens refuses to start.
4. **Providers:** pick `LUMITRACE_STT_PROVIDER` / `LUMITRACE_STT_MODEL`, the `LUMITRACE_LLM_*` models
   and `LUMITRACE_EMBEDDING_MODEL` / `LUMITRACE_EMBEDDING_DIMENSION`, and put the provider keys in
   `.env`. **Turn on the training opt-outs:** OpenAI API data is not used for training by default
   (check the organisation's data controls); for Amazon Transcribe / Bedrock enable the AWS
   Organizations **AI services opt-out policy**; for other providers check their API data terms.
   To try everything first without any provider, use `fake` for all of them.
   Copy `docs/templates/family.example.md` to `secrets/family.md` and fill in the real family.
   Each person in that list gets a block in every per-person section of the day file. The person
   with `relation: me` is the one speaking. Notes under the front matter (other people, relation
   words, foods, places, usual routines) go to the prompts so they can resolve what was said.
   A usual routine is not written for a day unless the transcript says it that day.
5. **Deploy:** on AWS, follow *Deploying on AWS Lightsail* below; elsewhere
   `docker compose up -d --build`. Check `curl localhost:8000/health` and
   `curl localhost:8002/health`; Spectrum has no published port (`docker compose logs
   spectrum`). Put HTTPS in front of the Prism (Tailscale or a reverse proxy,
   `docs/flash.md`) and of the Lens (`docs/lens.md`); in oauth mode set
   `LUMITRACE_MCP_PUBLIC_URL` to the Lens's public `https://` root.
6. **Flash:** set `LUMITRACE_FLASH_USERNAME` and `LUMITRACE_FLASH_PASSWORD` (10+ characters),
   restart `prism`, open `https://<prism address>/flash/`, sign in and add it to the Home
   Screen. Optionally build the Shortcuts too: Flash Config, Log My Day, Quick Note, Send
   pending, Send to Lumitrace and the nightly reminder (`docs/flash.md`). Send a test Quick
   Note and check that the day file appears in Drive (and in Obsidian).
7. **Connect the AI app:** add the Lens as a connector in Claude or ChatGPT (oauth), or in
   Cursor / Claude Desktop (`docs/lens.md`). Turn off "use my chats for training" in that
   app. Ask about the test note and check that the answer cites its date.

## Rotating tokens

* **Prism token:** generate (`openssl rand -hex 32`), set `LUMITRACE_API_TOKEN` in `.env`,
  restart `prism` (`docker compose up -d prism`), then update `token` in the **Flash Config**
  shortcut on the iPhone (the other shortcuts read it from there; `docs/flash.md`).
  Captures waiting in the phone's Flash Inbox are sent with the new token by Send pending.
  Changing the token also signs every Flash web app browser out (sessions are signed with it).
* **Flash web app password:** set `LUMITRACE_FLASH_PASSWORD` (and/or `LUMITRACE_FLASH_USERNAME`)
  and restart `prism`. Every signed-in browser is signed out and asks for the new password;
  captures waiting in a browser stay there and are sent after signing in again. After five wrong
  passwords sign-in is locked for 15 minutes (restarting `prism` clears the lock).
* **Lens owner password:** set `LUMITRACE_MCP_OWNER_PASSWORD` (16+ characters or the server
  refuses to start) and restart `lens`. The Lens has no static token (decision 0035).
  * OAuth sessions end on their own `LUMITRACE_MCP_SESSION_DAYS` (default 7) after each
    sign-in; the app then asks for the owner password again.
  * A new **owner password** does *not* end existing OAuth sessions (apps hold refresh tokens).
    To disconnect one app or all of them, use the Flash web app: Settings → **Connected AI
    apps** → **Disconnect** / **Disconnect all apps** (takes effect at once, no restart). If the
    Flash app is unavailable, use the command line instead:
    `docker compose run --rm lens lumitrace-lens reset-oauth`, then
    `docker compose restart lens`,
    then reconnect each app (Claude: Settings → Connectors → Lumitrace → Connect; ChatGPT:
    Settings → Apps & Connectors → Lumitrace). This deletes `mcp-oauth-state.json` next to the
    index; the journal and index are untouched.
* **Provider API keys:** update `GEMINI_API_KEY` / `LUMITRACE_SARVAM_API_KEY` in `.env`, restart all services.

## Renewing Google sign-in

* Symptom: storage errors mentioning an invalid or expired token.
* Make sure the OAuth consent screen is **In production** (Testing-mode refresh tokens expire
  after 7 days). `drive.file` is a non-sensitive scope, so no verification is needed.
* On a machine with a browser: `uv run lumitrace-drive-login` (or `--no-browser` and open the
  printed URL). It writes `LUMITRACE_GDRIVE_TOKEN_FILE` with mode 0600.
* Copy the token file to the server's `./secrets/` folder and restart the services. On
  Lightsail, run `SECRETS_DIR=secrets deploy/lightsail/deploy.sh`, which also gives the files to
  the container user (uid 10001).
* The app must keep using the **same OAuth client**; with `drive.file`, a different client cannot
  see the existing `Lumitrace` folder.

## Rebuilding the index (Spectrum)

* When: after changing `LUMITRACE_EMBEDDING_MODEL` / `LUMITRACE_EMBEDDING_DIMENSION`, after a schema
  version bump, or if the index looks wrong.
* `docker compose run --rm spectrum lumitrace-spectrum rebuild` (the running `spectrum` can stay up;
  SQLite serialises the writers). Locally: `uv run lumitrace-spectrum rebuild`.
* Keeps `feedback` and `edit_signals`; everything else is re-read from storage. Expect roughly
  one storage download per day file plus one embedding call per 16 days; with the `fake`
  embedding model a year of days takes seconds. Search is incomplete while it runs.
* Verify: the command prints `{"kind": "rebuild", "indexed": N, ..., "malformed": [...],
  "failed": [...]}`. `indexed` should equal the number of day files; fix any `malformed` file in
  Obsidian (the log names it) and run `lumitrace-spectrum sync`. Exit status 1 means some files
  failed transiently; run `sync` again. `curl http://localhost:8001/health` inside the Docker
  network shows the last result of the running Spectrum service.

* After upgrading Lumitrace to a version with a new index schema (for example day file format 3,
  which reorganised the fact tables), no manual step is needed: Spectrum sees the old
  `schema_version` on start, logs "rebuilding the index" and rebuilds. Older day files (format 1 or 2) are read as
  they are and rewritten in format 3 the next time the Prism writes that day. To convert past
  days at once (this calls the AI models and costs money):

  1. `lumitrace-prism regenerate --dry-run` lists what would change.
  2. Fill in `secrets/family.md` (copy `docs/templates/family.example.md`) before regenerating.
  3. `lumitrace-prism regenerate --from 2026-10-01 --to 2026-10-15 --nudge` runs Generate for a
     range; omit the dates for every day. In Docker: `docker compose run --rm prism lumitrace-prism regenerate ...`.
  This is the same safe update as the Flash Generate button, including days you edited.

### Recovering from a lost or corrupt index

1. Stop `spectrum` and `lens` (`docker compose stop spectrum lens`).
2. Either restore the backup (see *Restoring backups*) or delete the index file
   (`LUMITRACE_INDEX_PATH`, plus any `-wal`/`-shm` files next to it).
3. Start `spectrum`. Without a file it indexes everything from storage on its first cycle; with a
   restored backup it catches up from the backup's sync token. Then start `lens`.
4. Deleting the file without a backup loses `feedback` and `edit_signals` (the rest is rebuilt).
   Feedback also has JSON copies under `_system/feedback/`; edit signals come back for every day
   whose snapshot and day file still differ.

### Changing the embedding model

1. Set `LUMITRACE_EMBEDDING_MODEL` and `LUMITRACE_EMBEDDING_DIMENSION` (the model's vector size) in
   `.env`, with the provider's API key.
2. `docker compose up -d spectrum` first. On start it sees the change, logs "rebuilding the
   index", and rebuilds automatically (feedback and edit signals stay).
3. When `/health` (or the log) shows the rebuild finished, `docker compose up -d lens` so it embeds
   queries with the same model. Until then, search fails (new dimension) or returns poor results
   (same dimension, different model).

## Deploying on AWS Lightsail (with Tailscale)

One 2 GB Lightsail instance in `us-east-2` runs the three services with Docker Compose
(decision 0041). Scripts in `deploy/lightsail/` run from your computer with the AWS CLI; AI and
speech providers stay external (their keys only in the server's `.env`).

1. **AWS access:** in IAM create a user or SSO permission set with
   `deploy/lightsail/iam-policy.json`, then on your computer `aws configure sso` (or
   `aws configure`) and `export AWS_PROFILE=<profile>`. Never paste keys into chats or the repo.
2. **Create the server:** `deploy/lightsail/provision.sh`. It creates (if missing) the SSH key
   `~/.ssh/lumitrace-lightsail`, the instance `lumitrace` (Ubuntu 24.04, daily automatic snapshots), the
   static IP `lumitrace-ip`, and a firewall that only allows SSH from your current IP. Re-run it if
   your IP changes. First boot installs Docker, Tailscale and a swap file (a few minutes). If
   `/var/lib/lumitrace-bootstrap-done` is still missing after ~10 minutes (`sudo cloud-init status
   --long` on the server), run it by hand:
   `ssh -i ~/.ssh/lumitrace-lightsail ubuntu@<ip> 'sudo sh -s' < deploy/lightsail/cloud-init.sh`.
3. **Production settings:** write a local `.env.production` (git-ignored) from `.env.example`:
   real providers, `LUMITRACE_API_TOKEN` and `LUMITRACE_MCP_OWNER_PASSWORD`,
   `LUMITRACE_STORAGE_BACKEND=gdrive`, and `LUMITRACE_MCP_AUTH_MODE=oauth` (the public URL
   comes in step 5). Delete the `LUMITRACE_PROMPTS_DIR`, `LUMITRACE_LOCAL_ROOT`, `LUMITRACE_INDEX_PATH`
   and `LUMITRACE_GDRIVE_*_FILE` lines: the image sets the container paths (`/secrets/...`,
   `/data/...`) and the env file would override them with paths that do not exist there. Put
   the Google Drive files and `secrets/family.md` in `secrets/` (see *First-run checklist*).
4. **Deploy:** `ENV_FILE=.env.production SECRETS_DIR=secrets deploy/lightsail/deploy.sh`. It
   uploads both, copies the committed code (git `HEAD`) to `/opt/lumitrace/app`, and starts the
   services with `deploy/lightsail/compose.lightsail.yml` (ports on `127.0.0.1` only). Later
   deploys: commit, then `deploy/lightsail/deploy.sh` (add `ENV_FILE=...` when settings change).
5. **Tailscale (once):** `ssh -i ~/.ssh/lumitrace-lightsail ubuntu@<ip>`, then
   `sudo /opt/lumitrace/app/deploy/lightsail/tailscale.sh`. Open the sign-in link it prints (and the
   Funnel link if asked; MagicDNS and HTTPS certificates must be on in the Tailscale admin
   console). It prints the two addresses (decision 0044):
   * Prism, tailnet only: `https://lumitrace.<tailnet>.ts.net` (no port); open it for the Flash
     app and use it in Flash Config. The iPhone needs the Tailscale app with VPN On Demand
     (`docs/flash.md`).
   * Lens, public through Funnel: `https://lumitrace.<tailnet>.ts.net:8443/mcp`; set
     `LUMITRACE_MCP_PUBLIC_URL=https://lumitrace.<tailnet>.ts.net:8443` in `.env.production` and
     redeploy with `ENV_FILE=.env.production`.
   The script resets any earlier serve/funnel setup first, so it is safe to run again (for
   example after renaming the tailnet; see *Renaming the tailnet*).
6. **Optional:** with Tailscale SSH working (`ssh ubuntu@lumitrace`), remove the SSH rule in the
   Lightsail console (Networking tab) so no port is open to the internet.
7. **Check:** `https://lumitrace.<tailnet>.ts.net/health` from Safari on the phone,
   `curl https://lumitrace.<tailnet>.ts.net:8443/health` from anywhere, then a test Quick Note.

### Renaming the tailnet

The tailnet name (Tailscale admin console → DNS → *Rename tailnet*) is part of both addresses,
so a rename changes them at once:

1. In the Flash app, check Settings → **Waiting to send** is 0 (a new address is a new site to
   the browser; captures waiting under the old one would stay there).
2. Rename the tailnet. Set `LUMITRACE_MCP_PUBLIC_URL=https://lumitrace.<new>.ts.net:8443` in
   `.env.production`, deploy with `ENV_FILE=.env.production`, then run
   `sudo /opt/lumitrace/app/deploy/lightsail/tailscale.sh` on the server.
3. Phone: open `https://lumitrace.<new>.ts.net`, sign in, add it to the Home Screen again and
   delete the old icon; update the address in Flash Config.
4. Claude / ChatGPT / Cursor: remove the Lumitrace connector and add it again with
   `https://lumitrace.<new>.ts.net:8443/mcp`, then sign in with the Lens password.

Logs: `ssh ... 'cd /opt/lumitrace/app && docker compose -p lumitrace logs -f'`. The data volume is
`lumitrace_lumitrace-data`; the daily Lightsail snapshot covers it, `.env` and `secrets/`. Cost: the
bundle price (about $12 a month for 2 GB) plus snapshot storage.

## Switching AI or speech providers

1. Change the `LUMITRACE_LLM_*`, `LUMITRACE_STT_*` or `LUMITRACE_EMBEDDING_*` settings and provider
   keys in `.env`.
2. Run the answer-quality check (once it exists) and compare with the previous run.
3. Restart the services. For embedding changes, rebuild the index.
4. Record the change and the quality result in `CHANGELOG.md` and `docs/learnings.md`.

## Moving servers

1. Stop the services on the old server.
2. Copy `.env`, `secrets/` and (optionally) the `lumitrace-data` volume. The index can instead be
   rebuilt from storage.
3. `docker compose up -d --build` on the new server, update DNS / HTTPS proxy, and point the
   Flash shortcuts and MCP clients at the new URLs if they changed.
4. Check `GET /health`, then record a test Quick Note and confirm it appears in Drive and search.

## Restoring backups

* **Index:** stop `spectrum` and `lens`, copy `_system/index-backup/lumitrace.sqlite` from Drive to
  `LUMITRACE_INDEX_PATH`, start them; Spectrum catches up from its sync token. Or just rebuild.
* **Journal files:** restore the `Lumitrace` folder from the off-site backup (not built yet; first
  item after version one), then rebuild the index.
* Test a restore at least once a quarter.

## Checking health

* `GET /health` on the Prism; container logs (`docker compose logs -f`).
* Activity records in `Lumitrace/_system/activity/YYYY/MM.jsonl` show per-step errors, timing and
  cost (one line per capture attempt).

## Prism (recording API)

Reference: `docs/prism.md`. Logs: `docker compose logs -f prism` (no journal text is
logged).

* **A capture's status:** `curl -H "Authorization: Bearer $TOKEN" $API/captures/<id>`. `done` with
  `errors` means the transcript is saved but an AI step failed (see the activity record);
  `queued` with `retry_at` means an automatic retry is scheduled.
* **Failed captures:** they stay in `Lumitrace/_system/inbox/<id>/` with status `failed`. Fix the
  cause (provider key, quota, a day file whose front matter was broken in Obsidian), then
  `curl -X POST -H "Authorization: Bearer $TOKEN" $API/captures/<id>/retry`. Or just re-send from
  the phone with the same `capture_id`.
* **Find stuck captures:** list `Lumitrace/_system/inbox/`; each folder is one capture not yet
  `done`. Restarting the Prism (`docker compose restart prism`) re-queues all of them except
  `failed` ones.
* **Audio not compressed** (warning "audio kept uncompressed" in the log / activity record): the
  container lacks ffmpeg (rebuild the image) or the input format is unreadable. The original is
  kept and embedded, so nothing is lost; to compress it later, convert with
  `ffmpeg -i in -ac 1 -c:a aac -b:a 32k out.m4a` and fix the name in the day file's `audio` list
  and capture block.
* **Switching speech to Amazon Transcribe:** set `LUMITRACE_STT_PROVIDER=aws_transcribe`,
  `LUMITRACE_AWS_REGION`, `LUMITRACE_AWS_TRANSCRIBE_BUCKET` (a private bucket; the Prism deletes its
  objects under `lumitrace-stt/` after each job), AWS credentials with `s3:PutObject/GetObject/
  DeleteObject` on that prefix and `transcribe:StartTranscriptionJob/GetTranscriptionJob/
  DeleteTranscriptionJob`. Enable the AWS Organizations **AI services opt-out policy** for
  Amazon Transcribe. Restart `prism`.
* **Switching speech to Sarvam** (Telugu, Hindi, Tamil, ... also mixed with English): create an
  API key at [dashboard.sarvam.ai](https://dashboard.sarvam.ai), then set
  `LUMITRACE_STT_PROVIDER=sarvam`, `LUMITRACE_SARVAM_API_KEY=<key>`, `LUMITRACE_STT_LANGUAGE=te`
  (or empty to detect), and optionally `LUMITRACE_STT_KEYTERMS` (places and brands you mention;
  family names are added automatically). Sarvam runs one transcript job (ADR 0048). Check
  Sarvam's data terms before sending private audio. Restart `prism`. The next recording's
  activity record shows `"stt": "sarvam/saaras:v4"`.
* **Trying it offline:** `LUMITRACE_STT_PROVIDER=fake` and all three `LUMITRACE_LLM_*_MODEL=fake`;
  then `curl -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json'
  -d '{"text": "Test note"}' localhost:8000/notes`.
* **Costs:** sum `cost_usd` from the month's activity file, e.g.
  `jq -s 'map(.cost_usd // 0) | add' 10.jsonl`.

## Lens (MCP server)

Setup and client configs: `docs/lens.md`.

* **Health:** `curl https://journal.example.com/health` → `status`, `auth_mode`,
  `index_present`. Logs: `docker compose logs -f lens` (no journal text is logged).
* **Server won't start, "configuration error":** the token or password is empty, a placeholder
  or too short; or in `oauth` mode `LUMITRACE_MCP_PUBLIC_URL` is not `https://` or has a path.
* **AI app says "unauthorized" / keeps asking to sign in:** check `LUMITRACE_MCP_PUBLIC_URL`
  matches the URL the app uses (scheme and host), and that the proxy forwards
  `/.well-known/*`, `/register`, `/authorize`, `/token`, `/revoke` and `/oauth/login` as well as
  `/mcp`. Then reconnect the app.
* **"Too many wrong passwords":** wait 15 minutes (the lockout is in memory; restarting
  `lens` also clears it).
* **Answers say the index has not been built / is empty:** check Spectrum
  (`docker compose logs spectrum`, `lumitrace-spectrum sync`). `get_day` still works from storage.
* **"index uses dimension N":** the Lens and Spectrum settings disagree on
  `LUMITRACE_EMBEDDING_DIMENSION`; fix `.env` and rebuild the index.
* **Feedback:** each `feedback` call is in `Lumitrace/_system/feedback/YYYY/MM/*.json` and in the
  index's `feedback` table (kept across rebuilds).

## Trying the API with Bruno

`bruno/` is a [Bruno](https://www.usebruno.com) collection with one folder per module that has
an HTTP API: **Prism**, **Spectrum** and **Lens** (with **OAuth** and **MCP** subfolders).
`tests/test_bruno_collection.py` keeps it in step with the code.

1. In Bruno: **Open Collection** → choose the `bruno/` folder.
2. Copy `bruno/.env.example` to `bruno/.env` (git-ignored) and fill in the API token (the same
   value as `LUMITRACE_API_TOKEN` on that server) and, for production, the Tailscale addresses.
3. Pick the **Local** or **Production** environment, then run **Health** in each folder.
4. **Prism:** Quick note (JSON) needs nothing else. For the multipart requests, put a photo and a
   short audio file in `bruno/samples/` (git-ignored) as `photo.jpg` and `recording.m4a`, or pick
   files in the Body tab. Each upload saves its `capture_id`, so **Capture status** works next.
   The uploads have an empty `date` body field: leave it empty for today, or set `YYYY-MM-DD`
   to file the capture under an earlier day.
5. **Lens → MCP:** run **Initialize** first (it saves the session id), then any tool call.
   They send `mcpToken` as a bearer token, and the Lens only accepts OAuth access tokens
   (1 hour): put one from an OAuth sign-in in `LOCAL_MCP_TOKEN` / `PROD_MCP_TOKEN`, or ask
   through an AI app instead. There is no static token (decision 0035).

In production, notes and recordings are added to today's real journal and **feedback** writes a
real feedback record. Production Prism calls need this computer on the tailnet.

**Spectrum in production** is not published (port 8001, no auth). To reach it, open a tunnel
and keep it running while you use the Spectrum requests (`spectrumUrl` is `localhost:18001`):

```bash
ip=$(aws lightsail get-static-ip --static-ip-name lumitrace-ip --query staticIp.ipAddress --output text)
cid=$(ssh -i ~/.ssh/lumitrace-lightsail ubuntu@$ip \
  "docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' lumitrace-spectrum-1")
ssh -i ~/.ssh/lumitrace-lightsail -N -L 18001:$cid:8001 ubuntu@$ip
```

## Upgrading from LifeLog, Bookshelf or Lumen

The project was renamed three times: LifeLog (0.1.0) → Bookshelf (decision 0008) → Lumen
(decision 0009) → Lumitrace (decision 0042). A deployment set up under any old name needs these
one-time steps; nothing in the journal itself has to change.

| | LifeLog (0.1.0) | Bookshelf | Lumen | Lumitrace (now) |
|---|---|---|---|---|
| Env prefix | `LIFELOG_` | `BOOKSHELF_` | `LUMEN_` | `LUMITRACE_` |
| Drive root / local root | `LifeLog` / `data/LifeLog` | `Bookshelf` / `data/Bookshelf` | `Lumen` / `data/Lumen` | `Lumitrace` / `data/Lumitrace` |
| Index file | `data/index/lifelog.sqlite` | `data/index/bookshelf.sqlite` | `data/index/lumen.sqlite` | `data/index/lumitrace.sqlite` |
| Commands | `lifelog-api`, `lifelog-indexer`, `lifelog-mcp`, `lifelog-gdrive-login` | `bookshelf-typewriter`, `bookshelf-bookmarks`, `bookshelf-reading-lamp`, `bookshelf-drive-login` | `lumen-prism`, `lumen-spectrum`, `lumen-lens`, `lumen-drive-login` | `lumitrace-prism`, `lumitrace-spectrum`, `lumitrace-lens`, `lumitrace-drive-login` |
| Docker services / volume | `api`, `indexer`, `mcp` / `lifelog-data` | `typewriter`, `bookmarks`, `reading-lamp` / `bookshelf-data` | `prism`, `spectrum`, `lens` / `lumen-data` | `prism`, `spectrum`, `lens` / `lumitrace-data` |
| Shortcuts | LifeLog Config, LifeLog Inbox, Send to LifeLog | Notepad Config, Notepad Inbox, Send to Bookshelf | Flash Config, Flash Inbox, Send to Lumen | Flash Config, Flash Inbox, Send to Lumitrace |
| OAuth scope / name in AI apps | `lifelog` / LifeLog | `bookshelf` / Bookshelf | `lumen` / Lumen | `lumitrace` / Lumitrace |

1. **`.env`:** rename every old-prefix variable to `LUMITRACE_` (for example
   `sed -i.bak -E 's/^(LIFELOG|BOOKSHELF|LUMEN)_/LUMITRACE_/' .env`). Unrenamed variables are silently
   ignored.
2. **Drive folder:** the default root folder is now `Lumitrace`. Either rename the existing
   `LifeLog`, `Bookshelf` or `Lumen` folder in Drive to `Lumitrace` (the app finds it again because
   it created it), or keep the old name with `LUMITRACE_GDRIVE_ROOT_FOLDER=Lumen` (or the older
   name). For local storage, move the old `data/` folder to `data/Lumitrace`, or set
   `LUMITRACE_LOCAL_ROOT`.
3. **Index:** move the old index file (`data/index/lifelog.sqlite`, `bookshelf.sqlite` or
   `lumen.sqlite`, plus `-wal`/`-shm`) to `data/index/lumitrace.sqlite`, or set
   `LUMITRACE_INDEX_PATH` to the old file, so `feedback` and `edit_signals` are kept. New backups go
   to `_system/index-backup/lumitrace.sqlite`.
4. **Docker:** services are now `prism`, `spectrum` and `lens`, and the volume is `lumitrace-data`.
   Run `docker compose down` *before* pulling the new compose file, then copy the old volume
   (`lifelog-data`, `bookshelf-data` or `lumen-data`) into `lumitrace-data`, or rebuild the index from storage.
   Compose prefixes volume names with the project (folder) name, so after the repository folder
   is renamed to `lumitrace` look for the old volume with `docker volume ls`.
5. **Commands:** the old commands (see the table) are now `lumitrace-prism`, `lumitrace-spectrum`,
   `lumitrace-lens` and `lumitrace-drive-login`. Update Claude Desktop / Cursor MCP configs
   (`docs/lens.md`).
6. **OAuth:** the scope is now `lumitrace` and AI apps list the connector as **Lumitrace**; run
   `lumitrace-lens reset-oauth` and reconnect each AI app.
7. **iPhone (Flash):** rename the helper shortcuts to **Flash Config** and **Send to Lumitrace**,
   and the Files folder iCloud Drive → Shortcuts → old inbox folder to **Flash Inbox**; then
   update the `Run Shortcut` step and the inbox paths in Log My Day, Quick Note and Send pending
   (`docs/flash.md`). Send pending first if the old inbox still holds captures. Log My Day,
   Quick Note and Send pending keep their names.
8. **Day files:** nothing to do. Files with the old `lifelog:`, `bookshelf:` or `lumen:` markers
   and `lifelog_format`, `bookshelf_format` or `lumen_format` key are still read, and are
   rewritten with the new names the next time the Prism writes that day.
9. **Lightsail and Tailscale (from Lumen):** the scripts now default to the instance
   `lumitrace`, `/opt/lumitrace` and the Tailscale name `lumitrace`. Lightsail cannot rename an
   instance, so create a new one (*Deploying on AWS Lightsail*), deploy, join Tailscale, then
   delete the old instance, its static IP and key pair, and remove the old machine in the
   Tailscale admin console. Update the address in Flash Config
   (`https://lumitrace.<tailnet>.ts.net`) and the AI-app connectors
   (`https://lumitrace.<tailnet>.ts.net:8443/mcp`), and set `LUMITRACE_MCP_PUBLIC_URL`
   (addresses as of decision 0044).
