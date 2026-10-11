# 0003. SQLite + FTS5 + sqlite-vec index

- Status: accepted
- Date: 2026-10-10

## Context

Questions need exact facts ("what did I eat on Tuesday"), keyword search and meaning search over
about 10 MB of text per year. One person, one server.

## Decision

A single SQLite file: relational fact tables, an FTS5 table for keywords and a sqlite-vec `vec0`
table for embeddings (`docs/index-schema.md`). No separate database or vector service.

## Consequences

- Zero extra infrastructure; trivially backed up (copied to Drive daily) and rebuilt.
- The Python build must allow loading SQLite extensions (true for the official Docker image and
  uv-managed Python; verified by `tests/index/test_schema.py`).
- Changing the embedding model or dimension requires a rebuild; `connect` refuses a mismatch.
- Two processes write (indexer, MCP feedback), so WAL mode and a busy timeout are required.
