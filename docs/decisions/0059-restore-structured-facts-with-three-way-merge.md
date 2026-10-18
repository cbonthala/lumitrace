# 0059. Restore structured facts with an owner-safe three-way merge

- Status: accepted
- Date: 2026-10-18

## Context

ADR 0057 removed the At a glance region because the journal already covered the same topics.
That also removed the structured source for Spectrum's meals, places, people, activities and
family tables. Lens could still search prose, but precise questions such as what one person ate
on one day returned no rows. Rebuilding a day made this worse by deleting facts that an older
file still had.

ADR 0058 protects journal corrections by asking the model only for missing journal bullets and
inserting them mechanically. Structured facts need different behavior: later source can correct
or remove a model fact, while an owner may also add, change or delete a fact in Obsidian.

## Decision

* Format 5 restores the structured `## At a glance` region. English translations remain absent.
* `fill_day` returns a complete journal and complete `DayFacts`. `update_day` returns missing
  journal bullets and a complete `DayFacts` candidate from every recording plus My notes.
* The Prism stores the model's complete facts under
  `_system/generated-facts/YYYY/MM/YYYY-MM-DD.json`. This is the merge base. The existing
  `_system/generated/` file remains an exact copy of the last live day-file write for Spectrum's
  edit signals.
* Later facts use a three-way merge: previous model facts (base), live day-file facts (current)
  and the new model reply (incoming). An untouched value follows the incoming reply. Owner
  additions, changes and removals win conflicts.
* Journal updates keep ADR 0058's additive section merge. Notes and transcripts are never
  rewritten.
* Generate returns `unchanged` only when the source hash and generated-facts base both match.
  A format-4 day has no base, so its next Generate repairs structured facts even when its source
  did not change. A genuinely fact-free day stores an empty base and does not rerun forever.
* On the first update of an edited legacy day with no base, facts merge additively. This cannot
  delete an owner fact. The incoming complete reply then becomes the base for later three-way
  merges.
* `lumitrace-prism regenerate` calls the same `generate_day` path as the Flash Generate button.
  It does not skip an edited day and does not replace an existing journal. A dry run reports
  the same mode (`would full` or `would update`) without calling the model.

## Consequences

* Spectrum and Lens receive structured facts from every newly generated or repaired day.
* Clicking Generate, or running `lumitrace-prism regenerate`, repairs format-4 days without
  replacing their title, journal, notes or transcript.
* Bulk regenerate no longer has a separate skip-edited or force-rewrite path. ADRs 0045, 0050
  and 0055 described that older path.
* One additional small JSON file per generated day is kept in the owner's storage.
* A model reply without a `facts` object fails validation instead of silently saving only the
  journal.

Supersedes ADR 0057 only for removal of At a glance. Its no-translation decision remains.
