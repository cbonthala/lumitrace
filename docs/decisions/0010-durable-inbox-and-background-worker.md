# 0010. Durable inbox in storage, one background worker, client capture ids

- Status: accepted
- Date: 2026-10-10

## Context

Transcribing and writing a journal takes 10–60 seconds. An iPhone Shortcut waiting that long on
"Get Contents of URL" is fragile (screen locks, network changes), and if the server restarts in
the middle the recording must not be lost. The phone may also send the same capture twice: the
offline "Send pending" Shortcut cannot know whether an earlier attempt reached the server.

## Decision

* The API writes the raw upload to `_system/inbox/<capture_id>/` in the configured storage, with
  `manifest.json` written last, plus a status file `_system/captures/<capture_id>.json`, and only
  then answers `202 Accepted`.
* One worker thread processes captures sequentially. Failures retry automatically (60 s, 10 min),
  then stay `failed` in the inbox until retried or re-sent. On start-up the inbox is re-queued.
* The client may send a `capture_id`. A known id that has not failed is not stored again (`200`,
  `duplicate: true`); `merge_capture` is idempotent on the same id, so the day file can never get
  the same entry twice.
* Status files are kept after processing; the inbox folder is deleted.

## Consequences

* Uploads survive restarts and server loss (they are in Drive, not on the container's disk).
* With Google Drive, the `202` waits for the raw files to upload to Drive. A local-disk inbox
  would answer faster but needs a new setting and is lost with the server; revisit if responses
  get slow.
* Sequential processing means a capture waits behind earlier ones; fine for one person, and it
  removes any race on the day file between two captures.
* `_system/captures/` grows by one small file per capture (a few hundred a year).
