# 0017. The sender can choose the day with a `date` query parameter

- Status: accepted
- Date: 2026-10-13

## Context

The day a capture belongs to was always worked out from `captured_at` (default: when the upload
arrives) in `LUMITRACE_TIMEZONE`, with captures before `LUMITRACE_DAY_ROLLOVER_HOUR` counting as
the previous day. The owner wants to say the day directly, for example to record about
yesterday or to send an old voice memo, without faking a capture time.

## Decision

* `POST /recordings` and `POST /notes` accept `?date=YYYY-MM-DD`. A query parameter (not a form
  field) so a Shortcut can set it in the URL whatever body type it sends.
* The date wins over `captured_at` for the day file, the audio name and the confirmation
  message. `captured_at` still sets the capture's time and id.
* Empty or missing `date` keeps the old rule (capture time in the configured timezone, with the
  rollover hour), so existing Shortcuts and the offline inbox are unchanged.
  `LUMITRACE_DAY_ROLLOVER_HOUR=0` makes the fallback the plain calendar date.
* The date is stored in the inbox manifest (`CaptureRequest.entry_date`), so automatic retries
  and restarts file the capture under the same day.
* A malformed date or one after today (in the configured timezone) is refused with `422`.

## Consequences

* A capture filed under an earlier day shows its real recording time in that day's file (e.g.
  a 21:30 time on a day it was not recorded).
* Manifests written before this change have no `entry_date` and keep working.
