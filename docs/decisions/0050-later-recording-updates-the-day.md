# 0050. A later recording updates the day from that recording only

- Status: accepted
- Date: 2026-10-17

## Context

ADR 0046 stores transcripts during the day and writes the journal at 4:05 a.m. ADR 0049 fills
an unedited day with one `fill_day` call, but an edited day still ran `extract_facts` and
`journal_addendum`. The owner does not want that branch. A journal typed before 4:05 should
not block the morning write. A recording that arrives after the journal exists, even days
later, should add only what that recording says.

## Decision

* At 4:05 a.m., and for the first write of a day that is already closed, one `fill_day` call
  sees every transcript, the glossary, the keyterms, and the day template. `apply_generation`
  runs with `force=True`, so a journal typed before that run is replaced. Notes and
  transcripts stay.
* Once `generated_at` is set, a new recording is one `update_day` call. The model sees that
  recording plus the journal and facts already on the page. `merge_generation_additive`
  adds the new facts and appends the new lines under `## Later`. Owner edits stay. This does
  not depend on `is_user_edited()`.
* A replay of a capture id already in the file runs `fill_day` again, so a crash retry does
  not append a second Later block.
* `lumitrace-prism regenerate` still fills days that were not edited. An edited day is
  skipped, with no model call.
* The prompts `extract_facts`, `write_journal`, and `journal_addendum` are deleted.
  `LUMITRACE_LLM_EXTRACT_FACTS_MODEL` is removed. Both remaining tasks use
  `LUMITRACE_LLM_WRITE_JOURNAL_MODEL`.

## Consequences

* One model call per day at 4:05, and one more call per recording that arrives afterward.
* Words typed into the journal before 4:05 a.m. are replaced by the morning write.
* A day edited after the journal exists is never rewritten from scratch. `regenerate` leaves
  it alone.
* Old day files may still say `extract_facts-v7` in `prompt_version`. Those prompt files are
  not loaded at runtime.

Supersedes the edited-day half of ADR 0049.
