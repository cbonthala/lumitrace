# 0056. The journal covers the whole recording; Everyone meals are filled in code

- Status: accepted
- Date: 2026-10-18

## Context

A long recording's journal stopped before the last things said. The fill-day call already sent
the whole transcript. The prompt asked for about 60 to 300 words and did not require the ending.
The model call did not set an output-token ceiling, so a long JSON reply could stop at the
provider default. Day-level meals (`#### Everyone`) stayed empty because the JSON shape only
asks for meals under each person. An "I" item was also written as if someone else shared it.

## Decision

* `prompts/fill_day.md`, `prompts/update_day.md`, `prompts/day-template.md`, and the Telugu
  journal skill say: cover the transcript to its last sentence, and check the final third of
  each recording is in the journal or the facts. A short day stays near 60 to 300 words. A long
  recording may run longer.
* Give an item to a person only if the transcript names them or uses "we". "I drank coffee" is
  the author only.
* The journal call logs the character length of `{{captures}}`, the transcript length, whether
  every capture is present, and the model's maximum output tokens. Nothing is cut from the
  transcript before it is sent.
* The call sets `max_tokens` to that maximum (65536 for `gemini-3.8-flash` and the fallback).
  A reply that stops for length below that ceiling is retried once at the maximum.
* After the JSON is parsed, day-level meals are the union of every family member's meals. The
  same item is one line, tagged with who had it, in family order: `oatmeal (Maya, Leo)`. The
  model is not asked for this list. A reply with no per-person meals keeps a day-level list if
  the model returned one. A comma inside parentheses does not split a meal item, so the tag
  round-trips.

## Consequences

* Everyone meals and each person's meals both appear under Food. Search can list the same dish
  once per person and once on the Everyone row.
* A day regenerated with these prompts can be longer than 300 words.
