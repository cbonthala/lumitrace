# 0032. Built-in single-owner OAuth with a password page

- Status: accepted
- Date: 2026-10-10

## Context

Claude and ChatGPT connectors need an OAuth 2.1 authorization server with dynamic client
registration and PKCE. Options: an external identity provider (Auth0, Cognito, Google) in front
of the server, or a small authorization server inside it. There is exactly one user.

## Decision

* Use the MCP SDK's auth support (metadata, `/register`, `/authorize`, `/token`, `/revoke`,
  PKCE and client checks) with our own `OwnerOAuthProvider`. `/authorize` redirects to
  `/oauth/login`, where the owner types `LIFELOG_MCP_OWNER_PASSWORD` and presses Allow or Deny.
* Issuer = `LIFELOG_MCP_PUBLIC_URL` (https, root); resource = issuer + `LIFELOG_MCP_PATH`;
  tokens are bound to that resource and the server validates it (`validate_token_resource`).
* Access tokens 1 h, refresh tokens 90 days and rotated, codes 5 min and single use.
* Clients and tokens persist in `mcp-oauth-state.json` next to the index (server disk, not
  storage: they are credentials, not journal data), mode 0600, tokens stored as SHA-256 hashes.
  Codes and pending sign-ins stay in memory.
* Brute-force guard: 5 wrong passwords per 15 minutes, then a lockout; 0.5 s delay per miss.
  Registration is open (required by connectors) but capped at 50 clients.

## Consequences

* No third-party account or extra service; works the same on AWS or a home server.
* Security rests on the password and HTTPS; no second factor. A leaked state file does not
  leak usable tokens. `lifelog-mcp reset-oauth` disconnects every app.
* One server process only (in-memory codes). Moving to multiple replicas would need shared
  storage for codes, or an external IdP (supersede this decision then).
* Not yet verified against the real Claude/ChatGPT connectors (see `docs/lens.md`).
