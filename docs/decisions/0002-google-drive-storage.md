# 0002. Google Drive storage behind a swappable interface

- Status: accepted
- Date: 2026-10-10

## Context

Files must be readable in Obsidian on phone and laptop, backed up, and private. Options: S3 (no
easy reading/sync on devices), iCloud (no server API), Dropbox, Google Drive, Proton Drive (no
third-party API yet, see 0006).

## Decision

Google Drive first, behind the `Storage` interface (`lumen/frames/storage/base.py`) with a `local`
backend for development and tests. The Drive backend uses only the `drive.file` scope: the app
creates the `LifeLog` folder and can see only files it created. Changes are detected with the
Drive changes API (page tokens). Audio links are the file's private `webViewLink`.

## Consequences

- Drive syncs to devices, so Obsidian can open the folder; links open only for the owner.
- `drive.file` is a non-sensitive scope (no Google verification), but files created *outside*
  the app (e.g. a new note made in Obsidian) are invisible to it. Edits to app-created files are
  visible. Reading self-written notes is an open question in the plan.
- The OAuth consent screen must be "In production" or refresh tokens expire after 7 days
  (`docs/runbook.md`).
- Moving to another store means writing one new backend class; nothing else changes.
