# 0051. One prompt file per task

- Status: accepted
- Date: 2026-10-17

## Context

Prompt files were `prompts/<task>/v1.md`, `v2.md`, and so on. The day file stored
`prompt_version: fill_day-v1`. Git already keeps every edit to a file. The extra copies were
there so that label still opened the text that wrote an old day. The running program only
loads the current file (ADR 0050). The day template Gemini sees lived in
`docs/templates/day-template.md`, outside the prompt folder.

## Decision

* One file per task: `prompts/fill_day.md` and `prompts/update_day.md`. Edit the file in place.
* The day template moves to `prompts/day-template.md`. The fill-day call pastes that file in.
* A new day file stores `prompt_version: fill_day` or `update_day`. Older files keep whatever
  label they already have (`fill_day-v1`, `journal-v1`). Those old files are not loaded.
* Activity records no longer store a prompt version number.

## Consequences

* Changing the wording is an edit to one file. Git is the history.
* `prompt_version` on a new day names the task, not a revision of the text.
* Supersedes the versioned prompt paths in ADR 0014 and the `fill_day-v1` label in ADR 0049.
