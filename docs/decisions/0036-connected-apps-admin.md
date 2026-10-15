# 0036. Connected AI apps: a private Lens admin port, used by the Flash app through the Prism

- Status: accepted
- Date: 2026-10-14

## Context

AI apps sign in to the Lens with the owner password (decisions 0032, 0034, 0035). The only way
to cut one off was `lumitrace-lens reset-oauth` on the server, which disconnects every app and
needs a restart. The owner wants to see the connected apps in the Flash web app and sign one
(or all) out, so it asks for the password again.

The OAuth state (clients and token hashes) lives in the Lens process's memory and is saved to
`mcp-oauth-state.json`. Another process editing that file would be overwritten by the Lens on
its next save, so changes must go through the Lens. The Lens's MCP port is public (Tailscale
Funnel); the Flash app is tailnet-only and behind its own password.

## Decision

* The Lens serves a second, private Starlette app (`lumitrace/lens/admin.py`) on
  `LUMITRACE_MCP_ADMIN_HOST`:`LUMITRACE_MCP_ADMIN_PORT` (default `127.0.0.1:8003`; Docker
  Compose binds `0.0.0.0` inside the container network and never publishes it). Same process
  and same `OwnerOAuthProvider` as the MCP app, so changes apply at once. It runs only with
  OAuth and a non-zero port.
* Routes: `GET /admin/apps`, `POST /admin/apps/{id}/sign-out`, `POST /admin/apps/sign-out-all`.
  Callers send `Authorization: Bearer <LUMITRACE_API_TOKEN>`; while that token is a placeholder
  or shorter than 16 characters, the API answers 503.
* One action, **Disconnect** (`sign-out`): it deletes the app's access and refresh tokens and
  any half-finished sign-in. Access tokens are opaque and looked up on every request, so the
  app is cut off on its next request, not when its 1-hour token would have expired. The
  registration stays, so the app reconnects with just the password.
* No "remove registration" action: it would not cut access any faster, and apps that keep
  their client id (Claude, ChatGPT) would fail to reconnect until the connector is re-added.
* The provider records when each app last used an access token, saved at once on first use
  and then at most once a minute.
* The Prism proxies these as `/lens/apps...` behind the Flash sign-in (or the API token) and
  calls `LUMITRACE_MCP_ADMIN_URL`. Any Lens failure becomes 502, never 401, because the Flash
  app treats 401 as its own sign-out.
* The Flash Settings tab shows a "Connected AI apps" card with **Disconnect** per connected app
  and **Disconnect all apps**, each behind a confirmation.

Rejected: putting the routes on the public MCP port (one leaked API token would let anyone on
the internet sign apps out or list them); having the Prism edit the state file (lost updates);
a separate admin password (the API token already guards the Prism, which is the only caller).

## Consequences

* Port 8003 must never be published or funnelled; it is listed in `AGENTS.md`.
* App names come from dynamic registration and are untrusted; the Flash app shows them as text.
* An app disconnected mid-session gets 401 on its next request and runs the sign-in again.
* Disconnected registrations stay listed until the 50-client cap or `reset-oauth` prunes them.
