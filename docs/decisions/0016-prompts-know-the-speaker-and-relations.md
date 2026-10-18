# 0016. Prompts know the speaker and family relations, and read translation and original together

- Status: accepted (the journal no longer reads a translation; ADR 0048)
- Date: 2026-10-12
- Family list source superseded by 0047 (`secrets/family.md`, not `LUMITRACE_FAMILY`)

## Context

On a real Telugu recording, `extract_facts-v2` and `write_journal-v1` got most facts wrong:
the cheaper model made a dish out of a misheard phrase, the journal model trusted those facts,
actions the owner's wife did ("took our daughter to the park") became the owner's, and the
child's "Dad" was not understood as the owner. The prompts did not say who was speaking, how
family members are related, or that the input may be another language; v2 also told the model
never to put the author in `family`, while the owner was listed in `LUMITRACE_FAMILY`, so the
owner's block was always empty.

## Decision

* `LUMITRACE_FAMILY` entries may carry a relation in parentheses, and `(me)` (or `(self)`)
  marks the owner: `Sam (me), Maya (wife), Leo (son)`. Free text, so any relation works
  (elder sister, mother-in-law, ...). Plain names still work. One setting instead of a separate
  owner setting, so the owner's name and family block are configured in one place.
* New prompt versions `extract_facts-v3`, `write_journal-v2`, `journal_addendum-v2` get
  `{{author}}` and `{{family}}` (`Sam (the author), Maya (the author's wife), Leo`) and tell the
  model to:
  * give every action, meal, place and feeling to the person who did it; "we" is the author
    plus whoever it clearly includes;
  * resolve relationship words in any language from the point of view of whoever says them;
  * read the "English translation" for meaning and the "Original transcript" for names, drop
    details the two disagree on, and never turn a misheard phrase into a food, place or name;
  * put the author's own facts in their family block;
  * (journal) treat the extracted facts as possibly wrong and follow the entries, and use
    Morning/Afternoon/Evening only for events the entries place there.
* Captures with a translation are shown to the model as the translation first, then the
  original.

## Consequences

* Without `(me)` the prompts say the author is "(not given)"; facts still work but who-did-what
  is weaker. The runbook and `.env.example` tell the owner to add relations.
* The relation is sent to the AI provider with every request, like the names already were.
* Older days keep their `prompt_version`; regenerating them uses the new versions.
