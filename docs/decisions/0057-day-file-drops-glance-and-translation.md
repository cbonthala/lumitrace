# 0057. The day file has no At a glance section and no English translation

**Status:** accepted
**Date:** 2026-10-18

## Context

The journal model already reads the Telugu transcript (ADR 0048). The day file still kept an
English translation under each recording (ADR 0043) and an "At a glance" facts section
(ADR 0040, format 3 in ADR 0045). The owner does not want either in the file.

## Decision

Format 4 writes the title, the journal, My notes, and the Telugu transcript.

* `render` does not write `## At a glance` or a translation block.
* `parse` still reads both from older files. The next system write drops them.
* On a day that was not edited, that drop refreshes `generated_hash`, so it is not itself an edit.
* New captures do not store `Capture.translation`.
* `fill_day` and `update_day` ask for a headline and a journal only. Food, places, people,
  health, feelings and memories belong in the journal.

## Consequences

* Spectrum's fact tables and Lens `query_facts` stay filled only for days that still have the
  old section. After a rewrite they are empty. Search still covers the journal and the transcript.
* `lumitrace-prism regenerate` rewrites an unedited day into format 4, which removes the section.
* An edited day is still left alone by regenerate. The first Generate or 4:05 write uses
  `force=True`; later source is merged without rewriting existing journal words (ADR 0058).
