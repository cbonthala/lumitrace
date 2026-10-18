# Prompts

Everything Gemini sees, besides the day's transcripts and `secrets/family.md`, lives in this
folder. Edit the file. Git keeps the history. Code: `lumitrace/prism/pipeline/prompts.py`
(loading) and `lumitrace/prism/pipeline/generate.py` (calling). Details: `docs/prism.md`.

## Layout

```
prompts/
  fill_day.md        the 4:05 a.m. write: facts plus the journal
  update_day.md      a recording that arrives after that write
  day-template.md    the day-file shape, pasted into the fill_day user message
```

* Both tasks use `LUMITRACE_LLM_WRITE_JOURNAL_MODEL`, then `LUMITRACE_LLM_FALLBACK_MODEL`.
* One file per task. Change the wording in place. The day file's `prompt_version` stores the
  task name (`fill_day` or `update_day`). Older day files may still say `fill_day-v1`.
* `secrets/family.md` is the owner's names and notes. It is filled into `{{author}}`,
  `{{family}}` and `{{glossary}}` at send time. It does not live in this folder.

## File format

`fill_day.md` and `update_day.md`:

```
<!-- lumitrace-prompt: system -->
Instructions for the model, including the exact JSON shape to return.
<!-- lumitrace-prompt: user -->
Date: {{date}}
...
{{captures}}
```

`day-template.md` is plain Markdown. It has no system or user part. The fill-day prompt pastes
it in whole as `{{template}}`.

`{{name}}` placeholders are filled by the code; a placeholder without a value is an error, so the
prompt and the code cannot silently drift apart. Available values:

| Task | Placeholders |
|---|---|
| `fill_day` | `date` (`2026-10-10 (Saturday)`), `author`, `family`, `glossary`, `keyterms`, `template`, `captures` |
| `update_day` | `date`, `author`, `family`, `glossary`, `keyterms`, `journal`, `facts` (JSON already on the page), `capture` |

`author` is the `secrets/family.md` member whose relation is `me`, or `(not given)`. `family`
lists every member with their relation to the author, and a birth date when the file has one:
`Sam (the author), Maya (the author's wife, born 1990-04-12), Leo`. `glossary` is the Markdown
under that file's front matter, or `(none)`.

`captures` / `capture` are rendered as `### HH:MM · Log My Day (location: ...)` followed by the
transcript or note text. There is no English translation. `keyterms` is the speech-to-text list
(family names, then `LUMITRACE_STT_KEYTERMS`), or `(none)`.

## Rules

* No personal content in prompts or examples. Use fictional people and events.
* Prompts must ask the model to use only what is in the transcript and never invent facts
  (`tests/prism/test_prompts_llm.py` checks for "never invent/guess").
* Fact lists in both replies must validate against `lumitrace.frames.dayfile.DayFacts`.
* Record why a prompt changed in `CHANGELOG.md` and, if it came from a learning, in
  `docs/learnings.md`.
