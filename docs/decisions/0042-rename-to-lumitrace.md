# 0042. Rename Lumen to Lumitrace

- Status: accepted
- Date: 2026-10-12
- Supersedes: [0009](0009-rename-to-lumen.md)

## Context

"Lumen" alone was too generic to search for or to tell apart from other products. The owner
wanted a more distinctive name that still fits the light theme of the modules (Flash, Prism,
Frames, Spectrum, Lens): light that leaves a trace of each day.

## Decision

The project is **Lumitrace**, everywhere: code, docs, infrastructure and accounts. The module
names and the story line from decision 0009 are unchanged.

| Name | What it is | Code | Command | Docker service |
|---|---|---|---|---|
| Lumitrace | the project | `lumitrace/` | | image `lumitrace` |
| Flash | the iPhone Shortcuts (Log My Day, Quick Note, Flash Config, Send pending, Send to Lumitrace) | none | | |
| Prism | recording API + processing pipeline | `lumitrace/prism/` | `lumitrace-prism` | `prism` |
| Frames | the day files: format and storage layer | `lumitrace/frames/` | `lumitrace-drive-login` | |
| Spectrum | the indexer | `lumitrace/spectrum/` | `lumitrace-spectrum` | `spectrum` |
| Lens | the MCP server (shown to AI apps as "Lumitrace") | `lumitrace/lens/` | `lumitrace-lens` | `lens` |

* Environment variables use the prefix `LUMITRACE_`. The Drive root folder defaults to
  `Lumitrace`, local storage to `data/Lumitrace`, the index file is `lumitrace.sqlite` and its
  backup `_system/index-backup/lumitrace.sqlite`.
* Day-file markers become `<!-- lumitrace:... -->` and the front-matter key `lumitrace_format`;
  prompt markers become `<!-- lumitrace-prompt: ... -->`. `parse` reads all four generations of
  markers and format keys (`lumitrace`, `lumen`, `bookshelf`, `lifelog`); `render` writes only the
  new names. `FORMAT_VERSION` stays 2.
* The OAuth scope is `lumitrace`.
* Infrastructure follows: the Lightsail instance `lumitrace` (static IP `lumitrace-ip`, key pair
  `lumitrace-key`, SSH key `~/.ssh/lumitrace-lightsail`), the server folder `/opt/lumitrace`, the
  Compose project and volume `lumitrace` / `lumitrace-data`, and the Tailscale machine `lumitrace`
  (`https://lumitrace.<tailnet>.ts.net`). Lightsail cannot rename resources, so the server was
  replaced rather than renamed; the index is rebuilt from the day files.
* Accounts follow: the Google OAuth app is named Lumitrace, the repository is
  `lumitrace`, and the local folder is `lumitrace`.
* Earlier decisions keep their wording; only code paths and module names in them were updated.
  Decision 0009 is marked superseded and otherwise unchanged.

## Consequences

- A third rename touches nearly every file; `git mv` keeps each module's history.
- The compatibility branch in `lumitrace/frames/dayfile.py` now covers three older generations;
  keep it for as long as such day files may exist.
- Existing deployments need the one-time steps in `docs/runbook.md` → *Upgrading from LifeLog,
  Bookshelf or Lumen*. The Prism and Lens addresses change, so Flash Config and AI-app
  connectors must be updated.
- `AGENTS.md`, the README and this decision carry the name map; keep them in sync.
