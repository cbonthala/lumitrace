# Prompts

AI prompts live here as plain, versioned files so every change is reviewed, diffable and
traceable to the journal entries it produced. They are the Prism's instructions. Code:
`lumitrace/prism/pipeline/prompts.py` (loading) and
`lumitrace/prism/pipeline/generate.py` (calling). Details: `docs/prism.md`.

## Layout

One file per task and version:

```
prompts/
  extract_facts/v2.md      facts for the day, incl. places and per family member facts
                           (validated against lumitrace.frames.dayfile.DayFacts); v1.md is the
                           previous version
  write_journal/v1.md      {headline, journal} for the whole day
  journal_addendum/v1.md   {text}: a paragraph about a new entry, for days the owner edited
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
| `extract_facts` | `date` (`2026-10-10 (Saturday)`), `family` (`LUMITRACE_FAMILY`, comma-separated; v2), `location`, `captures` |
| `write_journal` | `date`, `facts` (JSON), `captures` |
| `journal_addendum` | `date`, `journal` (the edited page), `capture` (the new entry) |

`captures` / `capture` are rendered as `### HH:MM · Log My Day (location: ...)` followed by the
transcript or note text.

## Rules

* No personal content in prompts or examples. Use fictional people and events.
* Prompts must ask the model to use only what is in the transcript and never invent facts
  (`tests/prism/test_prompts_llm.py` checks for "never invent/guess").
* `extract_facts` output must validate against `lumitrace.frames.dayfile.DayFacts`.
* Record why a prompt changed in `CHANGELOG.md` and, if it came from a learning, in
  `docs/learnings.md`.
