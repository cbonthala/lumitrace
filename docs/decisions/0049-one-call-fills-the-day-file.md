# 0049. One Gemini call fills the day file

- Status: accepted; the edited-day half is superseded by 0050; the `fill_day-v1` label is superseded by 0051
- Date: 2026-10-17

## Context

Transcription is one Sarvam job (ADR 0048). After that, the Prism called two models: one to
extract facts and one to write the journal. The owner wants a single model to see the Telugu
transcript, the day-file template, and the rules, then fill the whole day: food, places, and
the journal.

## Decision

* An unedited day is filled by one call, `fill_day` v1. The prompt includes the transcript
  (no English translation), `{{glossary}}`, `{{keyterms}}`, and the text of
  `docs/templates/day-template.md`. The reply is JSON `{headline, journal, facts}`.
  `apply_generation` writes the day file. The model does not write the Markdown itself.
* The model is `LUMITRACE_LLM_WRITE_JOURNAL_MODEL`, set to `gemini/gemini-3.8-flash`
  (LiteLLM string `gemini/gemini-3.8-flash`, key `GEMINI_API_KEY`).
  `LUMITRACE_LLM_FALLBACK_MODEL` is still used when that call errors or times out.
* A day the owner edited is not rewritten. It still gets `extract_facts` on the new entry
  and `journal_addendum`, using `LUMITRACE_LLM_EXTRACT_FACTS_MODEL` and the journal model.
  Both are set to the same Gemini model.

## Consequences

* One model call per unedited day, instead of two.
* The day file's `prompt_version` for that path is `fill_day-v1`.
* Gemini has to read Telugu. A failed call falls back to `LUMITRACE_LLM_FALLBACK_MODEL`.
