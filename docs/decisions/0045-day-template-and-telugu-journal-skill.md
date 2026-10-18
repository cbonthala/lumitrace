# 0045. A topic-first day template and a skill for filling it from Telugu transcripts

- Status: accepted
- Date: 2026-10-17
- `LUMITRACE_GLOSSARY` superseded by 0047 (`secrets/family.md`)

## Context

The day file groups facts by family member (`### Family` → `#### name`) and writes the journal
as Summary/Morning/Afternoon/Evening prose. It is hard to scan: you cannot see "what did
everyone eat" or "what do I want to remember" at a glance. A second agent that reads the
transcripts and journals (Oct 12 to 15) also found repeated errors: wrong who-did-what from the
machine translation, misheard words, mixed-up names, invented details (meals, visits, health),
deliveries counted as visits and dropped emotional moments.

## Decision

* New template `docs/templates/day-template.md`: topic first, one subsection per family member
  inside each topic (Highlight, Food by meal, Places visited, People we met or visited, Health
  and fitness, Feelings, Memories, Weather, Things we did, Audio and transcript with Telugu and
  English). Short bullets, `not mentioned` for gaps, `[uncertain: ...]` for doubt, and a
  `Remember:` line at the end of Highlight. It is implemented as day file
  format 3 (see Update below).
* New project skill `.cursor/skills/lumitrace-telugu-day-journal/` with the rules for filling it:
  the Telugu original wins over the machine translation (ADR 0018), newer recordings win over
  older ones, resolve relation words ("<child> Nanna" is the father speaking; "my Nanna" is his
  father), and the known error list above.
* Real names live in `glossary.local.md`, git-ignored (AGENTS.md rule 5); the repo has
  `glossary.example.md` with fictional names.

## Consequences

* Nothing changes at runtime yet. Making the Prism write this layout needs a new
  `FORMAT_VERSION`, `dayfile.py` parse/render changes, Spectrum/Lens updates and tests
  (`docs/frames-format.md` → *Changing the format*).
* New prompt versions `extract_facts-v5`, `write_journal-v4`, `journal_addendum-v4` carry the
  skill's rules (the server cannot read `.cursor/`, so the rules are copied into the prompts).
  The journal stays within the existing headings (Summary, Morning, ...) but is written as
  bullets with a final `**Remember:**` bullet. Per-member Food/Health/Feelings sections of the
  template still need format 3.
* New setting `LUMITRACE_GLOSSARY` (notes separated by `;`) is sent as `{{glossary}}` to all
  three prompts, so real names and known mishearings stay out of the repository.
* Dry-run the new versions on a real day (generate only, no writes) before deploying.
* Pipeline bugs from the same feedback (recordings lost on re-run, empty entries while
  rebuilding, newer recording not overriding older) are code issues, tracked separately.

## Update: format 3 is implemented

* `FORMAT_VERSION = 3`: `dayfile.py` renders and parses the topic-first layout; formats 1 and 2
  are still read and converted (`docs/frames-format.md` → Older formats). Empty values are
  `not mentioned`; Weather is `not looked up` until a lookup exists.
* Index `SCHEMA_VERSION = 3`: `meals.person`, `days.remember`, `family_facts` categories
  `feelings`/`health`/`moments` (`Together` for shared memories). Fact tables are dropped and
  recreated on rebuild; Spectrum rebuilds on its own when it sees the old version. Facts passages
  are one per section or person block ("Section · Person"). The Lens `query_facts` takes
  `person` for meals too.
* `extract_facts-v6` produces the new shape (`remember`, `memories`, per member `meals`,
  `health`, `feelings`, `moments`).
* Old days: a format 1/2 day cannot reproduce its old hash, so it looks edited. Redoing days
  (`lumitrace-prism regenerate`) treats a day as unedited when the file equals its snapshot;
  edited days only gain facts (additive merge). Chosen over rewriting every day blindly so the
  owner's edits are never lost.
* Per-member places and activities of format 2 become day-level places and things we did marked
  with the person's name `(Name)`.
