# 0060. A later recording replaces model facts and corrects the journal

- Status: accepted
- Date: 2026-10-18

## Context

ADR 0059 keeps owner edits with a three-way merge, but the first update of an edited day that
has no saved model base appends the new facts onto the old ones. The same fact then appears
twice when the wording changes ("Sulemani chai" beside "Sulemani chai (spiced black tea)"), and
the day stays marked edited, so the next update treats the stacked lines as hand edits.

ADR 0058 never changes a journal sentence that is already on the page. A later recording that
corrects a generated sentence updates the facts and leaves the old sentence in the journal.

## Decision

* Facts from a later recording or from Generate are one complete list. The three-way merge
  still applies: a fact the owner added, changed or removed wins, and an untouched fact follows
  the new reply. The same fact is kept once. A parenthetical gloss or an `[uncertain: ...]`
  note does not make a second bullet; the incoming wording is the one kept.
* There is no append-only facts path. When no model base and no generated snapshot exist, the
  live facts are the base, so the complete reply replaces them.
* The saved model base (`_system/generated-facts/`) now includes the model journal. A snapshot
  stands in until that field exists. The snapshot is read before a new capture is saved, because
  that save copies the live file over the snapshot.
* When the live journal still matches that model journal, a changed recording, changed My notes,
  or `lumitrace-prism regenerate --replace-generated` rewrites the journal from every recording.
  A sentence the owner changed stays. On an edited journal, a replacement is applied only when
  the old sentence is still in the model journal, and a bullet that is already on the page is
  not inserted again.
* `activities.minutes` is a number only when that number was spoken. A range is not multiplied
  out. A first-person item stays with the author. A stated absence is a fact.
* `--replace-generated` runs the update even when the recordings are unchanged, so a prompt fix
  can rewrite model-owned text. It does not replace a journal the owner has edited.

## Consequences

* A new recording no longer stacks a second copy of a model fact, and a correction reaches a
  generated journal sentence.
* A line the owner added that is not the same fact as a model line stays.
* A line left behind by an older append, whose wording is not the same fact and which is not in
  the saved model base, still looks like a line the owner added. Deleting it once keeps it gone.
* Notes, transcripts, audio and photos are unchanged.

Supersedes ADR 0058's rule that existing journal words are never changed, and ADR 0059's
append-only first update of an edited day with no facts base. Owner edits still win conflicts.
