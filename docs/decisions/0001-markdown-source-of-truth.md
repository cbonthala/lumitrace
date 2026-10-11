# 0001. Markdown day files are the source of truth

- Status: accepted
- Date: 2026-10-10

## Context

The journal must outlive any app, model or database, be readable without LifeLog, and be
editable by hand (in Obsidian). AI output will be wrong sometimes and must be correctable.

## Decision

One Markdown file per day with YAML front matter for facts, a generated journal region, a notes
region the system never touches, and the raw transcript (`docs/frames-format.md`). Every other
store (the SQLite index) is derived and disposable. Generated content carries a hash so owner
edits are detected and never overwritten.

## Consequences

- Plain files work with Obsidian, Drive, backups and future apps; nothing is locked in.
- The index must be rebuildable from the files, so anything only in the index (feedback, edit
  signals) is also written to `_system/` or is acceptable to lose.
- Format changes need versioning (`lifelog_format`) and parsers that read old versions.
- Parsing must be tolerant of hand edits; text outside known regions is moved to notes, not lost.
