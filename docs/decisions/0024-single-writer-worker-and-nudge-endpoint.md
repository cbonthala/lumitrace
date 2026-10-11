# 0024. One worker thread, FastAPI nudge endpoint, no auth on the internal port

- Status: accepted
- Date: 2026-10-10

## Context

`run` must poll, answer `POST /nudge` immediately (`202`), and back up daily. SQLite allows one
writer at a time, and the nudge must never make the recording API wait.

## Decision

- One worker thread owns the index connection and does all index work in cycles: nudged paths,
  sync (daily full scan), backup if due. HTTP handlers only queue paths and wake it.
- After waking, wait one second so a burst of writes (day file, snapshot, activity record) is one
  cycle.
- FastAPI + uvicorn (already dependencies) for `/nudge` and `/health`.
- No authentication: the port is internal to Docker (`expose`), and a nudge can only make the
  indexer re-read storage sooner.

## Consequences

- No writer contention inside the indexer; the MCP server's feedback writes wait at most one
  day-file transaction.
- Port 8001 must not be published to the internet. If that ever changes, add a token check.
