# Changelog

All notable changes. Format: [Keep a Changelog](https://keepachangelog.com/). Each work stream
edits only its own subsection under *Unreleased* to avoid merge conflicts.

## [Unreleased]

### Foundation

- Project setup: Python 3.12, uv, ruff, pytest; one `lifelog` package.
- `lifelog.config.Settings` covering API, storage, speech, LLM, embeddings, index and MCP
  settings; `.env.example` documents every variable.
- Swappable storage: `Storage` interface, `LocalStorage`, `GDriveStorage` (`drive.file` scope,
  changes API, share links) and the `lifelog-gdrive-login` command.
- Day-file contract `lifelog.dayfile`: paths, 4 a.m. rollover, `DayFile` model, lossless
  parse/render, `merge_capture`, edit-safe `apply_generation` / `merge_generation_additive`.
- Index contract `lifelog.index.schema`: facts, passages, FTS5, sqlite-vec, files, edit signals,
  feedback, meta.
- Shared helpers: `lifelog.embeddings.embed_texts` (with offline `fake` model) and
  `lifelog.nudge.nudge_indexer`.
- Placeholder entry points `lifelog-api` (`/health`), `lifelog-indexer`, `lifelog-mcp`.
- Dockerfile (Python 3.12 slim, ffmpeg, uv) and docker-compose with api, indexer and mcp sharing
  a data volume.
- Docs: AGENTS.md, README, architecture, contracts, day-file format, index schema, decisions
  0001–0006, runbook, learnings, prompts README.

### Recording API

### Indexer

### MCP server
