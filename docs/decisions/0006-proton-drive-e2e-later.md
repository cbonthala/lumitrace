# 0006. Proton Drive / end-to-end encryption later

- Status: accepted
- Date: 2026-10-10

## Context

A life journal is highly sensitive. Google Drive encrypts at rest but Google can read the files.
Proton Drive is end-to-end encrypted but has no official API for third-party apps yet.

## Decision

Start with Google Drive (0002). Revisit when Proton Drive officially supports third-party apps,
or encrypt audio and photos client-side before upload. The `Storage` interface keeps this a
backend swap.

## Consequences

- Version one is not end-to-end encrypted; the README says so.
- AI providers see transcripts during processing regardless of storage; that is governed by the
  provider's terms and opt-outs (0005).
- An encrypted off-site backup with a tested restore is the first priority after version one.
