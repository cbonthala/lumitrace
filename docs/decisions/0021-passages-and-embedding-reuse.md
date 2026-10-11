# 0021. Passages by section and heading, with embedding reuse

- Status: accepted
- Date: 2026-10-10

## Context

Search needs chunks small enough to point at the right part of a day, but with enough context to
make sense on their own. Days grow during the day (several quick notes), and re-embedding the
whole day on each capture would waste API calls.

## Decision

- Passages follow the day-file structure: one `title`, a `facts` passage (front-matter facts as
  plain text, so people/foods/activities are also found by keyword and meaning search), `journal`
  and `notes` split at Markdown headings, and `transcript` per capture (`capture_id` set).
- At most 1,000 characters per passage; cut at paragraph, then sentence, then word boundaries.
  No overlap.
- Embed `heading + "\n" + text`; `text_hash` is the sha256 of that input. When a day is
  re-indexed, vectors with an unchanged hash are copied over; only new text is embedded.
- New passages from up to 16 files are embedded together (`embed_texts` batches by 64).

## Consequences

- Adding a quick note embeds only the new note's passages (and the changed facts/journal).
- Passage ids change whenever a day is re-indexed; nothing should store them long-term.
- Changing the splitting rules only needs a rebuild.
