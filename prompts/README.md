# Prompts

AI prompts live here as plain, versioned files so every change is reviewed, diffable and
traceable to the journal entries it produced. They are the Prism's instructions. Code:
`lumitrace/prism/pipeline/prompts.py` (loading) and
`lumitrace/prism/pipeline/generate.py` (calling). Details: `docs/prism.md`.

## Layout

One file per task and version:

```
prompts/
  extract_facts/v3.md      facts for the day, incl. places and per family member facts
                           (validated against lumitrace.frames.dayfile.DayFacts); knows the
                           speaker, family relations and translations; v1, v2 are older
  write_journal/v2.md      {headline, journal} for the whole day; v1 is older
  journal_addendum/v2.md   {text}: a paragraph about a new entry, for days the owner edited;
                           v1 is older
```

* **Task** folders match the per-task model settings: `extract_facts` (uses
  `LUMITRACE_LLM_EXTRACT_FACTS_MODEL`), `write_journal` and `journal_addendum` (both use
  `LUMITRACE_LLM_WRITE_JOURNAL_MODEL`). All fall back to `LUMITRACE_LLM_FALLBACK_MODEL`.
* **Versions** are `v1`, `v2`, ... Never edit a released version in place: copy it to the next
  version, change the copy, and switch `PROMPT_VERSIONS` in
  `lumitrace/prism/pipeline/prompts.py` to it in the same commit.
* The **prompt version** recorded in each day file's front matter (`prompt_version`) joins the
  prompts used for that generation, e.g. `extract_facts-v1+write_journal-v1`; the activity
  records under `Lumitrace/_system/activity/` list them per task. That lets the weekly report
  compare quality across versions and lets old days be regenerated from their transcripts with a newer
  version.

## File format

```
<!-- lumitrace-prompt: system -->
Instructions for the model, including the exact JSON shape to return.
<!-- lumitrace-prompt: user -->
Date: {{date}}
...
{{captures}}
```

`{{name}}` placeholders are filled by the code; a placeholder without a value is an error, so the
prompt and the code cannot silently drift apart. Available values:

| Task | Placeholders |
|---|---|
| `extract_facts` | `date` (`2026-10-10 (Saturday)`), `author`, `family`, `location`, `captures` |
| `write_journal` | `date`, `author`, `family`, `facts` (JSON), `captures` |
| `journal_addendum` | `date`, `author`, `family`, `journal` (the edited page), `capture` (the new entry) |

`author` is the `LUMITRACE_FAMILY` member marked `(me)`, or `(not given)`. `family` lists every
member with their relation to the author: `Sam (the author), Maya (the author's wife), Leo`.

`captures` / `capture` are rendered as `### HH:MM · Log My Day (location: ...)` followed by the
transcript or note text. A recording with an English translation is shown as
`English translation (machine-made from the audio):` + the translation, then
`Original transcript (as spoken):` + the transcript.

## Rules

* No personal content in prompts or examples. Use fictional people and events.
* Prompts must ask the model to use only what is in the transcript and never invent facts
  (`tests/prism/test_prompts_llm.py` checks for "never invent/guess").
* `extract_facts` output must validate against `lumitrace.frames.dayfile.DayFacts`.
* Record why a prompt changed in `CHANGELOG.md` and, if it came from a learning, in
  `docs/learnings.md`.
