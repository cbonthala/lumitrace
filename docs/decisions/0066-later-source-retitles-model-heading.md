# 0066. Later source may retitle a model-owned heading

- Status: accepted
- Date: 2026-10-19

## Context

The first `fill_day` writes `# Saturday, October 10, 2026 · Taco day`. A later recording can
change the highlight, timeline and trackers, but `_apply` only set the title on `mode == "full"`.
`update_day` did not return a headline. Generate at lunch, then an evening birthday dinner, left
the heading on Taco day.

The snapshot cannot be the previous model title: every Prism write copies the live file over it,
including an owner-edited heading after `merge_capture`.

## Decision

* `fill_day` and `update_day` both return `headline`, the memorable part after the weekday date,
  from every recording and My notes.
* Code composes `default_title(date) · headline` and applies it only when the live title still
  equals the last title the model wrote (`GeneratedFactsState.title`). An owner-edited heading
  stays. Older generated-facts files without `title` keep the live heading when the day is
  already edited, and retitle when the whole page is still model-owned.
* Notes, transcripts, audio and photos are unchanged. Owner timeline, tracker and tag edits still
  win the three-way merge.

## Consequences

* A later Generate or 4:05 run can rename a day the model still owns.
* A heading typed in Obsidian is kept even when later recordings rewrite model trackers.
* Regenerating an unedited legacy day may replace its old headline; that matches the first-write
  rule.

Related: [0061](0061-format-6-family-day-files.md).
