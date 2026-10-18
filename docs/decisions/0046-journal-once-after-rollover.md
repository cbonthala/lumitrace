# 0046. Write the journal once, five minutes after the day closes

- Status: accepted
- Date: 2026-10-17

## Context

Each short recording rewrote the whole day's facts and journal. A day with several clips paid
for a new journal every time, and the page kept changing until the last clip. The day already
closes at `LUMITRACE_DAY_ROLLOVER_HOUR` (4 a.m.): a recording at 3:30 a.m. still belongs to the
day before.

## Decision

* Saving a capture only transcribes it and appends it to the day file, while that day is still
  open. `generation` is `deferred`. A marker `_system/journal-due/YYYY-MM-DD.txt` records that
  the journal is still to be written.
* The Prism writes the facts, title and journal once, five minutes after the rollover (4:05
  a.m. when the rollover hour is 4), and again on startup for any closed day whose marker is
  still there (the server was off at 4:05). The run waits until the capture worker is idle, so
  a recording from just before 4 a.m. is included. One write sees every recording; a later
  recording still wins where they disagree.
* A capture whose day has already closed is written immediately. The morning run for that day
  has passed, and waiting until the next 4:05 would leave it out.
* The same edit rule as before: if the owner changed the facts, title or journal, the run only
  adds. The first save of a blank day stores a hash of that blank page, so an edit made before
  4:05 is visible. Words typed only in My notes do not count as an edit.
* A failed run leaves the marker. The next start tries again.

## Consequences

* Until 4:05 the day file has the transcripts and an empty journal. Highlight, Food and the
  journal appear with the morning run. Spectrum is nudged when the transcript is saved and
  again when the journal is written.
* `lumitrace/prism/journal_schedule.py` owns the clock. Tests pin the clock so a day in October
  2026 stays "already closed" or "still open" no matter when the suite runs.
