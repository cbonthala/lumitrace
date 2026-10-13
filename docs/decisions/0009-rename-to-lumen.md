# 0009. Rename to Lumen

- Status: superseded by [0042](0042-rename-to-lumitrace.md)
- Date: 2026-10-11
- Supersedes: [0008](0008-project-and-module-names.md)

## Context

Decision 0008 renamed LifeLog to Bookshelf with an everyday-home theme (Notepad, Typewriter,
Books, Bookmarks, Reading Lamp). The owner then chose a more modern theme built around light,
which also fits what the parts do: one raw recording is split into several kinds of output and
then looked at more closely.

## Decision

The project is **Lumen**. The story line, used at the top of the README and the architecture
page: *A Flash captures the moment, the Prism splits it into its colors, each day becomes a
Frame, the Spectrum lays everything out in order, and the Lens lets you zoom into any day.*

| Name | What it is | Code | Command | Docker service | Docs |
|---|---|---|---|---|---|
| Lumen | the project | `lumen/` | | image `lumen` | `README.md` |
| Flash | the iPhone Shortcuts (Log My Day, Quick Note, Flash Config, Send pending, Send to Lumen) | none | | | `docs/flash.md` |
| Prism | recording API + processing pipeline: splits one beam of raw voice into its colors (facts, journal, mood, transcript) | `lumen/prism/`, `lumen/prism/pipeline/` | `lumen-prism` | `prism` | `docs/prism.md` |
| Frames | the day files (one Frame per day): format and storage layer | `lumen/frames/dayfile.py`, `lumen/frames/storage/` | `lumen-drive-login` | | `docs/frames-format.md` |
| Spectrum | the indexer | `lumen/spectrum/` | `lumen-spectrum` | `spectrum` | `docs/spectrum.md` |
| Lens | the MCP server (shown to AI apps as "Lumen") | `lumen/lens/` | `lumen-lens` | `lens` | `docs/lens.md` |

Everything else from decision 0008 carries over with the new names:

* Environment variables use the prefix `LUMEN_`. Field names keep their technical prefixes
  (`api_*`, `indexer_*`, `mcp_*`).
* The Drive root folder defaults to `Lumen`, local storage to `data/Lumen`, and the index file is
  `lumen.sqlite`. The `_system/` subfolder names are unchanged.
* `config`, `embeddings`, `nudge`, `logging_setup` and `index/schema.py` stay shared at the top of
  the package: the Spectrum writes the index and the Lens reads it, and neither imports the
  other's package.
* Day-file markers become `<!-- lumen:... -->` and the front-matter key `lumen_format`; prompt
  markers become `<!-- lumen-prompt: ... -->`. `parse` reads all three generations of markers
  (`lumen:`, `bookshelf:`, `lifelog:`) and format keys (`lumen_format`, `bookshelf_format`,
  `lifelog_format`); `render` writes only the new names. `FORMAT_VERSION` stays 1.
* The OAuth scope is `lumen`; existing connections must be reset once.
* The Lens's tool class is `LensTools`.
* The helper shortcuts are renamed (Notepad Config → Flash Config, Notepad Inbox → Flash Inbox,
  Send to Bookshelf → Send to Lumen). Log My Day, Quick Note and Send pending keep their names:
  they are what the owner says to Siri and taps every day.
* The descriptive terms (recording API, indexer, MCP server, day files) remain fine in prose next
  to the new names. Earlier decisions keep their original wording; only their file paths and
  links were updated. Decision 0008 is marked superseded and otherwise unchanged.
* The repository folder will be renamed from `lifelog` to `lumen` separately; nothing in the code
  depends on it.

## Consequences

- A second rename commit touches nearly every file; `git mv` keeps the history of each module.
- Existing deployments, under either earlier name, need the one-time steps in
  `docs/runbook.md` → *Upgrading from LifeLog or Bookshelf* (`.env` prefix, Drive folder, index
  file, Docker volume, MCP client configs, OAuth reset, shortcut names).
- The compatibility branch in `lumen/frames/dayfile.py` now covers two older generations; keep it
  for as long as such day files may exist.
- `AGENTS.md`, the README and this decision carry the name map; keep them in sync when adding a
  component.
