# 0040. Facts in the day file body, with a block per family member

- Status: accepted
- Date: 2026-10-11

## Context

Format 1 kept the facts (mood, people, meals, ...) in the YAML front matter. Obsidian shows that
as a collapsed property list, so the owner could not easily read or fix what the Prism found,
and there was no place for where the day happened or for what each family member ate, did or
went through. `family_events` were loose strings with no person attached, so questions like
"what did Leo eat this week?" could not be answered from the index.

The owner wants the day file to stay the single snapshot: the Prism turns the audio into all the
facts once, and Spectrum only copies what the file says, never re-deriving facts from text.

## Decision

- Format 2 moves the facts into an `## At a glance` section right under the title, inside
  `lumen:facts` markers: labelled lines for mood, city and weather, then `###` sections Food,
  Places, People, Activities, Family and Highlights. The front matter keeps only date, media
  and provenance. `generated_hash` covers the same facts as before plus `places` and `family`.
- Family has one `####` block per person with fixed labelled lines (Mood, Ate, Went to, Did,
  Moments, Health, School/work). Who counts as family is a config list (`LUMEN_FAMILY`); the
  Prism drops anyone else and spells names as configured, so blocks stay stable across days.
  `family_events` is removed; format 1 events are moved into Highlights.
- **Every day file has the same lines, with the same names, in the same order.** Search
  (Spectrum's vectors, read by the Lens) and the owner both rely on one fixed shape. Empty facts
  are written as `none` rather than left out, but the index never stores those lines. Every
  configured family member gets a block of all seven lines every day. Meal types are a fixed set
  of five (breakfast, lunch, dinner, snacks, drinks); synonyms are mapped and anything else
  counts as snacks. Generated journals only use `## Summary`, `Morning`, `Afternoon`,
  `Evening`, `Thoughts` and `Later`. Code enforces this (`normalize_journal`), not just the
  prompt. Other headings become bold lines so no words are lost. Additions to an edited day go
  under `## Later` with a bold time label instead of their own heading.
- Values are normalised (one line, no separator inside an item) so `parse(render(x)) == x`, and
  the parser tolerates hand edits; lines it cannot place move into My notes instead of being
  lost.
- Format 1 files are still read. An unedited format 1 day gets its hash re-stamped to the format
  2 hash, so the upgrade alone never marks a day as edited.
- The index gets `places` and `family_facts` (one row per item with `person` and `category`),
  `family_events` is dropped, and the schema version goes to 2; Spectrum rebuilds on its own when
  the stored schema version differs (like ADR 0023).

## Consequences

- The owner reads and edits facts as normal Markdown, and edits are protected by the same hash.
- `query_facts` can answer per-person questions (`kind="family"`, `person=...`) and place
  questions; `on_this_day` shows places and family.
- Changing the labels or headings is a format change: the parser accepts a few aliases, but the
  renderer's exact text is part of the contract (`docs/frames-format.md`).
- Family members not listed in `LUMEN_FAMILY` only appear in People and the journal. An empty
  setting means no family blocks.
- Upgrading costs one automatic index rebuild.
- Quiet days show many `none` lines; that is the price of an identical shape. Only system
  writes are made strict: the owner's own headings in an edited journal are left as they are,
  and hand-edited facts are rewritten to the standard lines on the next system write.
