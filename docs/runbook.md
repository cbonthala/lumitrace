# Runbook

Maintenance procedures. Each work stream fills in its own steps; keep commands copy-pasteable
and never paste real tokens or personal content here.

## Rotating tokens

* **Recording API token:** generate (`openssl rand -hex 32`), set `LIFELOG_API_TOKEN` in `.env`,
  restart `api` (`docker compose up -d api`), update the token in every iPhone Shortcut
  (Log My Day, Quick Note, Send pending).
* **MCP token / owner password:** set `LIFELOG_MCP_AUTH_TOKEN` or `LIFELOG_MCP_OWNER_PASSWORD`,
  restart `mcp`, reconnect the AI apps. *(mcp work stream: add OAuth client/session reset steps.)*
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
* `docker compose run --rm indexer lifelog-indexer rebuild`
* Keeps `feedback` and `edit_signals`. *(indexer work stream: add timings and verification.)*

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
* Activity records in `LifeLog/_system/runs/` show per-step errors, timing and cost.
