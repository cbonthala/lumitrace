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
| [0009](0009-rename-to-lumen.md) | Rename to Lumen: Flash, Prism, Frames, Spectrum, Lens (superseded by 0042) |
| [0010](0010-durable-inbox-and-background-worker.md) | Recording API: durable inbox in storage, one worker, client capture ids |
| [0011](0011-save-transcript-first-then-generate.md) | Recording API: save transcript first, full vs additive generation, re-check edits |
| [0012](0012-activity-records-monthly-jsonl.md) | Recording API: activity records as monthly JSONL without content |
| [0013](0013-audio-and-photo-processing.md) | Recording API: ffmpeg → afconvert → keep original; photos without EXIF |
| [0014](0014-llm-json-validation-and-fallback.md) | Recording API: JSON validated per model, own fallback loop, `fake` model, prompt format |
| [0015](0015-sarvam-speech-to-text-and-translation.md) | Recording API: Sarvam batch speech to text, code-mixed transcript plus an English translation (translate job superseded by 0048) |
| [0016](0016-prompts-know-the-speaker-and-relations.md) | Recording API: prompts know the speaker and family relations, read translation and original together |
| [0017](0017-date-field.md) | Recording API: optional `date` field (`YYYY-MM-DD`) chooses the day; empty = capture time's day |
| [0018](0018-follow-the-original-over-the-translation.md) | Recording API: prompts follow the original transcript over the translation, always fill the author's block; `gpt-4.1` recommended |
| [0019](0019-flash-web-app-with-password-sign-in.md) | Flash web app served by the Prism at `/flash/`, username/password sign-in with a signed session cookie |
| [0020](0020-incremental-sync-change-feed-and-hashes.md) | Indexer: change feed, hashes, retries, daily full scan |
| [0021](0021-passages-and-embedding-reuse.md) | Indexer: passages by section/heading, embedding reuse |
| [0022](0022-edit-signal-baseline-and-supersede.md) | Indexer: edit-signal baseline and one row per baseline |
| [0023](0023-automatic-in-place-rebuild.md) | Indexer: automatic in-place rebuild on embedding changes |
| [0024](0024-single-writer-worker-and-nudge-endpoint.md) | Indexer: one worker thread, unauthenticated internal nudge |
| [0030](0030-hybrid-search-rrf.md) | MCP: hybrid search with reciprocal rank fusion, date filters in SQL |
| [0031](0031-mcp-auth-modes.md) | MCP: auth modes none / token / oauth, strict startup checks |
| [0032](0032-single-owner-oauth.md) | MCP: built-in single-owner OAuth with a password page |
| [0033](0033-mcp-reads-and-feedback-writes.md) | MCP: per-call read-only index, `get_day` from storage, dual feedback write |
| [0040](0040-facts-in-day-file-body-and-family-sections.md) | Day file format 2: facts in an "At a glance" section, places, a block per family member (`LUMITRACE_FAMILY`) |
| [0041](0041-aws-lightsail-with-tailscale.md) | Hosting: one AWS Lightsail instance, Prism on the tailnet, Lens public through Tailscale Funnel |
| [0042](0042-rename-to-lumitrace.md) | Rename Lumen to Lumitrace everywhere; module names unchanged |
| [0043](0043-capture-translation-in-day-file.md) | Day file: a recording's English translation stored under its transcript |
| [0044](0044-flash-on-the-tailnet-root-url.md) | Hosting: the Flash app on the plain tailnet address, the Lens Funnel on `:8443` |
| [0045](0045-day-template-and-telugu-journal-skill.md) | Topic-first day template and a skill for filling it from Telugu transcripts |
| [0046](0046-journal-once-after-rollover.md) | Write the journal once, five minutes after the day closes |
| [0047](0047-family-file.md) | Family members and prompt notes live in `secrets/family.md`, not in environment variables |
| [0048](0048-journal-reads-the-telugu-transcript.md) | One Sarvam transcript job; the journal reads that Telugu text plus the glossary and keyterms |
| [0049](0049-one-call-fills-the-day-file.md) | One Gemini 3.8 Flash call fills the day file from the transcript and the day template |
| [0050](0050-later-recording-updates-the-day.md) | A recording after the journal exists updates that day from the new transcript only |
| [0051](0051-one-prompt-file-per-task.md) | One prompt file per task; the day template lives in `prompts/` |
| [0052](0052-day-journal-reading-rules.md) | Fill-day prompt, day template, and skill share the reading rules |
| [0053](0053-gemini-embeddings.md) | Search vectors come from Gemini Embedding 2, at 1536 dimensions |
| [0054](0054-flash-reviews-before-sending.md) | Flash holds a recording for play, pause, and crop, and sends only when you tap Send |
| [0055](0055-generate-journal-from-flash.md) | Flash Generate writes one day now (destructive rewrite superseded by 0058) |
| [0056](0056-journal-covers-the-whole-recording.md) | The journal covers each recording to the end; Everyone meals are filled in code |
| [0057](0057-day-file-drops-glance-and-translation.md) | Day file format 4: no At a glance section and no English translation |
| [0058](0058-notes-and-safe-section-updates.md) | My notes feed generation; later source is inserted into existing journal sections without rewriting edits |
| [0059](0059-restore-structured-facts-with-three-way-merge.md) | Format 5 restores structured facts and merges later model facts without losing owner edits |
| [0060](0060-replace-model-facts-and-correct-the-journal.md) | Later source replaces model facts and may correct an untouched generated journal sentence |
| [0061](0061-format-6-family-day-files.md) | Format 6 uses one structured timeline and family-tracker content region |
| [0062](0062-flash-talk-map-before-recording.md) | Flash shows a Format 6 talk map before the microphone starts |
| [0063](0063-flash-requires-filing-date.md) | Flash requires an explicit filing date, including today, before Send |
| [0064](0064-discard-unused-captures.md) | Flash can discard a capture the journal has not used |
| [0065](0065-photo-only-captures.md) | Photo-only captures stay in the day file and are sent to fill/update |
| [0066](0066-later-source-retitles-model-heading.md) | Later source may retitle a heading the owner has not edited |
