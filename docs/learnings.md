# Learnings

What we learned about quality, models, prompts and operations, and what to change next.
Personal details are always removed; the full weekly reports live in `LifeLog/_system/reports/`.

Entry format: `- YYYY-MM-DD — observation → action (link to PR/ADR)`.

## Foundation

- 2026-10-10 — mcp resolved to 2.x, where `FastMCP` is now `mcp.server.mcpserver.MCPServer`;
  v1 examples online won't work as-is → use the 2.x API.
- 2026-10-10 — With the `drive.file` scope, files created outside LifeLog are invisible to it →
  reading self-written Obsidian notes needs a decision (open question in the plan).
- 2026-10-10 — Photos are embedded as `![[photo-NN.jpg]]`, a name that repeats in every day
  folder. Obsidian should resolve it to the file next to the note, but this is unverified →
  check in Obsidian; if wrong, switch embeds to relative Markdown links.

## Recording API

## Indexer

## MCP server

## Models and prompts
