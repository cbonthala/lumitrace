# Flash (web app and iPhone Shortcuts)

A Flash captures the moment. There are two ways to do it, and both send everything to the Prism
(the recording API; reference: `docs/prism.md`):

* **The Flash web app** (section 0): a page the Prism serves at `/flash/`. Open it in any
  browser on your phone or laptop, sign in with a username and password, and add it to the
  iPhone Home Screen. Nothing to build.
* **Apple Shortcuts** (sections 1 to 11): for Siri, the Action Button, the share sheet,
  today's photos picked automatically, and recording with the screen locked.

You can use both; captures from either land in the same day file.

## 0. The Flash web app

**Set up (once, on the server):**

1. In `.env` set `LUMITRACE_FLASH_USERNAME` and `LUMITRACE_FLASH_PASSWORD` (at least 10
   characters; a passphrase is easiest to type on a phone). `LUMITRACE_API_TOKEN` must be set
   too: it signs the sign-in sessions.
2. Restart the Prism: `docker compose up -d prism`.
3. Make the Prism reachable over HTTPS (section 1). Browsers only allow the microphone on HTTPS
   (or `http://localhost`).

**On the phone or laptop:**

1. Open `https://<your address>` (it goes to `/flash/`; on the Tailscale setup:
   `https://<machine>.<tailnet>.ts.net`) and sign in. iCloud Keychain or your
   password manager can save the password.
2. iPhone: Safari → **Share** → **Add to Home Screen**. It opens full screen like an app and
   stays signed in for `LUMITRACE_FLASH_SESSION_DAYS` (90 days by default). On a laptop, use the
   browser's **Install** or **Add to Dock** option, or a bookmark.

**What it does:**

| Part | What it does |
|---|---|
| **Log My Day** (big red button) | first tap opens a talk map of every Format 6 day-file field (timeline, who/where/people, food, body, pregnancy, daycare/work, likes, growth, highlight and remember). **Start talking** starts the microphone; the cards stay on screen while you talk so you can glance and tap one once you have covered it. **Discard**, **Pause** / **Resume**, and **Stop** are the same icons as on the record card, on the sheet (ADR 0062). Stop holds the take (it is not sent yet). Then **Play**, drag the two handles to crop, pick **Filing under** (even if it is today), and **Send** or **Discard**. Send posts that audio to `POST /recordings` with the photos you picked, the place name and (if turned on) your location. An uncropped take is the original file; a crop is trimmed on the phone before upload (ADR 0054) |
| **Send** (bottom corner of the Log My Day card) | sends the photos on that card when there is no recording (`POST /notes`). One photo and no audio is enough. While a recording is waiting in review, this same button sends the recording. Either way, a day must already be chosen; if it is not, a **Select the date** sheet asks before anything is uploaded (ADR 0063) |
| **Upload audio** (chip under the record button) | pick an audio file (a Voice Memo saved to Files, an `.m4a`, `.mp3`, `.wav`, ...) and send it as Log My Day with the photos you picked and the place name, but not your current location (the memo may be from elsewhere). You still choose **Filing under** first; the app then asks before sending |
| **Filing under** | the day the capture belongs to (`date`). It starts unselected. Choose today, yesterday, or another day before Send. The web app will not guess today for you (ADR 0063) |
| **This week** | days logged in the last 7 days, entries in them, and your streak (`GET /summary`) |
| **Recent captures** / History | captures from the last 7 days, grouped by the day they are filed under. Each row is the time, what it was, and a status: Waiting (still on this device), Queued, Retrying…, Transcribing… (a recording) or Saving… (a note or photos), Not in journal (saved; the journal waits for Generate or 4:05 a.m.), In journal (this capture's words are in the journal), Journal failed (the recording is saved; the model did not write), or Failed (tap to retry). **Generate** beside the day writes its first journal and structured facts from every recording and My notes (`POST /journal`, ADR 0058, 0059). Later clicks process changed source, or repair missing format-4 facts, without changing owner words or fact edits. There is no Later section. Notes and recordings stay. Anything still waiting on the phone is sent first |
| **Design** (tab on a phone, **How it works** button on a laptop) | an animated diagram of the Flash → Prism → Frames → Spectrum → Lens flow and one short card per module: what it does and where you see it in the app |
| **Settings** | place name and location switch (saved on the device only), sign out, and **Connected AI apps** |
| **Connected AI apps** (in Settings) | the AI apps that have connected to the Lens (Claude, ChatGPT, ...): name, the website it signs in from, Connected or Disconnected, when it signed in, when its session ends and when it was last used. **Disconnect** cuts an app off at once (its next request is refused) until it signs in again with the Lens password; **Disconnect all apps** does it for every app. Each asks for confirmation (`/lens/apps`, decision 0036) |

On a phone the screen has four tabs (Capture, History, Design, Settings). Turned sideways, the
Capture page uses two columns (the record card next to this week) so the record button stays on the first
screen. From 600 to 899 px the single column is centred at 640 px. On a laptop (900 px and
wider) the capture cards and the history list sit side by side. **Home** (the house, next to
Connected) returns to Capture. **How it works** opens the Design page.

**Offline:** every capture is saved in the browser (IndexedDB) before it is uploaded and removed
only after the Prism confirms it. Without a connection the app still opens (a service worker
keeps a copy), records, and shows "waiting to send"; it sends by itself when you're back online,
when you reopen the app, every minute, or when you tap **Send now**. A capture the Prism refuses
(for example too large) is marked "Not accepted"; tap it to remove it.

**Limits of a web app on iPhone:**

* Recording stops if the screen locks or you switch apps. The app asks iOS to keep the screen
  on while recording and while paused; keep it in front. A take you have not sent yet stays
  in the browser until you Send or Discard; leaving the page asks you to stay.
* No Siri, Action Button, Back Tap, share sheet or automations; use the Shortcuts for those.
* Photos are picked by hand (the browser cannot read today's photos by itself).
* Location is latitude and longitude only, with the place name you set in Settings; there is
  no reverse geocoding.

Sign-in details: `docs/prism.md` → Flash web app endpoints; decision: ADR 0019.

---

The rest of this guide is the Shortcuts. Written for iOS 18 (most steps work on iOS 17; noted
where not). Action names are as they appear in the Shortcuts action search.

You will build four Flash shortcuts and one automation:

| Shortcut | What it does |
|---|---|
| **Flash Config** | holds the API address and token, used by all the others |
| **Log My Day** | record audio + location + today's photos → `POST /recordings` |
| **Send pending** | uploads anything left in the offline inbox |
| **Send to Lumitrace** | share sheet: send a Voice Memo or photos |
| *Nightly reminder* | automation at about 9 p.m. that starts Log My Day |

> Variable names below in *italics* are the names you give with **Rename** (long-press an
> action's output, or tap the magic variable and choose Rename). Shortcuts names outputs itself
> otherwise ("Recorded Audio", "Contents of URL", ...).

## 1. Reaching the API

The phone needs an **HTTPS** address for the recording API (the token travels in every request,
so never use plain HTTP outside your home network). Two options:

**A. Tailscale (recommended: nothing exposed to the internet)**

1. Install Tailscale on the server and on the iPhone, sign in to the same tailnet.
2. In the Tailscale admin console enable **MagicDNS** and **HTTPS certificates**.
3. On the server: `sudo tailscale serve --bg --https=443 http://127.0.0.1:8000` (proxies
   `https://<machine>.<tailnet>.ts.net` to the API with a valid certificate, tailnet only).
   On the Lightsail server `deploy/lightsail/tailscale.sh` does this, and also publishes the Lens
   on port 443 through Funnel (`docs/runbook.md` → Deploying on AWS Lightsail).
4. On the iPhone, Tailscale app → settings → turn on **VPN On Demand** so the connection comes up
   by itself when a shortcut runs.
5. The API address is `https://<machine>.<tailnet>.ts.net` (no port; decision 0044).

**B. Public HTTPS**

Put a reverse proxy with automatic certificates in front of port 8000, for example Caddy with a
`Caddyfile` of `lumitrace.example.com { reverse_proxy localhost:8000 }`, and point the DNS name at
the server. The Shortcuts only need `POST /recordings`, `POST /notes`, `GET /captures/*` and
`GET /health`; the web app also needs `/flash/*`, `/login`, `/logout`, `/session`, `/captures`,
`/summary` and `/lens/apps*`. Every request without the token or a signed-in session is refused.

Check it from Safari on the phone: `https://<address>/health` should show `{"status":"ok",...}`.

## 2. Token handling

* Generate the token on the server: `openssl rand -hex 32`, set `LUMITRACE_API_TOKEN` in `.env`,
  restart the Prism (`docker compose up -d prism`).
* Put it **only** in the Flash Config shortcut below. All other shortcuts read it from there, so
  rotating the token is one edit (`docs/runbook.md` → Rotating tokens).
* **Never share Flash Config** (or a shortcut that contains the token): a shared shortcut
  includes its text. Share the others freely; they contain no secrets.
* If the phone is lost: rotate the token on the server; the old one stops working immediately.

## 3. Flash Config

1. New shortcut, name it **Flash Config**.
2. **Dictionary** action with two Text items:
   * `url` → `https://<your address>` (no trailing slash)
   * `token` → the token
3. **Stop and Output** → *Dictionary*. (If "There's nowhere to output to", choose *Do Nothing*.)
4. Shortcut details (ⓘ): turn **off** "Show in Share Sheet"; optionally hide it from widgets.

Each of the other shortcuts starts with the same three steps (written "**Load config**" below):

1. **Run Shortcut** → *Flash Config*; tap the chevron and turn **off** "Show While Running".
2. **Get Dictionary Value** → Get *Value* for `url` in *Shortcut Result* → rename to *API*.
3. **Get Dictionary Value** → Get *Value* for `token` in *Shortcut Result* → rename to *Token*.

## 4. The offline inbox ("Flash Inbox" in Files)

Every capture is saved to **iCloud Drive → Shortcuts → Flash Inbox → *capture id*/** *before*
it is uploaded, and the folder is deleted only after the API confirms it. Shortcuts has no
error handling: when an upload fails (no signal, server down) the shortcut simply stops with an
error, and the capture stays in the inbox for **Send pending**. Because every capture carries the
same `capture_id` on every attempt, re-sending is always safe: the API stores each id once and
answers `200 "duplicate": true` for anything it already has.

Create the folder once in the Files app: iCloud Drive → Shortcuts → new folder **Flash Inbox**.

## 5. Log My Day

New shortcut **Log My Day**. Actions in order:

1. **Load config** (three actions, section 3).
2. **Record Audio**: Audio Quality *Normal*; Start Recording *Immediately*; Finish Recording
   *On Tap*. Rename the output *Recording*.
3. **Current Date**, then **Format Date**: Date Format *ISO 8601*, **Include ISO 8601 Time** on.
   Rename to *Captured At* (looks like `2026-10-10T21:30:00-05:00`).
4. **Format Date** on *Current Date* again: Date Format *Custom*, format string
   `yyyyMMdd'T'HHmmss`. Then a **Text** action: `iphone-` *Formatted Date* `-rec`. Rename the Text
   to *Capture ID*.
5. **Get Current Location**. Then three **Get Details of Locations** actions on *Current
   Location*: *Latitude* (rename *Lat*), *Longitude* (*Lon*), *City* (*Place*). The first run
   asks for location permission: choose *Always Allow* for this shortcut.
6. **Find Photos**: Add Filter → *Date Taken* *is today*; optionally another filter *Media Type*
   *is* *Image* (skips videos); Sort by *Date Taken*, Order *Latest First*; Limit on, *Get 30
   Photos*. Rename *Photos*. The first run asks for Photos access.
7. Optional but recommended (smaller, faster uploads; the server resizes to 2048 px anyway):
   **Resize Image** *Photos* to width `2048` (height Auto), then **Convert Image** to *JPEG*,
   quality ~0.8, Preserve Metadata off. Rename the result *Photos*.
8. **Save to the inbox**:
   1. **Text** action with this JSON, inserting the variables where shown:
      `{"kind": "recording", "capture_id": "`*Capture ID*`", "captured_at": "`*Captured At*`",
      "lat": "`*Lat*`", "lon": "`*Lon*`", "place": "`*Place*`"}`. Then **Set Name** on it:
      `meta.json`.
   2. **Save File** *Text* (the renamed meta.json): Ask Where to Save **off**; destination
      *Shortcuts* folder; Subpath `Flash Inbox/`*Capture ID*`/`; Overwrite If File Exists on.
   3. **Set Name** on *Recording*: `audio.m4a`; **Save File** it to the same subpath.
   4. **Save File** *Photos* to the same subpath.
9. **Get Contents of URL**:
   * URL: *API* `/recordings`
   * Method: **POST**
   * Headers: `Authorization` → `Bearer ` *Token* (one space after Bearer)
   * Request Body: **Form**, with fields (tap *Add new field*):
     | Key | Type | Value |
     |---|---|---|
     | `audio` | File | *Recording* |
     | `photos` | File | *Photos* |
     | `captured_at` | Text | *Captured At* |
     | `capture_id` | Text | *Capture ID* |
     | `lat` | Text | *Lat* |
     | `lon` | Text | *Lon* |
     | `place` | Text | *Place* |
10. **Get Dictionary Value**: *Value* for `capture_id` in *Contents of URL*.
11. **If** *Dictionary Value* **has any value**:
    * **Get File from Folder**: Folder *Shortcuts*, Path `Flash Inbox/`*Capture ID*, Error If
      Not Found off; then **Delete Files** on it with **Confirm Before Deleting** off.
    * **Get Dictionary Value** `message` in *Contents of URL* → **Show Notification** with it
      (e.g. "Recording saved for Saturday, October 10. Your journal updates in a minute.").
12. **Otherwise**: **Show Notification** "Saved offline. Run Send pending later." then **End If**.

Notes:

* If no photo was taken today, *Photos* is empty and the field is just left out; that is fine.
* A file field holding several photos sends one form part per photo, all named `photos`; the
  API also accepts `photos[]`. Check the first run: `GET /captures/<id>` (or the day folder)
  should list every photo.
* The response arrives within a few seconds; transcription and the journal take about a minute
  more. Open the day in Obsidian afterwards.

## 6. Quick Note (retired)

Do not build this shortcut. Delete **Quick Note** on the phone if it is still there. Days are
captured by recording. A photo with no recording is sent from the web app's **Send** button,
which still uses `POST /notes`. Old day files that already contain a Quick Note stay as they are.

**Filing under another day** (Log My Day, optional): add a Text field `date` →
*Formatted Date* to the request body, next to `captured_at` (a **Format Date** action with custom
format `yyyy-MM-dd`, from an **Ask for Input** of type Date). Leave it off, or empty, for today.

## 7. Send pending

New shortcut **Send pending**. It uploads every folder in Flash Inbox and deletes the ones the
API confirms.

1. **Load config**.
2. **Get File from Folder**: Folder *Shortcuts*, Path `Flash Inbox`. Then **Get Contents of
   Folder** on it. Rename *Pending*.
3. **If** *Pending* **does not have any value** → **Show Notification** "Nothing to send" →
   **Stop This Shortcut** → **End If**.
4. **Repeat with Each** item in *Pending* (each item is one capture folder):
   1. **Get Contents of Folder** *Repeat Item* → rename *Files*.
   2. **Filter Files** *Files* where *Name* *is* `meta.json` → **Get Text from Input** →
      **Get Dictionary from Input** → rename *Meta*.
   3. **Filter Files** *Files* where *Name* *begins with* `audio` → *Audio*.
      **Filter Files** *Files* where *Name* *begins with* `photo` → *Photos* (photos saved by
      Log My Day keep their original names; use *Name* *is not* `meta.json`, `audio.m4a`,
      `note.txt` if yours differ).
      **Filter Files** *Files* where *Name* *is* `note.txt` → **Get Text from Input** → *Note*.
   4. **Get Dictionary Value** `kind` in *Meta*.
   5. **If** *Dictionary Value* **is** `recording`: **Get Contents of URL** POST *API*
      `/recordings`, Form body like Log My Day, with values from *Meta* (**Get Dictionary Value**
      `capture_id`, `captured_at`, `lat`, `lon`, `place`), `audio` → *Audio*, `photos` → *Photos*.
      **Otherwise**: **Get Contents of URL** POST *API* `/notes`, **Form** body with `text` →
      *Note*, `audio` → *Audio* (if it was a voice clip), `captured_at`, `capture_id`, `place`
      from *Meta*. **End If**.
   6. **Get Dictionary Value** `capture_id` in *If Result*; **If** it has any value → **Delete
      Files** *Repeat Item* (Confirm Before Deleting off). **End If**.
5. **End Repeat** → **Show Notification** "Flash inbox sent".

If the network drops halfway, the shortcut stops; run it again later. Captures already accepted
are deleted from the inbox, and anything re-sent is recognised by its `capture_id`.

Tip: add a personal automation **When Wi-Fi joins** (your home network) → *Run Immediately* →
**Run Shortcut** *Send pending*, so the inbox empties itself.

## 8. Send to Lumitrace (share sheet, Voice Memos)

New shortcut **Send to Lumitrace**; in details (ⓘ) turn on **Show in Share Sheet**, and in the
first block "Receive *Media, Files, Images* from *Share Sheet*", If there's no input: *Stop and
Respond*.

1. **Load config**.
2. **Get Details of Files** *Shortcut Input* → *Creation Date* → **Format Date** ISO 8601 with
   time → *Captured At*. (For a Voice Memo this is when it was recorded.) When several photos
   are shared, put **Get Item from List** → *First Item* before Format Date so you get one date.
3. *Capture ID*: **Format Date** of *Creation Date* with `yyyyMMdd'T'HHmmss`, Text
   `iphone-`…`-memo`.
4. **Get Type** of *Shortcut Input*. **If** *Type* **contains** `Image` (or `Photo`): **Get
   Contents of URL** POST *API* `/notes` with header `Authorization` → `Bearer ` *Token* and Form
   fields `photos` (File) → *Shortcut Input*, `captured_at`, `capture_id`. **Otherwise**: POST
   *API* `/recordings` with the same header and Form fields `audio` (File) → *Shortcut Input*,
   `captured_at`, `capture_id`. **End If**.
5. Show the `message` from the response as a notification.

In Voice Memos: tap a memo → ••• → Share → **Send to Lumitrace**. Long memos are fine; the API
accepts up to `LUMITRACE_API_MAX_UPLOAD_MB` (200 MB by default).

## 9. Nightly reminder (about 9 p.m.)

Shortcuts app → **Automation** → **+** → **Time of Day**:

1. Time *9:00 PM*, Repeat *Daily*.
2. Choose **Run After Confirmation** (iOS 17+: the toggles are *Run Immediately* / *Run After
   Confirmation*; keep **Notify When Run** on). Next.
3. Action: **Run Shortcut** → *Log My Day*. Done.

At 9 p.m. a notification appears; tap it (then *Run*) and recording starts immediately. Recording
audio needs the phone unlocked, which is why this runs after confirmation instead of silently.

## 10. Ways to start a capture

* **Siri:** "Hey Siri, Log My Day" (Siri uses the shortcut name).
* **Action Button** (iPhone 15 Pro and later): Settings → Action Button → swipe to
  **Shortcut** → *Log My Day*.
* **Control Center** (iOS 18): swipe down → **+** → Add a Control → **Shortcuts** → *Run
  Shortcut* → choose it.
* **Lock Screen** (iOS 18): long-press the Lock Screen → Customize → Lock Screen → tap the
  flashlight or camera button → replace with a **Shortcut** control. (iOS 16–17: add a
  Shortcuts widget to the Home Screen instead.)
* **Back Tap:** Settings → Accessibility → Touch → **Back Tap** → *Double Tap* → *Log My Day*.
* **Apple Watch:** Log My Day uses Record Audio and Find Photos, which are not available on
  watchOS, so start it from the phone.
* **Share sheet:** *Send to Lumitrace* from Voice Memos, Photos or Files (section 8).
* **Home Screen:** long-press a shortcut in the Shortcuts app → Share → *Add to Home Screen*.

## 11. Checking that it worked

* The notification shows the API's `message`. Only a `capture_id` in the response proves the
  server stored it.
* Status: open `https://<address>/captures/<capture id>` with the header (or make a tiny shortcut:
  Get Contents of URL GET with the Authorization header → Quick Look). `done` means the day file
  is written; `errors` lists AI steps that failed (the transcript is saved regardless).
* In Files, Flash Inbox should be empty after a successful run.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Could not connect to the server" | No signal or Tailscale off: the capture is in Flash Inbox; run Send pending later. |
| `401` / "missing or invalid bearer token" | Token in Flash Config differs from `LUMITRACE_API_TOKEN`; check the space after `Bearer`. |
| `503` "API token is not configured" | `LUMITRACE_API_TOKEN` is empty on the server. |
| `413` | Upload too large: lower the photo limit or resize photos (step 7). |
| `422` with `capture_id` | Use only letters, digits, `.`, `_`, `-` in the id. |
| Photos missing | Check Photos permission for the shortcut and the *Find Photos* filters. |
| Wrong day | Before 4 a.m. counts as the previous day (by design). Otherwise check `LUMITRACE_TIMEZONE`. |
