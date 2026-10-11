# 0008. Project and module names: Bookshelf

- Status: accepted
- Date: 2026-10-11

## Context

The project started as "LifeLog", with technical names for its parts (recording API, indexer,
MCP server, day files). The owner wanted names that are friendlier to talk about and that hang
together, so that the docs read as one story and it is obvious which part does what.

## Decision

The project is **Bookshelf**, with an everyday-home theme. The story line, used at the top of
the README and the architecture page: *You jot it on the Notepad, the Typewriter turns it into
Books, Bookmarks mark every page worth finding, and the Reading Lamp lets you read any of it.*

| Name | What it is | Code | Command | Docker service | Docs |
|---|---|---|---|---|---|
| Bookshelf | the project | `bookshelf/` | | image `bookshelf` | `README.md` |
| Notepad | the iPhone Shortcuts (Log My Day, Quick Note, Notepad Config, Send pending, Send to Bookshelf) | none | | | `docs/notepad.md` |
| Typewriter | recording API + processing pipeline | `bookshelf/typewriter/`, `bookshelf/typewriter/pipeline/` | `bookshelf-typewriter` | `typewriter` | `docs/typewriter.md` |
| Books | the day files: format and storage layer | `bookshelf/books/dayfile.py`, `bookshelf/books/storage/` | `bookshelf-drive-login` | | `docs/books-format.md` |
| Bookmarks | the indexer | `bookshelf/bookmarks/` | `bookshelf-bookmarks` | `bookmarks` | `docs/bookmarks.md` |
| Reading Lamp | the MCP server (shown to AI apps as "Bookshelf") | `bookshelf/reading_lamp/` | `bookshelf-reading-lamp` | `reading-lamp` | `docs/reading-lamp.md` |

Details of the rename:

* Environment variables use the prefix `BOOKSHELF_`. Field names keep their technical prefixes
  (`api_*`, `indexer_*`, `mcp_*`), so the settings still say what they configure.
* The Drive root folder defaults to `Bookshelf` and local storage to `data/Bookshelf`. The index
  file is `bookshelf.sqlite`. The `_system/` subfolder names are unchanged.
* `bookshelf/index/schema.py` stays a shared module rather than moving into
  `bookshelf/bookmarks/`: Bookmarks writes the index but the Reading Lamp reads it, and the Reading
  Lamp should not import the indexer's package. `config`, `embeddings`, `nudge` and
  `logging_setup` stay at the top of the package for the same reason.
* Day-file markers become `<!-- bookshelf:... -->` and the front-matter key `bookshelf_format`;
  prompt markers become `<!-- bookshelf-prompt: ... -->`. Following decision 0001 (parsers read
  old versions), `parse` still accepts `lifelog:` markers and `lifelog_format`, and `render`
  writes the new names. `FORMAT_VERSION` stays 1: the structure is unchanged, only the names.
* The OAuth scope is `bookshelf`; existing connections must be reset once.
* The descriptive terms (recording API, indexer, MCP server, day files) remain fine in prose next
  to the new names. Earlier decisions keep their original wording; only their file paths and
  links were updated.

## Consequences

- One rename commit touches nearly every file; `git mv` keeps the history of each module.
- Existing deployments need the one-time steps in `docs/runbook.md` → *Upgrading from LifeLog*
  (`.env` prefix, Drive folder, index file, Docker volume, MCP client configs, OAuth reset).
- Code paths no longer match the technical names, so `AGENTS.md`, the README and this decision
  carry the name map; keep them in sync when adding a component.
- A small compatibility branch in `bookshelf/books/dayfile.py` stays for as long as pre-rename
  day files may exist.
