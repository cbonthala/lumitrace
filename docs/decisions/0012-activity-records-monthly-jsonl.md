# 0012. Activity records as monthly JSONL without content

- Status: accepted
- Date: 2026-10-10

## Context

The self-improvement loop needs, per capture, the models and prompt versions used, the time and
cost of each step, and the errors. The foundation docs sketched one JSON file per run under
`_system/runs/`. A weekly report has to read all of them, and on Google Drive every file is a
separate API call.

## Decision

* One JSON line per processing attempt in `_system/activity/YYYY/MM.jsonl` (month of the attempt,
  UTC), including failed attempts. Fields: capture id, kind, attempt, status, entry date, times,
  generation mode, prompt versions, models, steps (name, ms, ok, model, cost, error, detail),
  total cost, errors, warnings.
* Never any journal content: no transcript, notes, facts, journal, names, places or file
  contents. Errors pass through `safe_error`, which drops the messages of validation and JSON
  errors (they echo model output) and truncates the rest.
* Appending is a read-modify-write of the month file under a process lock; a failed write is
  logged and never fails a capture.

## Consequences

* A month is one file to download for the weekly report; a busy month is well under 1 MB.
* Read-modify-write is only safe with a single writer (the API). Another writer would need its
  own file.
* `docs/contracts.md` and `docs/architecture.md` were updated to `_system/activity/` in the 0.1.0
  integration pass.
