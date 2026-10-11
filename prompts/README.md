# Prompts

AI prompts live here as plain, versioned files so every change is reviewed, diffable and
traceable to the journal entries it produced. The recording API adds the actual prompts.

## Layout

One file per task and version:

```
prompts/
  extract_facts/v1.md
  write_journal/v1.md
  ...
```

* **Task** folders match the per-task model settings: `extract_facts` (uses
  `LIFELOG_LLM_EXTRACT_FACTS_MODEL`) and `write_journal` (uses `LIFELOG_LLM_WRITE_JOURNAL_MODEL`).
* **Versions** are `v1`, `v2`, ... Never edit a released version in place: copy it to the next
  version, change the copy, and switch the code to it in the same commit.
* The **prompt version** recorded in each day file's front matter (`prompt_version`) and in the
  activity records under `LifeLog/_system/` identifies the set of prompts used, e.g.
  `extract_facts-v1+write_journal-v1`. That lets the weekly report compare quality across
  versions and lets old days be regenerated from their transcripts with a newer version.

## Rules

* No personal content in prompts or examples. Use fictional people and events.
* Prompts must ask the model to use only what is in the transcript and never invent facts.
* `extract_facts` output must validate against `lifelog.dayfile.DayFacts`.
* Record why a prompt changed in `CHANGELOG.md` and, if it came from a learning, in
  `docs/learnings.md`.
