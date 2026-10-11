# 0031. MCP auth modes: none, token, oauth

- Status: accepted
- Date: 2026-10-10

## Context

The MCP server exposes the whole journal. Local apps (Claude Desktop, Cursor) can run it over
stdio or send a header; phone apps (Claude, ChatGPT connectors) can only do OAuth with dynamic
client registration. The owner is a single person.

## Decision

* `LIFELOG_MCP_AUTH_MODE` = `none` | `token` | `oauth`, applied to the streamable-http
  transport only; stdio is a local child process and is never authenticated.
* `token` (default): one static bearer token, compared in constant time through the SDK's
  `TokenVerifier` / `RequireAuthMiddleware`.
* `oauth`: our own minimal authorization server (decision 0032). The static token, if set, is
  still accepted so scripts and Cursor keep working.
* Refuse to start with an empty, placeholder (`change-me`) or short (< 16 chars) token or
  password, an `http://` public URL that is not localhost, or a public URL with a path.
* `none` logs a warning when not bound to localhost.

## Consequences

* Misconfiguration fails at startup instead of silently exposing the journal.
* `token` mode has no expiry; rotation is manual (`docs/runbook.md`).
