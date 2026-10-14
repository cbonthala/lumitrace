# 0019. A Flash web app served by the Prism, with username/password sign-in

- Status: accepted
- Date: 2026-10-13

## Context

The Flash was only Apple Shortcuts: five shortcuts with about 60 hand-built actions, iPhone
only, and the API token typed into one of them. The owner wants to capture from any browser
(phone or laptop, over Tailscale) and add it to the iPhone Home Screen like an app, and to sign
in with a username and password instead of pasting a token.

## Decision

* A static web app (plain HTML, CSS and JavaScript, no build step) in `lumitrace/prism/web/`,
  served by the Prism at `/flash/` (and `/` redirects there). Same origin as the API, so no CORS
  and no server address to configure. A second program or a frontend framework was not worth
  it for one page.
* **Sign-in:** `POST /login` checks `LUMITRACE_FLASH_USERNAME` and `LUMITRACE_FLASH_PASSWORD`
  (plain values in `.env`, like `LUMITRACE_MCP_OWNER_PASSWORD`, ADR 0032) in constant time, and
  sets a cookie `lumitrace_flash` = `v1.<expiry>.<HMAC-SHA256>`. HttpOnly, `SameSite=Strict`,
  `Secure` (except plain HTTP on localhost), `Max-Age` = `LUMITRACE_FLASH_SESSION_DAYS` (90).
  Stateless: the key is derived from the API token, username and password, so changing any of
  them signs every browser out; there is no session store.
* **Same brute-force guard as the Lens:** 5 wrong attempts per 15 minutes lock sign-in (429),
  with a 0.5 s delay per miss.
* Sign-in is off (503) while the username is empty, the password is empty, `change-me` or
  shorter than 10 characters, or the API token is unusable (it signs the sessions).
* `require_auth` accepts the bearer token **or** the cookie on every API endpoint, so the
  Shortcuts are unchanged. A cookie-authenticated request that changes something and carries
  `Sec-Fetch-Site: cross-site` is refused (403), on top of `SameSite=Strict`.
* Two new read endpoints for the app: `GET /captures` (recent statuses, no journal content) and
  `GET /summary` (days logged in the last 7 days, captures in them, streak; read from the day
  files, one storage listing per month).
* **Offline:** every capture is put in IndexedDB before upload and deleted only after the Prism
  answers with its `capture_id`, the same rule as the Shortcuts' Flash Inbox; a service worker
  keeps the app shell available offline. Retries reuse the `capture_id`, so they are never
  stored twice.

## Consequences

* Capturing needs no Shortcuts setup; the Shortcuts remain for what a web page cannot do: Siri,
  the Action Button, the share sheet, today's photos picked automatically, and recording with
  the screen locked.
* A browser recording stops when the phone locks or the app goes to the background; the app
  asks to keep the screen awake (Screen Wake Lock) and says so on screen.
* Recordings arrive as `.m4a` (Safari) or `.webm` (Chrome, Firefox); the Prism already converts
  any format with ffmpeg.
* Security rests on the password, HTTPS (Tailscale) and the lockout; no second factor. The
  lockout is global, so someone guessing can keep the owner locked out for 15 minutes.
* Not yet verified on a real iPhone (microphone permission in a Home Screen app, wake lock,
  IndexedDB blobs).
