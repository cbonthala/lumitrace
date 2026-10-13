# 0043. A recording's English translation is stored under its transcript

- Status: accepted
- Date: 2026-10-12

## Context

With Sarvam (ADR 0015) a recording gets both a raw transcript (Telugu with English words) and
an English translation. The raw transcript must stay (Key rule 3), the translation should be
readable in Obsidian next to it, survive re-parsing, reach the AI steps, and be searchable in
English. Options: put both into `Capture.text` (no format change, but the two could never be
told apart again), keep the translation only in a side file (invisible in Obsidian, two files
to keep in sync), or add a field rendered inside the capture block.

## Decision

* `Capture.translation: str = ""` in `lumitrace/frames/dayfile.py`.
* `render` writes it at the end of the capture block, after the transcript, as
  `<!-- lumitrace:translation (English translation of the recording) -->`, a
  `#### English translation` heading and the text. `parse` takes everything after the marker
  as the translation (dropping the heading if present); older marker prefixes are accepted.
* No `lumitrace_format` bump: files without the marker parse exactly as before, and older code
  reading a new file would only see the translation as part of the transcript text.
* Spectrum adds the translation as extra `transcript` passages (heading
  `HH:MM · Log My Day · English`); the Lens `get_day` returns it per capture.
* Spectrum's edit signals still compare only the transcript text.

## Consequences

* English questions in AI apps match days spoken in Telugu.
* Owner edits to the translation are kept like transcript edits, but are not recorded as edit
  signals.
