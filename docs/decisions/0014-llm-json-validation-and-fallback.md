# 0014. JSON replies validated per model, own fallback loop, `fake` model, prompt file format

- Status: accepted; the prompt-file layout is superseded by 0051
- Date: 2026-10-10

## Context

Fact extraction must produce `DayFacts`, and the journal step a headline plus Markdown. Providers
differ in how well they follow "reply with JSON"; LiteLLM's built-in `fallbacks` only react to
provider errors, not to a reply that fails validation. The pipeline must also run fully offline.

## Decision

* Every AI call asks for `response_format={"type": "json_object"}` with `drop_params=True`, parses
  the reply tolerantly (code fences, text around the object) and validates it with pydantic.
* Our own loop tries the task model, then `LIFELOG_LLM_FALLBACK_MODEL`; a provider error, invalid
  JSON or failed validation all move on to the next model. The model that answered is what goes
  into `models_used` and the activity record; each failed attempt is recorded.
* The model string `fake` returns deterministic output without calling a provider.
* Prompt files are `prompts/<task>/<version>.md` with `<!-- lifelog-prompt: system -->` and
  `<!-- lifelog-prompt: user -->` parts and `{{name}}` placeholders; current versions live in
  `PROMPT_VERSIONS`. `prompt_version` in front matter joins the labels of the prompts used, e.g.
  `extract_facts-v1+write_journal-v1`. Edited days use a third task, `journal_addendum`.

## Consequences

* Switching to a model that struggles with JSON degrades to the fallback model instead of losing
  the journal; the activity records show how often that happens.
* Both the system and the user message are versioned, so a prompt diff shows everything the model
  saw except the transcripts.
* `fake` is a reserved model name.
