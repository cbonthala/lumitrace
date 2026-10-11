# 0020. Incremental sync: change feed, hashes, retries and a daily full scan

- Status: accepted
- Date: 2026-10-10

## Context

The indexer must keep the index in step with Google Drive cheaply (Drive downloads are slow and
rate-limited), never lose an update, and never stop because one file is broken. The Drive change
feed is efficient but can lag a few seconds and, after a restart, can miss deletions of files it
never saw.

## Decision

- Use `storage.list_changes(meta.sync_token)` for incremental syncs; store the new token after
  each sync.
- Skip unchanged files in two steps: equal modification time → don't download; equal sha256 →
  don't re-index.
- Index only canonical day files; read generated snapshots only for edit signals; never download
  audio, photos or other files.
- One transaction per day file, so readers see a whole old or whole new day.
- Malformed files: warn (path and error type only), record the hash, keep the last good index.
  Transient errors: remember the path in `meta.indexer_retry_paths` and retry next sync, while
  still advancing the token.
- Nudged paths are indexed directly (stat + read), not via the change feed.
- `run` does a full scan (`list_changes(None)`) once a day and drops index entries for day files
  that no longer exist. A token storage rejects also falls back to a full scan.

## Consequences

- A normal poll costs one change-feed call; a new capture costs one or two downloads.
- One broken or unreachable file never blocks the rest, and is retried without a storage change.
- Missed deletions or changes are repaired within 24 hours.
- Three new `meta` keys (`indexer_retry_paths`, `last_full_scan_at`, `last_backup_at`); no schema
  change.
