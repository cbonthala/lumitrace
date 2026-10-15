# 0034. OAuth sessions end a fixed number of days after the password sign-in

- Status: accepted
- Date: 2026-10-14

## Context

Decision 0032 gave refresh tokens 90 days and rotated them on every refresh, with each new
refresh token getting a fresh 90 days. An AI app used at least once every 90 days therefore
stayed connected forever, and the owner password was only ever typed once per app. The Lens is
public (Tailscale Funnel), so a leaked refresh token or a forgotten connected account kept access
indefinitely. The owner wants every app to ask for the password again every 7 days.

## Decision

* New setting `LUMITRACE_MCP_SESSION_DAYS` (default 7, at least 1).
* Each token records `signed_in_at`, the time of the password sign-in. Refreshing copies it to
  the new pair instead of starting a new session.
* No token expires later than `signed_in_at` + the session length: the access token is cut
  short (its `expires_in` says so), and the refresh token is refused after that moment, so the
  app has to run the sign-in again.
* Tokens saved before this change have no `signed_in_at`; on startup they count as signed in
  then, and the capped expiry is saved, so restarts don't extend them.
* The password page tells the owner how long the app will stay connected.

A fixed session from sign-in was chosen over "7 days without use" (a 7-day sliding refresh
lifetime) because the owner asked to be logged off every 7 days even when apps are used daily.

## Consequences

* The owner types the password in each AI app once a week. `reset-oauth` still disconnects
  everything at once.
* Changing the setting applies to existing tokens on the next restart (shorter only; a longer
  setting does not extend tokens already cut short).
* The static `LUMITRACE_MCP_AUTH_TOKEN` was not affected; decision 0035 removed it.
