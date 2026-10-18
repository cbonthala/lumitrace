# 0055. Generate the journal from Flash before 4:05 a.m.

- Status: accepted
- Date: 2026-10-18
- Superseded in part by: 0058 (Generate no longer rewrites existing words)

## Context

ADR 0046 saves transcripts through the day and writes the journal once, at 4:05 a.m. The owner
wants that same write on demand: every recording filed under a day, written up now, without
waiting for the rollover.

## Decision

* Flash History groups captures by the day they are filed under. Each day has a **Generate**
  button. `POST /journal` with that date (or none, for the open day) waits until the capture
  worker is idle, then runs one `fill_day` on every transcript. `apply_generation` uses
  `force=True`, so edits to the facts, title or journal do not block it and are replaced.
  Notes and transcripts stay. The model is not shown the page as it stands. The reply is a
  status and a short message, never the journal text.
* A day with no words is `skipped`. A failed model call is `failed` and keeps the due marker.
  A date after today is refused.
* Recordings that arrive after Generate, while the day is still open, stay deferred. If any
  do, the 4:05 run writes the day again from every transcript, not as an update of only the
  latest clip. If nothing new arrived, the marker is already clear and 4:05 does nothing.
* A capture for a day that has already closed still updates from that capture only (ADR 0050).

## Consequences

* Generate rewrites the facts, title and journal from the transcripts, whether or not those
  were edited. `lumitrace-prism regenerate` still skips a day you edited. The button asks
  before it runs.
* Clicking Generate, then recording more before 4:05, means the morning run replaces the
  journal again so the later recordings are included.
* One model call per click, and another at 4:05 only when more transcripts arrived.
