# 0047. Family members and prompt notes live in one file

- Status: accepted
- Date: 2026-10-17
- Supersedes the `LUMITRACE_FAMILY` setting in 0016 and the `LUMITRACE_GLOSSARY` setting in 0045

## Context

Who is in the family, how they are related, and the notes that stop the same translation
mistakes (sound-alike names, relation words, foods, places) were two environment variables:
a comma list and a semicolon string. Birth dates and usual routines do not fit in either.
The running server also cannot read `.cursor/`, so a glossary kept next to the journal skill
never reached the prompts. Keeping both meant the skill and the Prism could disagree.

## Decision

* One file, `secrets/family.md` (in Docker, `/secrets/family.md`). It is git-ignored with the
  rest of `secrets/`. There is no `LUMITRACE_FAMILY` or `LUMITRACE_GLOSSARY`.
* YAML front matter holds the family list: `name`, `relation` (`me` or `self` is the person
  who records), and optional `born` (`YYYY-MM-DD`). List order is the subsection order.
  The first spelling of a name wins.
* Markdown under the front matter is sent to the prompts as `{{glossary}}`. It is background
  for resolving words that were said. `extract_facts-v7`, `write_journal-v5` and
  `journal_addendum-v5` say not to write a meal, place, visit or activity for today because
  it is usual.
* `get_settings()` loads the file. `Settings()` used by tests does not, so real names in a
  checkout cannot leak into tests. A missing file means no family blocks and `(none)` for notes.
  A file that exists but is not valid YAML fails startup.
* The fictional copy committed in the repo is `docs/templates/family.example.md`. The journal
  skill reads `secrets/family.md`.
* Speech-to-text key terms still start with the names from this file, then
  `LUMITRACE_STT_KEYTERMS`.

## Consequences

* `.env` and `.env.production` no longer carry the family. Deploy uploads `secrets/`, which
  already includes this file.
* A birth date in the file is shown to the model (`born 1990-04-12`). It is not written into
  a day unless the transcript says it.
* Old prompt versions stay for days already generated. New generations use v7 and v5.
