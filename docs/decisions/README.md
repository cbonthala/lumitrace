# Decision records

One short note per decision: what we chose, why, and what it costs. Never rewrite an accepted
decision; supersede it with a new one and link both ways.

Numbering (so parallel work streams don't collide):

| Range | Area |
|---|---|
| 0001–0009 | foundation (incl. Frames) |
| 0010–0019 | Prism (recording API) |
| 0020–0029 | Spectrum (indexer) |
| 0030–0039 | Lens (MCP server) |
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
| [0007](0007-plain-english-test-catalog.md) | Plain-English test catalog, kept complete by a test |
| [0008](0008-project-and-module-names.md) | Project and module names: Bookshelf, Notepad, Typewriter, Books, Bookmarks, Reading Lamp (superseded by 0009) |
| [0009](0009-rename-to-lumen.md) | Rename to Lumen: Flash, Prism, Frames, Spectrum, Lens |
| [0010](0010-durable-inbox-and-background-worker.md) | Recording API: durable inbox in storage, one worker, client capture ids |
| [0011](0011-save-transcript-first-then-generate.md) | Recording API: save transcript first, full vs additive generation, re-check edits |
| [0012](0012-activity-records-monthly-jsonl.md) | Recording API: activity records as monthly JSONL without content |
| [0013](0013-audio-and-photo-processing.md) | Recording API: ffmpeg → afconvert → keep original; photos without EXIF |
| [0014](0014-llm-json-validation-and-fallback.md) | Recording API: JSON validated per model, own fallback loop, `fake` model, prompt format |
| [0020](0020-incremental-sync-change-feed-and-hashes.md) | Indexer: change feed, hashes, retries, daily full scan |
| [0021](0021-passages-and-embedding-reuse.md) | Indexer: passages by section/heading, embedding reuse |
| [0022](0022-edit-signal-baseline-and-supersede.md) | Indexer: edit-signal baseline and one row per baseline |
| [0023](0023-automatic-in-place-rebuild.md) | Indexer: automatic in-place rebuild on embedding changes |
| [0024](0024-single-writer-worker-and-nudge-endpoint.md) | Indexer: one worker thread, unauthenticated internal nudge |
| [0030](0030-hybrid-search-rrf.md) | MCP: hybrid search with reciprocal rank fusion, date filters in SQL |
| [0031](0031-mcp-auth-modes.md) | MCP: auth modes none / token / oauth, strict startup checks |
| [0032](0032-single-owner-oauth.md) | MCP: built-in single-owner OAuth with a password page |
| [0033](0033-mcp-reads-and-feedback-writes.md) | MCP: per-call read-only index, `get_day` from storage, dual feedback write |
