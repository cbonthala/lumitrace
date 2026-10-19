# 0061. Use one structured Format 6 family day file

- Status: accepted
- Date: 2026-10-18

## Context

Format 5 stores the same day in two generated shapes: an At a glance fact list for exact
queries and a separate journal for the story. That split cannot express the fuller family
template now used by the prompts: a chronological timeline, day context, per-person food,
health, routine, interests and growth trackers, pregnancy details and tags. It also makes a
correction cross two independently merged regions.

The owner must still be able to edit the Markdown directly. Older day files must stay readable,
and Spectrum and Lens still consume the Format 5 fact contract.

## Decision

* Format 6 has one generated `content` region, represented by
  `lumitrace.frames.daycontent.DayContent`. It contains the day timeline, context, family
  tracker tables, pregnancy and baby tracker, and tags. My notes and transcripts remain
  separate regions with their existing ownership rules.
* `daycontent.render` writes a canonical Markdown layout and `daycontent.parse` reads that
  layout. Empty values render as `—`; multiple values in a table cell use `<br>`.
* `fill_day` returns a headline and complete Format 6 content. `update_day` returns exact
  timeline additions, replacements and deletions plus the complete structured tracker state.
  Code applies timeline patches and validates all returned JSON before writing Markdown.
* Later generations use a three-way content merge: the previous model content is the base, the
  live day file is current, and the new model result is incoming. Owner scalar, list, row and
  table-cell edits win. The generated-facts JSON stores the model's Format 6 content as the
  merge base while retaining a Format 5 facts projection for compatibility.
* A Format 5 or older day is parsed without migration. It is conservatively projected into
  Format 6 only when generation needs content; a successful generation then writes Format 6.
  Merely parsing and rendering a legacy day keeps the Format 5 layout.
* `DayFile.facts` and `DayFile.journal` remain compatibility projections. Spectrum also indexes
  the canonical content as `content` passages and flattened `content_facts` rows while keeping
  the legacy fact tables. Lens `get_day` returns canonical content and the projections, and
  `query_facts` adds timeline, trackers, pregnancy, tags and all-content views.
* Format 6 edit signals compare the top-level timeline, family, pregnancy/baby and tags values.
  Legacy facts and journal keep their existing comparisons.

## Consequences

* The Markdown source of truth now matches the family day template and has one generated region
  to merge.
* Schema version 4 adds `content_facts`. Legacy tables stay populated from the compatibility
  projection, so old fact queries continue to work while new queries can use every Format 6
  field.
* Search sees canonical Format 6 Markdown. Edit signals are top-level content comparisons
  rather than one row per nested cell.
* Existing files and generated-facts JSON remain readable. Their first successful generation
  may reorganize legacy journal text under the conservative Format 6 projection before the new
  complete model result is merged.
* The canonical tables make direct editing predictable, but structural edits that break the
  expected headings or table shape are parse errors rather than free-form notes.

Supersedes ADR 0059's Format 5 layout and ADR 0060's separate facts-and-journal update model.
Their owner-edit and no-translation rules remain.
