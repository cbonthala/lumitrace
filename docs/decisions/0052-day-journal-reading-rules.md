# 0052. Day-journal reading rules

- Status: accepted
- Date: 2026-10-17

## Context

The fill-day prompt, the day template, and the Telugu journal skill disagreed on a few rules:
a bare "Nanna", what to do when a detail is unclear, and where weather comes from.

## Decision

`prompts/fill_day.md`, `prompts/day-template.md`, and
`.cursor/skills/lumitrace-telugu-day-journal/SKILL.md` use the same rules:

* A bare Nanna (నాన్న) means the author when the author is talking about their own child.
  Otherwise the item ends with `[uncertain: who is Nanna]`.
* Events stay in the order they were spoken. Reorder only when a time is stated.
* నిన్న or "yesterday" belongs to the previous date.
* A proper noun must appear in the transcript, keyterms, or glossary. Otherwise
  `[uncertain: name unclear]`.
* Weather is null unless a weather lookup is passed in as input.
* If you cannot tell what happened, drop it. If you can tell what happened but not a detail,
  keep it and end with `[uncertain: why]`.
* The journal may include `## Thoughts`. Meal types include drinks.

## Consequences

* The JSON shape is unchanged.
* A meal type of `drinks` is still stored as snacks until `MEAL_TYPES` includes drinks.
* `prompts/update_day.md` is unchanged.
