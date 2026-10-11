# 0033. Where MCP tools read from, and how feedback is written

- Status: accepted
- Date: 2026-10-10

## Context

The index is disposable and may be mid-rebuild or missing; the day files are the source of
truth but slower to read (Drive). Feedback is a signal that must survive index rebuilds.

## Decision

* `search`, `query_facts` and `on_this_day` read the index; `get_day` reads the day file from
  storage (complete, always current, works before the first index build) and asks storage for
  share links.
* Every tool call opens a fresh read-only SQLite connection, so the indexer can sync, rebuild
  or replace the file at any time without the MCP server holding stale handles.
* A missing, unreadable or schema-less index gives empty results with a `note` the AI client
  can relay, not an error. A dimension mismatch is an error asking for a rebuild.
* `feedback` writes the JSON copy under `_system/feedback/` first (the durable record, in the
  owner's storage) and then the `feedback` row (creating the index if needed). Either write may
  fail without losing the other.

## Consequences

* `get_day` costs a Drive read per call (fine for one owner).
* The MCP server needs storage credentials as well as the index file.
* Feedback is kept twice; the weekly report can use either.
