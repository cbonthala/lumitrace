# Changelog

All notable changes. Format: [Keep a Changelog](https://keepachangelog.com/). Each work stream
edits only its own subsection under *Unreleased* to avoid merge conflicts.

## [Unreleased]

### Foundation

- **Day file format 5 restores structured facts** (ADR 0059). At a glance again writes Highlight,
  Food, Places, People, Health, Feelings, Memories, Weather and Things we did. Format 4 still
  parses and its next Generate repairs the missing facts. English translations remain absent.
- **Day file format 4** (ADR 0057). A new write has the title, the journal, My notes and the
  Telugu transcript. It does not include At a glance or an English translation. Older files
  still parse. The next system write drops both. Fact search stays filled only for days that
  still have the old section.
- **Search uses Gemini embeddings** (ADR 0053). `LUMITRACE_EMBEDDING_MODEL` is
  `gemini/gemini-embedding-2`, same `GEMINI_API_KEY` as the day file. The call asks for 1536
  values (the model's full vector is 3072). Restarting Spectrum rebuilds the index.
- **Day file format 3 and index schema 3** (ADR 0045, accepted): the facts are topic first
  (Highlight with Remember, Food by person and meal, Places visited, People we met or visited,
  Health and fitness, Feelings, Memories, Weather, Things we did) with a block per family
  member, so new members appear everywhere. Formats 1 and 2 are still read and converted.
  Spectrum indexes the new fields (`meals.person`, `days.remember`, family categories
  `feelings`/`health`/`moments`, facts passages per section and person) and rebuilds old
  indexes by itself; the Lens `query_facts` takes `person` for meals. `extract_facts-v6` writes
  the new shape. `docs/templates/day-template.md` matches the real layout.
- **Family file** (ADR 0047): who is in the family, birth dates, and the notes the prompts use
  to resolve names live in `secrets/family.md` (Docker: `/secrets/family.md`).
  `LUMITRACE_FAMILY` and `LUMITRACE_GLOSSARY` are removed. `get_settings()` loads the file;
  tests pass a household in and do not read it. A missing file means no family blocks.

### Prism

- **A later recording replaces model facts and corrects the journal** (ADR 0060). The same fact
  is kept once, so a reworded gloss does not sit beside the old line. A journal that is still
  the model's is rewritten from every recording; a sentence you changed stays, and a generated
  sentence a newer recording contradicts can be replaced. `activities.minutes` is only a number
  you stated. `lumitrace-prism regenerate --replace-generated` runs that update even when the
  recordings are unchanged.
- **Bulk regenerate uses the Flash Generate button** (ADR 0059). `lumitrace-prism regenerate`
  calls `generate_day` for each day. An existing journal is updated safely, including a day you
  edited. It no longer skips edited days or replaces an unedited journal from scratch.
- **Generate keeps structured facts current without losing owner edits** (ADR 0059). Fill and
  update replies include complete facts. The previous model facts are kept separately under
  `_system/generated-facts/` and used as the base of a three-way merge; owner additions, changes
  and removals win. Missing state triggers a one-time format-4 facts repair, while an actual
  fact-free day remains unchanged on later clicks.
- **Capture status chips match the journal.** A recording in progress says Transcribing…, and a saved capture whose journal is still waiting says Not in journal. In journal appears only after that capture's words are in the journal. The history list follows the day file, so Generate and the 4:05 a.m. run flip the chip without sending the clip again.
- **My notes feed safe journal updates** (ADR 0058). The first journal uses every recording plus
  My notes. Later recordings or changed notes return missing bullets classified as Summary,
  Morning, Afternoon, Evening or Thoughts; code inserts them without rewriting existing words.
  `generated_source_hash` prevents repeat Generate clicks and capture replays from duplicating
  content. There is no Later section. Format-4 regeneration trusts the generated hash so a
  refreshed snapshot cannot hide manual corrections.
- **The journal prompt no longer asks for At a glance or a translation** (ADR 0057). `fill_day`
  and `update_day` return a headline and a journal. The Telugu transcript is the source.
- **Journal calls keep the end of a long recording** (ADR 0056). The fill-day prompt must cover
  each transcript through its last sentence, including the final third, and a word cap no longer
  cuts a long day short. An item is shared only when the transcript names that person or says
  "we". The call logs the `{{captures}}` length and the model's maximum output tokens (65536
  for Gemini 3.8 Flash) and sends that ceiling; a reply cut off by a lower ceiling is retried
  once. The whole transcript is sent. Day-level meals are filled in code from each person's
  meals, tagged with who had them (`oatmeal (Maya, Leo)`). The model is not asked for that list.
- **Generate writes today's journal from Flash** (ADR 0055, safe-update behavior superseded by
  ADR 0058). History groups captures by the day they are filed under. **Generate** beside that
  day writes the first journal now; later clicks safely process changed recordings or My notes.
  **Home**, next to Connected, returns to Capture. The record card no longer stretches to the
  height of the history list.
- **Quick Note is retired in the Flash web app.** The typed note card is gone. Record through
  the day; the journal is written at the end of the day. A photo with no recording still sends
  from the Log My Day card (`POST /notes`). Old Quick Notes already in day files stay readable.
  Delete the **Quick Note** shortcut on the phone.
- **Flash reviews a recording before sending** (ADR 0054). The red button stops and holds the
  take. Pause and Resume stay on the same recording. Play, crop with two handles, then Send
  or Discard. An uncropped take is uploaded as recorded. A crop is trimmed in the browser,
  which takes about as long as the part you keep. Pause, play, and discard are icon buttons.
  Send sits in the bottom corner of the card and also sends photos when there is no recording.
- **Fallback is Gemini too.** `LUMITRACE_LLM_FALLBACK_MODEL` is `gemini/gemini-3.6-flash`, the same
  `GEMINI_API_KEY` as the day-file model. It runs when `gemini-3.8-flash` fails or times out.
- **Day-journal rules** (ADR 0052). `prompts/fill_day.md`, the day template, and the Telugu
  journal skill now agree: a bare Nanna means the author when they are talking about their own
  child; events stay in spoken order unless a time is stated; నిన్న / yesterday belongs to the
  previous date; unknown names are `[uncertain: name unclear]`; weather is null unless a lookup
  is passed in; drop what you cannot tell, and mark an unclear detail `[uncertain: why]`;
  Thoughts is a journal heading; meal types include drinks.
- **One prompt file per task** (ADR 0051). `prompts/fill_day.md` and `prompts/update_day.md`
  replace the `v1` folders. `prompts/day-template.md` is the shape pasted into the fill-day
  call. A new day stores `prompt_version: fill_day` or `update_day`. Edit the file; git is
  the history.
- **A later recording updates the day; unused prompts are gone** (ADR 0050). The 4:05 a.m.
  write is `fill_day` from every transcript, and it replaces a journal typed before that run.
  A recording that arrives after the journal exists is one `update_day` call on that recording
  only; existing words stay. `extract_facts`, `write_journal`, and `journal_addendum` prompts
  are removed. `LUMITRACE_LLM_EXTRACT_FACTS_MODEL` is removed. Regenerating an edited day
  skips it.
- **One Gemini call fills the day file** (ADR 0049). After Sarvam, `fill_day-v1` reads the
  Telugu transcript, the family-file notes, the keyterms, and `docs/templates/day-template.md`,
  and returns the facts and the journal together. The model is
  `LUMITRACE_LLM_WRITE_JOURNAL_MODEL` (`gemini/gemini-3.8-flash`). An edited day still keeps
  your words: facts from the new entry plus a short addendum. Needs `GEMINI_API_KEY`.
- **One Sarvam job; the journal reads the Telugu** (ADR 0048). The Saaras `translate` job and
  `LUMITRACE_SARVAM_TRANSLATE` are gone. `write_journal-v6` and `journal_addendum-v6` receive
  the code-mixed transcript, the family-file glossary and the keyterms. They do not receive an
  English translation or the extracted facts. Fact extraction still sees a translation already
  stored on an older capture. Journal models stay the env settings.
- **Family-file notes are background** (ADR 0047): `extract_facts-v7`, `write_journal-v5`,
  `journal_addendum-v5`. The Markdown under `secrets/family.md` is sent as `{{glossary}}`.
  The prompts may use it to resolve a word that was said, and must not turn a usual routine
  into a fact for today. The family list in that file, including a birth date, is the
  `{{family}}` line.
- **The journal is written once, at 4:05 a.m.** (ADR 0046). Recordings during the day are
  transcribed and saved only. Five minutes after the day rollover, and on startup if that run
  was missed, Prism writes the facts and journal from every recording of the day that just
  closed. A day you edited keeps your words. A capture for a day that has already closed is
  written immediately.
- **`lumitrace-prism regenerate`** redoes past days from their transcripts with the current
  prompts and format. Unedited days are replaced; edited days only gain the new facts
  (`--dry-run`, `--from`, `--to`, `--nudge`). It calls the AI models, so check with `--dry-run`.

- **Day template and Telugu journal skill** (ADR 0045, proposed): `docs/templates/day-template.md`
  (topic-first, per-member subsections, Food by meal, People we met or visited, `Remember:`
  recap) and the project skill `.cursor/skills/lumitrace-telugu-day-journal/` with a fictional
  `glossary.example.md`; the real `glossary.local.md` is git-ignored. Not parsed by the code yet.
- **Prompts use the Telugu day rules** (ADR 0045): `extract_facts-v5`, `write_journal-v4`,
  `journal_addendum-v4` carry the rules of the `lumitrace-telugu-day-journal` skill (original
  over translation, Nanna rules, known translation errors, no deliveries as visits, no shows as
  people, high bar for health, keep small emotional moments, later recording wins). The journal
  is bullets with a `**Remember:**` line. New setting `LUMITRACE_GLOSSARY` (`Settings.glossary`,
  `glossary_lines`) feeds names and mishearings into `{{glossary}}`. Dry-run on a real day
  before deploying.
- `.env.example` matches production's providers: `openai/gpt-4.1` for fact extraction and
  journal writing, and Sarvam speech-to-text in Telugu (`LUMITRACE_STT_MODEL` commented out, as
  it is only read by the `litellm` provider).
- `docs/architecture.md` → *Deployment and providers*: a simple high-level diagram of the
  programs, the Lightsail server, Tailscale and the outside services (Sarvam, OpenAI, Google
  Drive).
- `setup_logging` keeps `httpx` and `httpcore` at WARNING: their INFO lines printed full request
  URLs, including Sarvam's signed storage links.
- **English translation in the day file** (ADR 0043): `Capture.translation`, written at the
  end of a recording's transcript block under a `<!-- lumitrace:translation -->` marker and an
  `#### English translation` heading; files without it read as before.
- `LUMITRACE_FAMILY` accepts relations and marks the owner: `Sam (me), Maya (wife), Leo (son)`.
  New `Settings.family_relations` and `Settings.owner_name`; `family_members` still returns the
  names only.
- **Bruno collection** (`bruno/`) for trying the APIs by hand, one folder per module: Prism
  (health, notes, recording, capture status, retry), Spectrum (health, nudge) and Lens (health,
  OAuth discovery, and the MCP session with all five tools). Local and Production environments
  read tokens from a git-ignored `bruno/.env`; `tests/test_bruno_collection.py` checks the
  requests against the real routes and runs the MCP sequence. Guide: `docs/runbook.md` →
  *Trying the API with Bruno*.
- Cloud Agent notes in `AGENTS.md`: uv 0.13.0 on `/usr/local/bin`, `uv sync --frozen`, and
  tmux sessions for Prism, Spectrum, and Lens with a generated offline `.env` when none exists.
- **Renamed the project from Lumen to Lumitrace** (decision 0042, supersedes 0009), everywhere;
  the module names (Flash, Prism, Frames, Spectrum, Lens) are unchanged. Entries below this one
  use the Lumen names.
  - Package `lumen` → `lumitrace` (git mv); commands `lumitrace-prism`, `lumitrace-spectrum`,
    `lumitrace-lens`, `lumitrace-drive-login`.
  - Environment prefix `LUMEN_` → `LUMITRACE_`; Drive root folder `Lumitrace`, local root
    `data/Lumitrace`, index `lumitrace.sqlite` (backup `_system/index-backup/lumitrace.sqlite`).
  - Docker image `lumitrace`, volume `lumitrace-data`; Lightsail instance `lumitrace`, static IP
    `lumitrace-ip`, key pair `lumitrace-key`, server folder `/opt/lumitrace`, Tailscale name
    `lumitrace`.
  - Day files are written with `lumitrace:` markers and `lumitrace_format`; `lumen:` files (and the
    two older generations) are still read, and the compatibility test covers all three. Prompt
    markers are `lumitrace-prompt:`; the OAuth scope is `lumitrace`; AI apps list "Lumitrace".
  - Shortcut **Send to Lumen** → **Send to Lumitrace**. Upgrading: `docs/runbook.md` →
    *Upgrading from LifeLog, Bookshelf or Lumen*.
- `docs/tech-stack.md`: every language, library, tool, AI provider, service and client Lumen
  uses, grouped by module (shared, Flash, Prism, Frames, Spectrum, Lens, deployment,
  development), with versions, what each is for, and whether it is open source (license).
  Linked from README.
- **Renamed the project from Bookshelf to Lumen** (decision 0009, supersedes 0008): *A Flash
  captures the moment, the Prism splits it into its colors, each day becomes a Frame, the
  Spectrum lays everything out in order, and the Lens lets you zoom into any day.* Name map in
  README and AGENTS.md.
  - Package `bookshelf` → `lumen` (git mv): `typewriter` → `lumen/prism/` (pipeline in
    `lumen/prism/pipeline/`), `books` → `lumen/frames/`, `bookmarks` → `lumen/spectrum/`,
    `reading_lamp` → `lumen/lens/` (`ReadingLampTools` → `LensTools`). Shared modules stay at
    the top. Tests mirror the layout (`tests/prism/`, `tests/frames/`, `tests/spectrum/`,
    `tests/lens/`).
  - Commands `lumen-prism`, `lumen-spectrum`, `lumen-lens`, `lumen-drive-login` replace the
    `bookshelf-*` commands.
  - Environment prefix `BOOKSHELF_` → `LUMEN_`; default Drive root folder `Lumen`, local root
    `data/Lumen`, index `data/index/lumen.sqlite` (backup `_system/index-backup/lumen.sqlite`).
    `_system/` subfolders unchanged.
  - Docker: image `lumen`, services `prism`, `spectrum` (port still internal) and `lens`, volume
    `lumen-data`.
  - The Lens shows itself to AI apps as "Lumen"; OAuth scope `lumen`.
  - Day files are written with `lumen:` markers and `lumen_format`; files with `bookshelf:` or
    `lifelog:` markers and `bookshelf_format` or `lifelog_format` are still read (the
    compatibility test now covers both). Prompt markers are `lumen-prompt:`.
  - Docs renamed: `prism.md`, `spectrum.md`, `lens.md`, `flash.md`, `frames-format.md`.
    Shortcuts **Flash Config**, **Flash Inbox** and **Send to Lumen** replace Notepad Config,
    Notepad Inbox and Send to Bookshelf; Log My Day, Quick Note and Send pending keep their
    names.
  - Upgrading an existing setup (from LifeLog or Bookshelf): `docs/runbook.md` → *Upgrading
    from LifeLog or Bookshelf*. The repository folder is renamed to `lumen` separately.
- **Renamed the project from LifeLog to Bookshelf** (decision 0008, superseded by the Lumen
  rename above; names in this entry are the Bookshelf ones): *you jot it on the
  Notepad, the Typewriter turns it into Books, Bookmarks mark every page worth finding, and the
  Reading Lamp lets you read any of it.* Name map in README and AGENTS.md.
  - Package `lifelog` → `bookshelf`: `api` + `pipeline` → `bookshelf/typewriter/` (pipeline in
    `bookshelf/typewriter/pipeline/`), `indexer` → `bookshelf/bookmarks/`, `mcp_server` →
    `bookshelf/reading_lamp/`, `dayfile.py` + `storage/` → `bookshelf/books/`. `config`,
    `embeddings`, `nudge`, `logging_setup` and `index/schema.py` stay shared at the top. Tests
    mirror the layout (`tests/typewriter/`, `tests/bookmarks/`, `tests/reading_lamp/`,
    `tests/books/`).
  - Commands `bookshelf-typewriter`, `bookshelf-bookmarks`, `bookshelf-reading-lamp`,
    `bookshelf-drive-login` replace `lifelog-api`, `lifelog-indexer`, `lifelog-mcp`,
    `lifelog-gdrive-login`. `bookshelf-typewriter --help` now prints help instead of starting
    the server.
  - Environment prefix `LIFELOG_` → `BOOKSHELF_`; default Drive root folder `Bookshelf`, local
    root `data/Bookshelf`, index `data/index/bookshelf.sqlite` (backup
    `_system/index-backup/bookshelf.sqlite`). `_system/` subfolders unchanged.
  - Docker: image `bookshelf`, services `typewriter`, `bookmarks` (port still internal) and
    `reading-lamp`, volume `bookshelf-data`.
  - Reading Lamp shows itself to AI apps as "Bookshelf"; OAuth scope `bookshelf`.
  - Day files are written with `bookshelf:` markers and `bookshelf_format`; files with the old
    `lifelog:` markers and `lifelog_format` are still read. Prompt markers are
    `bookshelf-prompt:`.
  - Docs renamed: `typewriter.md`, `bookmarks.md`, `reading-lamp.md`, `notepad.md`,
    `books-format.md`. Shortcuts "LifeLog Config", "LifeLog Inbox" and "Send to LifeLog" are now
    **Notepad Config**, **Notepad Inbox** and **Send to Bookshelf**; Log My Day and Quick Note
    keep their names.
  - Upgrading an existing setup: `docs/runbook.md` → *Upgrading from LifeLog*.
- `docs/test-cases.md`: a plain-English catalog of every test, grouped by component and
  feature, with an end-to-end story, a "covered / not covered" line per component and each
  test's name for tracing. `tests/test_docs_test_cases.py` fails when a test is missing from
  the catalog or the catalog names a test that no longer exists. AGENTS.md rule 8 requires
  describing every new or changed test; linked from README and `docs/architecture.md`;
  decision 0007.
- **Day file format 2** (decision 0040): the facts move from the front matter into an
  `## At a glance` section under the title (`lumen:facts` markers): Mood, City and Weather
  lines, then Food, Places, People, Activities, Family and Highlights. New facts `places` and
  `family` (one `#### name` block per family member: Mood, Ate, Went to, Did, Moments, Health,
  School/work); `family_events` is removed. Values are normalised so render and parse agree,
  and hand edits are tolerated (unplaceable lines move into My notes). Format 1 files are still
  read: their `family_events` go into highlights and an unedited day stays unedited. New
  setting `LUMEN_FAMILY` (comma-separated names; `Settings.family_members`).
- **Strict, identical layout every day:** "At a glance" always has the same lines in the same
  order, with `none` for empty ones (all six sections, five Food lines, seven lines per family
  member; `NONE_TEXT`). Meal types are fixed (`MEAL_TYPES`: breakfast, lunch, dinner, snacks,
  drinks; synonyms mapped, anything else → snacks). Generated journals only use the headings
  Summary, Morning, Afternoon, Evening, Thoughts and Later (`normalize_journal`, applied by
  `apply_generation`); additions to edited days go under `## Later` with a bold time label
  (`merge_generation_additive(addendum_label=...)`, formerly `addendum_heading`, which wrote a
  `###` heading). `render_facts_section(..., include_empty=False)` gives the view without
  `none` lines.
- Index schema version 2: new tables `places` and `family_facts`, `family_events` removed.
- **AWS Lightsail deployment** (decision 0041): `deploy/lightsail/` scripts create a 2 GB
  instance in `us-east-2` (SSH key, daily snapshots, static IP, SSH-only firewall), deploy the
  committed code with ports bound to localhost, and publish the Prism on the tailnet and the
  Lens through Tailscale Funnel. Steps in `docs/runbook.md` → *Deploying on AWS Lightsail*.
  Fixed after the first real run: the SSH key pair is named `lumen-key` (Lightsail names are
  unique across resource types), and `cloud-init.sh` is POSIX sh running the setup under bash
  (Lightsail runs user data with `/bin/sh`, where `pipefail` failed); it can be re-run by hand.
  `deploy.sh` now gives the uploaded `secrets/` to the container user (uid 10001), which
  otherwise could not read or refresh the Google Drive token. `.env.example` and the runbook
  warn that a Docker `.env` must not set the path settings (they override the image's container
  paths). `docs/flash.md` now uses the Prism address `tailscale.sh` serves
  (`https://<machine>.<tailnet>.ts.net:8443`).
- **Easier Flash address** (decision 0044): `tailscale.sh` now serves the Prism on port 443
  (tailnet only) and funnels the Lens on 8443, so the Flash app is at
  `https://lumitrace.<tailnet>.ts.net` and the Lens at `https://lumitrace.<tailnet>.ts.net:8443/mcp`.
  The script resets the old serve/funnel setup first. New runbook section *Renaming the
  tailnet*.

### Prism (recording API)

- **Flash web app** (ADR 0019) at `/flash/` (`/` redirects there): capture from any browser on
  a phone or laptop and add it to the iPhone Home Screen. Record your day (with picked photos,
  a place name and optional location), send quick notes, choose another day, see this week's
  days logged, entries and streak, and follow each capture's status (tap a failed one to
  retry). Phone layout with Capture/History/Settings tabs; two columns from 900 px. Captures
  are kept in the browser (IndexedDB) until the Prism confirms them, and a service worker lets
  the app open offline. Plain HTML/CSS/JS in `lumitrace/prism/web/`, no build step.
- **Flash web app: Design page**: a new **Design** tab (the **How it works** button in the
  header on a laptop) with an animated diagram (`flow.svg`) of Flash → Prism → Frames →
  Spectrum → Lens and a short card per module. Layout clean-up: phone in landscape uses two columns,
  600–899 px widths are centred, side margins respect the notch, and the tab bar is centred.
- **Username/password sign-in** for the web app: `POST /login`, `POST /logout`, `GET /session`.
  New settings `LUMITRACE_FLASH_USERNAME`, `LUMITRACE_FLASH_PASSWORD` (at least 10 characters),
  `LUMITRACE_FLASH_SESSION_DAYS` (90). A signed, HttpOnly, `SameSite=Strict` cookie works on
  every endpoint alongside the bearer token (`require_token` is now `require_auth`); changing
  the password, username or API token signs every browser out. Five wrong passwords in 15
  minutes lock sign-in; cookie requests from other sites that change something get `403`.
- `GET /captures` (recent capture statuses, newest first) and `GET /summary` (days logged in
  the last 7 days, captures in them, streak), for the web app.
- **Flash web app: Upload audio**: a chip under the record button sends an audio file (a Voice
  Memo saved to Files, `.m4a`, `.mp3`, `.wav`, ...) as Log My Day, filed under the day the file
  was recorded or saved unless a day is chosen. It goes through the same offline outbox.
- **Connected AI apps in Flash Settings** (decision 0036): lists the AI apps signed in to the
  Lens (name, website, sign-in time, session end, last use), with **Disconnect** and
  **Disconnect all apps**: the app is cut off on its next request and needs the Lens password
  again. Backed by `GET /lens/apps`, `POST /lens/apps/{id}/sign-out` and
  `POST /lens/apps/sign-out-all`, which call the Lens admin API at the new
  `LUMITRACE_MCP_ADMIN_URL`; Lens failures are `502`.
- **Prompts `extract_facts` v4, `write_journal` v3, `journal_addendum` v3** (ADR 0018): follow
  the original transcript when the machine translation disagrees (instead of dropping the
  detail), understand parents talking about themselves as "Dad"/"Nanna", always fill the
  author's own family block, describe a meal with no named food from the entry instead of
  borrowing another meal's food, and keep feelings people expressed. `openai/gpt-4.1` is the
  recommended facts and journal model for mixed-language entries.
- **Fix: Sarvam returned empty transcripts in Docker.** The upload's content type came from
  `mimetypes`, which knows no type for `.m4a` on the Linux image, so Sarvam got
  `application/octet-stream` and transcribed noise. Each supported extension now has a fixed
  type (`.m4a` → `audio/x-m4a`). An empty Sarvam transcript is now a capture warning.
- **`date` field (`YYYY-MM-DD`) on `POST /recordings` and `POST /notes`** (ADR 0017): form
  field or JSON key, next to `captured_at`; files the capture
  under that day (day file, audio name, confirmation message); kept in the inbox manifest for
  retries. Empty or missing: the day of `captured_at` (default now) in `LUMITRACE_TIMEZONE`, as
  before. Malformed or future dates get `422`.
- **Sarvam speech to text** (`LUMITRACE_STT_PROVIDER=sarvam`, ADR 0015) for Indian languages
  mixed with English: Saaras batch jobs (recordings up to 2 hours) give the transcript in
  `LUMITRACE_SARVAM_MODE` (default `codemix`: English words in English, the rest in its own
  script) and, at the same time, an **English translation** of the audio
  (`LUMITRACE_SARVAM_TRANSLATE`). Family names and `LUMITRACE_STT_KEYTERMS` are sent as
  keyterms so names come out right. A failed translation only adds a warning. New settings:
  `LUMITRACE_SARVAM_API_KEY`, `LUMITRACE_SARVAM_MODEL`, `LUMITRACE_SARVAM_MODE`,
  `LUMITRACE_SARVAM_TRANSLATE`, `LUMITRACE_STT_KEYTERMS`.
- **Prompts `extract_facts` v3, `write_journal` v2, `journal_addendum` v2** (ADR 0016): the
  model is told who is speaking and how each family member is related (`{{author}}`,
  `{{family}}` from `LUMITRACE_FAMILY=Sam (me), Maya (wife), Leo (son)`), gives every action to
  the person who did it, resolves words like "Dad" or "Amma" from the speaker's point of view,
  reads the English translation for meaning and the original for names, never turns a misheard
  phrase into a fact, fills the owner's own family block, and (journal) follows the entries
  over the extracted facts and only uses Morning/Afternoon/Evening when the entries say so.
  Captures with a translation are shown to the AI as the translation, then the original.
- Documented that an empty `LUMEN_STT_LANGUAGE` lets the speech model detect the language per
  recording, for mixed speech such as Telugu and English (`.env.example`, `docs/prism.md`).
- Prompt `extract_facts` v2: extracts `places` and per-member `family` facts for the names in
  `LUMEN_FAMILY` (new `{{family}}` placeholder); anyone else is dropped and names are spelled as
  configured (`keep_family`). Every configured member gets a block, empty if the day says
  nothing about them. Meal types in the prompt are the fixed five. Additive generation also
  merges places and family blocks, and late additions go under `## Later`.

### Spectrum (indexer)

- Indexes `places` and `family_facts` from the day file's "At a glance" section; facts
  passages are that section's rendered text without its `none` lines, one passage per heading
  (one per family member with facts).
- Rebuilds automatically when the index's schema version differs from the current one.
- A recording's English translation is indexed as extra transcript passages
  (`HH:MM · Log My Day · English`), so English searches find days spoken in another language.

### Lens (MCP server)

- **OAuth sessions end after 7 days** (`LUMITRACE_MCP_SESSION_DAYS`, decision 0034): refreshing
  no longer extends a connection; each AI app asks for the owner password again 7 days after
  signing in. The password page says so. Tokens saved earlier count as signed in at the next
  start. Production no longer sets the static `LUMITRACE_MCP_AUTH_TOKEN`.
- **OAuth is the only login** (decision 0035): the `token` mode and `LUMITRACE_MCP_AUTH_TOKEN`
  are removed, and `LUMITRACE_MCP_AUTH_MODE` defaults to `oauth`. Cursor and `mcp-remote`
  connect with the URL only and run the password sign-in. `none` remains for local-only use.
  A leftover `LUMITRACE_MCP_AUTH_TOKEN` is ignored; `LUMITRACE_MCP_AUTH_MODE=token` no longer
  starts.
- **Private admin API for connected apps** (decision 0036): with OAuth, `lumitrace-lens` also
  serves `/admin/apps` (list, disconnect one, disconnect all) on `LUMITRACE_MCP_ADMIN_HOST` /
  `LUMITRACE_MCP_ADMIN_PORT` (default `127.0.0.1:8003`, never published; Compose exposes it
  to the `prism` service only), guarded by `LUMITRACE_API_TOKEN`. The OAuth state now also
  records when each app last used the Lens.

- `get_day` returns each capture's English `translation` (or `null`).

- `query_facts` kinds `places` and `family` (replacing `family_events`), with a `person`
  filter for family and aggregates `by_place`, `by_person_and_category` and `top_items`.
  `on_this_day` returns `places` and `family` rows.

## [0.1.0] - 2026-10-10

Released as **LifeLog**; the names below are the ones it shipped with (see *Unreleased* for the
renames to Bookshelf and then Lumen).

First working version: record on the iPhone, get a Markdown day file in storage, read it in
Obsidian, ask through MCP. Tested offline end to end; not yet verified with real providers, real
Google Drive, the iPhone Shortcuts on a device or the Claude/ChatGPT connectors.

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
- Entry points `lifelog-api`, `lifelog-indexer`, `lifelog-mcp`, `lifelog-gdrive-login`.
- Dockerfile (Python 3.12 slim, ffmpeg, uv) and docker-compose with api, indexer and mcp sharing
  a data volume; only the API and MCP ports are published (the indexer's `/nudge` stays inside
  the Compose network).
- Dependencies: `boto3` declared explicitly (Amazon Transcribe); `mcp>=2.0` (the code uses the
  2.x `MCPServer` API).
- Docs: AGENTS.md, README, architecture, contracts, day-file format, index schema, decisions
  0001–0006, runbook, learnings, prompts README.

### Recording API

- `POST /recordings` (multipart: `audio`, `photos`/`photos[]`, `lat`, `lon`, `place`,
  `captured_at`, `capture_id`) and `POST /notes` (`text` and/or an `audio` clip and/or photos;
  multipart, urlencoded or JSON) with bearer-token auth (constant-time, fails closed with `503`
  when the token is missing, `change-me` or shorter than 16 characters). `202` with the capture
  id, entry date and a notification message.
- `GET /captures/{id}` status and `POST /captures/{id}/retry`; `GET /health` unchanged.
- Durable inbox: uploads saved to `_system/inbox/<id>/` (manifest last) and a status file in
  `_system/captures/` before answering; one background worker processes captures in order,
  retries failures after 60 s and 10 min, and resumes the inbox on start-up. Client
  `capture_id`s make retries idempotent (`200 duplicate`).
- Pipeline (`lifelog/pipeline/`): speech to text via `litellm`, `aws_transcribe` (S3 batch job
  with cleanup) or `fake`; audio compressed to mono AAC `.m4a` with ffmpeg → afconvert → original
  kept with a warning; photos (incl. HEIC) resized to JPEG without EXIF and numbered with
  `next_photo_names`; transcript saved to the day file before any AI step.
- AI steps through LiteLLM with JSON validated against `DayFacts`, per-task model plus fallback
  model (also on invalid replies) and an offline `fake` model. Unedited days are fully
  regenerated (`apply_generation`, title with a headline); edited days get additive facts and a
  journal addendum (`merge_generation_additive`); the day is re-read before writing so edits
  made during generation are kept. `prompt_version` and `models_used` recorded in front matter;
  `_system/generated/` snapshot written with every day-file write.
- Prompts `prompts/extract_facts/v1.md`, `write_journal/v1.md`, `journal_addendum/v1.md` (system
  and user parts, `{{placeholders}}`).
- Activity records: one JSON line per attempt in `_system/activity/YYYY/MM.jsonl` with models,
  prompt versions, per-step timings, LiteLLM cost and content-free errors.
- Indexer nudged after each capture (failures recorded, never fatal).
- Docs: `docs/recording-api.md`, `docs/iphone-shortcuts.md` (Log My Day, Quick Note, Send
  pending, share sheet, nightly reminder, triggers, Tailscale/HTTPS, token handling), decisions
  0010–0014, prompts README, runbook and learnings.

### Indexer

- `lifelog-indexer` with `run` (poll loop, `POST /nudge` → 202, `GET /health`, daily backup),
  `sync` (`--full`), `rebuild` and `backup`; JSON summaries, exit 1 on transient failures.
- Incremental sync from the storage change token; skips unchanged files by modification time and
  content hash; handles deletions; retries transient failures (`meta.indexer_retry_paths`);
  daily full scan repairs missed changes; a rejected token falls back to a full scan.
- Day files indexed in one transaction each: `days`, fact tables (meal types lower-cased),
  passages (title, facts, journal/notes by heading, transcript per capture; max 1,000 chars),
  FTS5 and sqlite-vec rows. Unchanged passages reuse their vectors.
- Malformed day files are logged (path and error type only) and keep their last good index.
- Edit signals: live file vs `_system/generated/` snapshot, per fact / title / journal / notes /
  transcript capture, with unified diffs; only for the same `generated_at`; one row per baseline.
- Automatic rebuild when the embedding model or dimension changes; feedback and edit signals kept.
- Index backup to `_system/index-backup/lifelog.sqlite` with SQLite's backup API.
- Docs: `docs/indexer.md`, decisions 0020–0024, runbook steps for rebuilding, recovering a lost
  index and changing the embedding model.

### MCP server

- `lifelog-mcp` replaces the placeholder: tools `search`, `get_day`, `query_facts`,
  `on_this_day` and `feedback`, with server instructions to answer only from the entries, cite
  dates and say when nothing was found. Dates are `YYYY-MM-DD` (plus `today` / `yesterday`, and
  `MM-DD` for `on_this_day`).
- `search`: FTS5 bm25 + sqlite-vec cosine merged with reciprocal rank fusion; date filters in
  SQL on both sides; keyword-only fallback when embedding fails or the model differs.
- `get_day` reads the day file from storage and returns private audio/photo links;
  `query_facts` returns rows plus counts and aggregates; `feedback` writes the `feedback` table
  and a JSON copy under `_system/feedback/`.
- Per-call read-only index connections; missing or empty index returns a friendly note.
- Transports stdio and streamable HTTP; auth modes `none`, `token` (bearer) and `oauth`
  (single-owner OAuth 2.1: dynamic client registration, PKCE, password page, refresh rotation,
  revocation, hashed tokens persisted next to the index). `GET /health`.
  `lifelog-mcp --transport stdio` and `lifelog-mcp reset-oauth`.
- `tests/test_entrypoints.py`: the MCP check now lists the five tools instead of `ping`.
- Docs: `docs/mcp-server.md` (tools, auth, Claude / ChatGPT / Claude Desktop / Cursor setup,
  privacy), decisions 0030–0033, runbook steps for tokens, OAuth reset and troubleshooting.

### Integration

- `tests/e2e/test_full_flow.py`: the three programs in-process on local storage with offline
  providers. Captures (recording with photo, notes, one from last year) go through the API; the
  indexer is updated only by the API's real `/nudge` calls; every MCP tool is called over MCP and
  finds the content under the right date; an owner edit yields edit signals; a later capture for
  the edited day is merged additively and the edit (and its signals) survive.
- The recording API now refuses placeholder and short tokens like the MCP server does (it only
  logged a warning before, so `change-me` from `.env.example` was accepted).
- Docs: README quick start, AGENTS.md status and cross-component rules, architecture, the full
  `_system/` layout in `docs/contracts.md` (activity records are in `_system/activity/`, not
  `_system/runs/`), `.env.example` notes on token refusal and the `fake` models, and a
  first-run checklist in `docs/runbook.md`.
