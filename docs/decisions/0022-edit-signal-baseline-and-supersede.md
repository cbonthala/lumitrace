# 0022. Edit signals: snapshot baseline, same-generation rule, one row per baseline

- Status: accepted
- Date: 2026-10-10

## Context

Edit signals should capture what the owner corrected in the AI's output. The baseline is the
snapshot the recording API writes to `_system/generated/` with every day file. Pitfalls: the API
writes the day file and the snapshot one after the other, so the indexer can see a new day file
next to an old snapshot; Obsidian saves every few seconds while the owner types, so each sync
could see a different half-finished edit; rebuilds re-run the comparison.

## Decision

- Compare live file and snapshot only when their `generated_at` are equal (same system write).
- Compare field by field: each fact, title, journal, notes, and each transcript capture present
  in the snapshot (`field` = capture id). Captures only in the live file are not edits.
- Keep one row per (date, section, field, before): a newer edit of the same baseline replaces the
  older row, and reverting the edit deletes it. Rows with an older baseline are never touched.
- Dedupe with `signal_hash` + `INSERT OR IGNORE`, so re-indexing and rebuilds are idempotent.

## Consequences

- No false signals from the API's two-step write or from new captures.
- The table holds the owner's latest version of each correction, not every keystroke.
- If the owner edits `generated_at` by hand, that day produces no signals (acceptable).
- Edits made before snapshots existed (or on days without a snapshot) are not captured.
