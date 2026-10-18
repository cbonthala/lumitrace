# 0058. My notes feed generation; later input merges into journal sections

- Status: accepted
- Date: 2026-10-18

## Context

Recordings accumulate through the day and the 4:05 a.m. run, or Generate in Flash, writes the
journal. The owner also adds source material in My notes. Generate previously ignored My notes
and deliberately rewrote the title and journal, including manual corrections. A later recording
was appended under a separate `## Later` section.

The owner wants My notes treated as input and every correction made after the first generation
to remain authoritative. New material should go into Summary, Morning, Afternoon, Evening or
Thoughts instead of a Later section.

## Decision

* The first generation sends every recording and the current My notes to `fill_day`. My notes are
  direct owner input and win when they correct a recording.
* `generated_source_hash` records the recordings and My notes already processed. Generate with
  no source change returns `unchanged` and makes no model call.
* Once `generated_at` exists, changed source material uses `update_day`. The model sees the
  current journal, every recording and My notes, and returns only missing bullets classified as
  Summary, Morning, Afternoon, Evening or Thoughts.
* Code inserts those bullets into the requested sections. It never asks the model to return a
  replacement journal and never changes existing journal words. A missing section is inserted
  in the normal order. No Later section is created.
* A recording after an early Generate remains deferred until 4:05, but that run is a safe update
  rather than a full rewrite. A closed-day recording updates immediately.
* Editing My notes does not itself call a model while the owner may still be typing. Generate, or
  the next recording, processes the changed notes.
* Capture replays use the source hash: an already-processed capture is `unchanged`; a capture
  saved before a crash but not incorporated is processed once. Regeneration trusts the format-4
  generated hash even when the live file equals the refreshed snapshot.

## Consequences

* Manual title and journal corrections survive Generate, 4:05, capture retries and later
  recordings.
* Updates are additive at the bullet level. A correction to generated prose is made directly in
  the journal; automation will not delete or paraphrase existing words.
* Older files without `generated_source_hash` get one safe update the next time their source is
  processed. The prompt compares all source material with the current journal to avoid repeats.

Supersedes ADR 0055's destructive Generate behavior and ADR 0050's `## Later` placement.
