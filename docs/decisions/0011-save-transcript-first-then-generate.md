# 0011. Save the transcript first, generate second, re-check edits before writing

- Status: accepted; the edited-day branch is superseded by 0046 and 0050
- Date: 2026-10-10

## Context

The AI steps are the slowest and least reliable part of a capture, and the owner may be editing
the same day in Obsidian while they run. Rule 2 says never overwrite the owner's edits, and rule 3
says keep the raw transcript.

## Decision

* Transcription runs before anything is written; if it fails the capture is retried from the
  inbox with nothing half-written.
* Audio, photos and the day file with the new transcript block are written next (with the
  `_system/generated/` snapshot). The capture is safe from this point even if every AI model
  fails.
* The AI steps then run in one of two modes, chosen from `DayFile.is_user_edited()`:
  * **full**: facts and journal for the whole day from all transcripts, `apply_generation`.
  * **additive**: facts from the new capture only and a short `journal_addendum` paragraph,
    `merge_generation_additive`. Facts, title and journal the owner edited are never changed.
* Just before writing, the day file is read again and the capture merged into the fresh copy. If
  a full result is about to be applied but the day is now edited, the result is discarded and the
  additive path runs instead (at most once more).

## Consequences

* Two writes per capture (transcript, then generation), two snapshots, one nudge.
* Once a day is edited, later captures only add to it; to get a fully regenerated journal the
  owner must undo their edits (or a future "regenerate" command with `force=True`).
* A small window remains between the second read and the write (milliseconds); Obsidian edits in
  that window could be lost. Storage has no compare-and-swap, so this is accepted.
