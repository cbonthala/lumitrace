# 0035. The Lens has one login: OAuth with the owner password

- Status: accepted (removes the `token` mode and static token of decision 0031)
- Date: 2026-10-14

## Context

Decision 0031 offered a static bearer token (`LUMITRACE_MCP_AUTH_TOKEN`), as the default `token`
mode and as a second way into `oauth` mode for Cursor and scripts. The token never expired,
skipped the owner password and the 7-day sessions of decision 0034, and worked through the public
Funnel address. Production no longer used it; the owner wants a single way in.

## Decision

* `LUMITRACE_MCP_AUTH_MODE` is `oauth` (default) or `none`. The `token` mode and the
  `LUMITRACE_MCP_AUTH_TOKEN` setting are removed; `oauth` mode accepts only tokens issued after a
  password sign-in.
* Every HTTP client signs in through OAuth: Claude and ChatGPT connectors, Cursor (URL only) and
  Claude Desktop through `mcp-remote` (it runs the browser sign-in). Local testing uses OAuth
  too, with `LUMITRACE_MCP_PUBLIC_URL=http://localhost:8002` (http is allowed on localhost).
* `none` stays for in-process tests and a Lens bound to 127.0.0.1; it still warns otherwise.
* A leftover `LUMITRACE_MCP_AUTH_TOKEN` is ignored (settings ignore unknown keys);
  `LUMITRACE_MCP_AUTH_MODE=token` fails at startup with a settings error.

## Consequences

* One credential (the owner password) and one session rule for every app.
* Scripts and the Bruno MCP requests need an OAuth access token (1 hour) instead of a fixed
  token; the Bruno test gets one through the real sign-in flow.
* A fresh `.env` from `.env.example` needs `LUMITRACE_MCP_OWNER_PASSWORD` before the Lens starts
  over HTTP (`stdio` is unaffected).
