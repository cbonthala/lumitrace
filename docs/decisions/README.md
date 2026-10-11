# Decision records

One short note per decision: what we chose, why, and what it costs. Never rewrite an accepted
decision; supersede it with a new one and link both ways.

Numbering (so parallel work streams don't collide):

| Range | Area |
|---|---|
| 0001–0009 | foundation |
| 0010–0019 | recording API |
| 0020–0029 | indexer |
| 0030–0039 | MCP server |
| 0040+ | later work (take the next free number) |

Template:

```markdown
# NNNN. Title

- Status: accepted | superseded by NNNN
- Date: YYYY-MM-DD

## Context
## Decision
## Consequences
```

| # | Decision |
|---|---|
| [0001](0001-markdown-source-of-truth.md) | Markdown day files are the source of truth |
| [0002](0002-google-drive-storage.md) | Google Drive storage behind a swappable interface |
| [0003](0003-sqlite-fts5-sqlite-vec-index.md) | SQLite + FTS5 + sqlite-vec index |
| [0004](0004-mcp-instead-of-chat-app.md) | MCP instead of a custom chat app |
| [0005](0005-config-driven-providers-litellm.md) | Config-driven providers via LiteLLM |
| [0006](0006-proton-drive-e2e-later.md) | Proton Drive / end-to-end encryption later |
