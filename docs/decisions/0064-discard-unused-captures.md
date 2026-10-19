# 0064. Flash can discard a capture the journal has not used

- Status: accepted
- Date: 2026-10-19

## Context

A recording can land on the wrong day, or be a take the owner does not want, before Generate
(or 4:05 a.m.) writes the journal. History showed those rows as **Not in journal** with no way
to remove them. Deleting only the audio would leave the transcript as source; deleting after
the journal has used the take would leave stale facts unless Generate ran again.

## Decision

* `DELETE /captures/{id}` removes a **done** capture that is **not in the journal** (the same
  test History uses: not `full` / `update` / `unchanged`).
* It deletes the audio and photos, the transcript block in the day file, the status record, and
  any leftover inbox folder. If that was the day's only unused material and no journal exists,
  the day file and generated snapshot go too. Spectrum is nudged with the paths that changed.
* A capture already in the journal is `409`. History shows a trash control only on unused rows.

## Consequences

* There is no move-to-another-day yet. File under the right day on Send, or discard and record
  again.
* Not yet checked on a real iPhone Home Screen or with Drive trash.
