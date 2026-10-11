# 0023. Automatic, in-place rebuild on embedding changes

- Status: accepted
- Date: 2026-10-10

## Context

Vectors from different embedding models (or dimensions) can't be compared, and the MCP server
embeds queries with the configured model. `connect` refuses a dimension mismatch; a model change
with the same dimension would silently give bad results. A rebuild costs one re-embedding of all
text (cents per year of journal).

## Decision

- When the configured model or dimension differs from `meta`, `sync` and `run` rebuild
  automatically (logged as a warning), so changing `.env` and restarting is enough.
- Rebuild in place: `reset_derived` (recreating `passages_vec` with the new dimension), then a
  full scan committed file by file. Don't build a second file and swap it.

## Consequences

- No manual step to forget after an embedding change; feedback and edit signals stay.
- While a rebuild runs, searches see a partial index (minutes for years of data).
- Swapping files was rejected: the MCP server holds the file open and writes feedback to it, so a
  swap could lose feedback or leave readers on a deleted file.
