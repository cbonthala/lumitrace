# Test cases in plain English

This is a catalog of every automated test in `tests/`. Each test gets one line that says what it
checks, written so you don't need to read the code. The small code name at the end of each line
is the test's name, so you can find it in the file listed under the section heading.

## What the tests cover

The tests check the three Lumitrace programs and the shared pieces they rely on:

* the **Prism** (recording API), which receives recordings, notes and photos from the
  Flash shortcuts on the iPhone and writes the day's journal file;
* the **Spectrum** (the indexer), which reads the journal files and keeps a small search index up
  to date;
* the **Lens** (MCP server), which lets AI apps such as Claude search and read your
  journal;
* the shared building blocks: the **Frames** (the day file format and **storage**, a local folder
  or Google Drive), the **index schema**, settings and small helpers.

One end-to-end test runs all three programs together, from a phone upload to an AI question.

**Everything runs offline.** No test talks to a real AI provider, speech service or Google
Drive. Instead they use stand-ins: a "fake" speech-to-text that treats uploaded text as the
transcript, scripted fake AI models, fake embeddings, an in-memory imitation of Google Drive,
and a temporary local folder for storage. All names and journal content in the tests are
fictional.

How to run them (from the project folder):

```bash
export UV_PYTHON_INSTALL_DIR=$PWD/.tools/python UV_CACHE_DIR=$PWD/.tools/cache
.tools/bin/uv run pytest                          # all tests
.tools/bin/uv run pytest tests/e2e                # just the end-to-end story
.tools/bin/uv run pytest tests/prism/test_auth.py # one file
```

Two tests skip themselves when the computer lacks a tool: the real audio compression test
(needs ffmpeg or afconvert able to make AAC audio) and the HEIC photo test (needs a HEIC
encoder). Tests marked `network`, which would need real credentials, are skipped unless
`LUMITRACE_RUN_NETWORK_TESTS=1` is set. There are none at the moment.

**Keeping this up to date.** `tests/test_docs_test_cases.py` fails if a test exists that is not
described here (or a test described here no longer exists). When you add or change a test,
add or update its line in the right section.

### A few words used below

* **Capture**: one thing sent from the phone: a *Log My Day* recording or a *Quick Note*.
* **Day file**: the Markdown journal file for one day, e.g. `2026/10/2026-10-10/2026-10-10.md`.
  It has **front matter** (the date, audio, photos and which AI made it), a title, an **At a
  glance** section with the facts (mood, food, places, people, activities, one block per family
  member, highlights), the journal, your own **My notes** section, and the raw **transcript**
  of each capture.
* **Entry date**: the day a capture belongs to. Anything before 4 a.m. counts as the day before.
* **Snapshot**: an exact copy of the day file as Lumitrace last wrote it, kept in
  `_system/generated/`. Comparing it with the live file shows what you edited.
* **Index**: a SQLite database Spectrum builds from the day files so they can be searched.
  It can always be rebuilt from the day files.
* **Passage**: a short piece of a day file (a journal section, a transcript entry, the facts)
  stored in the index for searching.
* **Embedding**: a list of numbers that captures the meaning of a passage, used for "search by
  meaning" in addition to keyword search.
* **Nudge**: a small message from the Prism telling Spectrum "these files just
  changed, index them now".
* **Edit signal**: a record that you changed something Lumitrace wrote (for example the mood or a
  journal sentence), used to improve Lumitrace later.
* **MCP**: the protocol AI apps use to call Lumitrace's tools (`search`, `get_day`,
  `query_facts`, `on_this_day`, `feedback`).

## Contents

| Component | Covered | Not covered |
|---|---|---|
| [End-to-end flow](#end-to-end-flow) | A recording and notes travel from upload to day file, index and every AI tool; your edit survives a later capture | Real providers, real Google Drive, iPhone Shortcuts on a device, real AI apps |
| [Prism](#prism-recording-api-and-processing-pipeline) | Login, uploads, entry dates, retries, never overwriting edits, AI fallbacks, audio, photos, speech-to-text options, prompts, activity records | Real speech and AI providers, real AWS, real ffmpeg/afconvert output quality (one optional test), HEIC files from a real iPhone |
| [Spectrum](#spectrum-the-indexer) | Incremental and full sync, passages, edit signals, rebuilds, backups, the nudge service, the command line | Real Google Drive change feed, real embedding providers, long-running polling over days |
| [Lens](#lens-the-mcp-server) | All five tools, hybrid search, dates, feedback, token and OAuth logins | The real Claude, ChatGPT and Cursor connectors; answer quality of a real AI app |
| [Frames: day files](#frames-day-files) | Paths, the 4 a.m. rule, reading and writing without losing anything, spotting your edits, merge rules | Opening the files in Obsidian |
| [Frames: storage](#frames-storage) | Local folder storage and Google Drive storage against an in-memory imitation | The real Google Drive API, the `lumitrace-drive-login` sign-in |
| [Index schema](#index-schema) | Tables, keyword and vector search, clean-up rules, what survives a reset | Index size and speed with years of entries |
| [Config and shared helpers](#config-and-shared-helpers) | Settings, `.env.example`, fake embeddings, nudges, the Bruno collection, this catalog's completeness | Real embedding providers, running the collection in the Bruno app |
| [Entry points](#entry-points) | The programs start and their commands exist | Running them in Docker |

---

## End-to-end flow

**Covered:** the whole chain on one computer, with fake providers. **Not covered:** real
providers, real Google Drive, the iPhone Shortcuts and real AI apps.

### The full journey of a day

File: `tests/e2e/test_full_flow.py`

All three programs run inside the test, sharing one temporary storage folder. Speech-to-text
is the fake one (the uploaded bytes are the "spoken" words), fact extraction is a scripted
stand-in, the journal is written by the built-in `fake` model, and audio compression behaves as
on a computer without audio tools (the original file is kept). Only Leo is listed as family
(`LUMITRACE_FAMILY`). The story:

1. **Capture.** At 9:30 p.m. on Saturday, October 10, 2026, a *Log My Day* recording about a
   morning run with Maya arrives with a photo and a location (Austin). Then a quick note about
   fish tacos at lunch, and a note dated October 10, 2025 about a pumpkin patch trip. Each one
   is accepted, processed and gets a full journal. The audio is kept as a `.wav` file with an
   "audio kept uncompressed" warning, the photo is saved as `photo-01.jpg`, and every nudge to
   the indexer is accepted.
2. **The day file.** The snapshot is identical to the day file. The entries are in time order,
   the mood comes from the extracted facts, the lake is listed under Places, empty facts say
   "none" (Snacks), Maya gets no family block (she is not listed as family) while Leo gets an
   empty one, the journal mentions the tacos, the audio is stored
   in the day's folder, and the upload inbox is empty again. The activity record names the
   capture but contains none of the journal's words.
3. **Index.** Without any polling, the nudges alone bring both days into the index, and the day
   is not marked as edited.
4. **Ask.** Through a real MCP client, each tool is called the way an AI app would:
   * `search` for "fish tacos" puts October 10, 2026 first (found by keyword), and "pumpkin
     patch" finds October 10, 2025;
   * `get_day` returns the people, both transcripts in time order, the location as
     "Austin (30.26720, -97.74310)", and links to the audio and the photo;
   * `query_facts` finds the fish-taco lunch, the 40-minute run and the lake;
   * `on_this_day` finds last year's pumpkin-patch day, "1 year ago", with its highlight;
   * `feedback` is saved in the index and in storage, with the date picked out of the answer.
5. **You edit the day in Obsidian.** The mood changes from "content" to "great" and a sentence
   ("Best tacos in town, honestly.") is added to the summary. After a nudge, the indexer records
   two edit signals (mood before and after, and the journal change) and marks the day as edited.
6. **A late capture.** A note at 10:15 p.m. about a walk with Leo is added *on top of* the
   edited day: the mood is still "great", your sentence is still there, the new note appears
   under "## Later" labelled "22:15 · Quick Note", Leo is added to the people and his family
   block gains the walk and "saw the stars", the day has three entries, and the snapshot is updated to match.
7. **Ask again.** Searching "stars" on that day finds it, `query_facts` finds Leo among the
   people and lists his walk and moment under family, and the earlier edit signals are still
   there.

- Checks that the story above works from start to finish across all three programs. <sub>`test_full_flow`</sub>

---

## Prism: recording API and processing pipeline

**Covered:** logging in, the Flash web app's sign-in and summary, sending recordings and notes, entry dates, retries and recovery, never
overwriting your edits, AI fallbacks, audio and photo handling, speech-to-text options, prompts
and activity records. **Not covered:** real speech and AI providers, real AWS, real iPhone
Shortcuts and HEIC photos straight from a phone, and the web app's JavaScript (recording,
offline queue) in a real browser.

### Logging in to the API

File: `tests/prism/test_auth.py`

- Checks that the health page answers without a token (password). <sub>`test_health_needs_no_token`</sub>
- Checks that sending a note without a token is refused (401) and the reply says a bearer token is needed. <sub>`test_missing_token_is_rejected`</sub>
- Checks that a wrong token, the wrong login type ("Basic"), a token without the word "Bearer", or an empty token are all refused, including when looking up a capture. <sub>`test_wrong_token_and_scheme_are_rejected`</sub>
- Checks that the right token is accepted, even when the header and the word "bearer" are written in lower case. <sub>`test_right_token_is_accepted`</sub>
- Checks that if the server has no token configured, every request is refused with 503 ("not set up") instead of being let through. <sub>`test_unconfigured_token_fails_closed`</sub>
- Checks that a placeholder token (`change-me`) or one that is too short also makes every request fail with 503, while the health page keeps working. <sub>`test_placeholder_or_short_token_fails_closed`</sub>
- Checks that the token rule flags an empty, placeholder or short token and accepts a long random one. <sub>`test_token_problem`</sub>

### The Flash web app

File: `tests/prism/test_flash.py`

- Checks that the web app page opens without signing in, has its Home Screen icon and app manifest, sends a security policy that stops other sites from framing it, that `/flash` and `/` lead to it, and that its script, styles, offline helper and icons are served. <sub>`test_web_app_is_served_without_a_login`</sub>
- Checks that the app has a Design page and a button that opens it, that the page shows the "How it works" diagram once, and that the diagram is served as an image naming the Flash, Prism, Frames, Spectrum and Lens, with no script inside. <sub>`test_how_it_works_diagram_and_design_page`</sub>
- Checks that signing in is refused (503, naming the settings to fill in) while no username and password are configured, and that the app is told sign-in is not available. <sub>`test_sign_in_is_off_until_configured`</sub>
- Checks that the right username and password set a session cookie that scripts cannot read, is only sent to this site and over HTTPS, and lasts 90 days; and that with it the app can send a note, follow its status, read the weekly summary and list recent captures, just like with the token. <sub>`test_sign_in_sets_a_session_cookie_that_works_like_the_token`</sub>
- Checks that a wrong username or password is refused without a cookie, and that after five wrong attempts even the right password is refused for a while (429). <sub>`test_wrong_password_and_lockout`</sub>
- Checks that an expired, altered, made-up or empty session cookie is refused, and that changing the password signs out every browser that signed in with the old one. <sub>`test_bad_or_old_sessions_are_refused`</sub>
- Checks that another website cannot use the owner's signed-in browser to send something (403), while reading still works, the app itself can send, the token keeps working, and signing in from another site is refused. <sub>`test_cross_site_requests_with_a_session_are_refused`</sub>
- Checks that signing out tells the browser to delete the session cookie. <sub>`test_logout_clears_the_cookie`</sub>
- Checks that sign-in counts as not set up when the username is blank, the password is a placeholder or too short, or the API token is too short, and that a session cannot be valid while sign-in is off. <sub>`test_login_problem`</sub>
- Checks that the recent-captures list needs a login, shows the newest capture first with its status and no journal text, and respects the limit and the allowed number of days. <sub>`test_recent_captures_newest_first`</sub>
- Checks that the weekly summary counts the days with a day file in the last seven days, the entries in them, and the streak of days in a row up to today. <sub>`test_week_summary_counts_days_captures_and_streak`</sub>
- Checks that the streak still counts while today has no entry yet, carries across the end of a month, drops to zero after a missed day, and that an empty journal gives all zeros. <sub>`test_streak_waits_for_today_and_crosses_months`</sub>

### Connected AI apps in the Flash Settings tab

File: `tests/prism/test_lens_apps.py`

- Checks that listing, disconnecting one and disconnecting all AI apps need a login, that each is passed on to the Lens's private admin address with the API token, with an app id made safe for the address, and that there is no way to delete an app. <sub>`test_connected_apps_are_forwarded_to_the_lens`</sub>
- Checks that a Lens that refuses the API token or can't be reached gives 502 (never 401, which would sign the Flash app out), and that an unknown app gives 404. <sub>`test_lens_failures_never_look_like_a_flash_sign_out`</sub>
- Checks the Prism against the real Lens admin app: an empty list with the session length, 404 for an unknown app, and "nobody disconnected" when no app is connected. <sub>`test_connected_apps_against_the_real_admin_api`</sub>
- Checks that the Settings tab has the Connected AI apps card with its list and disconnect-all button, and that the app's script loads the list. <sub>`test_settings_tab_has_connected_apps`</sub>

### Sending a recording

File: `tests/prism/test_capture_api.py`

- Checks the whole path of one *Log My Day* recording with two photos and a location: the API answers at once with "queued", the capture id, the entry date and a friendly message ("Saturday, October 10"); once processed the status says "done"; the day file has the AI's title and journal, the people, meals, audio and photo names, prompt and model versions, and the transcript with its time and formatted location; the audio and photos are in the day's folder; the snapshot matches; the inbox is empty; and the indexer is nudged once with the day file, audio and photos. <sub>`test_recording_end_to_end`</sub>

### Sending the same thing twice

File: `tests/prism/test_capture_api.py`

- Checks that re-sending a recording with the same capture id (for example when the phone retries after a dropped connection) is recognised as a duplicate, both while it is being processed and after it is done, and the day ends up with one entry and one audio file. <sub>`test_same_capture_id_is_stored_once`</sub>
- Checks that without a capture id every upload counts as new: two uploads in the same minute get different ids and two audio files (the second ending in `-2`). <sub>`test_without_capture_id_each_post_is_new`</sub>

### Which day an entry belongs to

File: `tests/prism/test_capture_api.py`

- Checks that a recording made at 1:30 a.m. goes into the previous day's journal (with the audio named by its clock time), while one at exactly 4:00 a.m. starts the new day. <sub>`test_rollover_before_4am_counts_as_previous_day`</sub>
- Checks that the capture time is understood whether it is sent without a timezone (taken as local time), in UTC, as a Unix timestamp, or left empty (meaning "now"). <sub>`test_captured_at_formats`</sub>
- Checks that a `date` field of `2026-10-08` files a recording made on Oct 10 under Oct 8 (day file, audio name and the confirmation message), keeps its real capture time and leaves Oct 10 untouched; that notes accept `date` as a form field and in JSON; and that an empty `date` falls back to the capture time's day. <sub>`test_date_field_chooses_the_day`</sub>
- Checks that a `date` that is not a real `YYYY-MM-DD` date, or is after today, is refused with 422. <sub>`test_date_field_validation`</sub>

### Quick notes

File: `tests/prism/test_capture_api.py`

- Checks that a typed note sent after a recording joins the same day file, entries stay in time order, and the journal and facts are rewritten using both entries. <sub>`test_note_merges_into_the_same_day`</sub>
- Checks that a note can be sent as a web form with text, or as a short audio clip that is transcribed and keeps its audio file. <sub>`test_note_as_form_and_as_audio_clip`</sub>
- Checks that a note with only a photo is accepted: the photo is saved and listed on the day, and the AI writing step is skipped because there are no words. <sub>`test_photo_only_note`</sub>

### Refusing bad requests

File: `tests/prism/test_capture_api.py`

- Checks that bad input is refused with a clear error: a recording without audio, a note without text, a capture id that tries to leave its folder (`../`), a latitude that isn't a number or is out of range, a time like "yesterday", a list instead of a form, plain text instead of a form or JSON (415), and an unknown or folder-escaping capture id when asking for a status (404). <sub>`test_validation_errors`</sub>
- Checks that an upload larger than the configured size limit is refused (413). <sub>`test_upload_size_limit`</sub>

### Retries and recovering after a crash

File: `tests/prism/test_capture_api.py`

- Checks that if speech-to-text fails once (service unreachable), the capture is retried automatically and finishes, after two attempts and with one entry in the day. <sub>`test_failed_capture_is_retried_automatically`</sub>
- Checks that when every automatic retry fails, the capture is marked "failed" with the error and nothing is written to the day; a manual retry is accepted (and fails again while the service is down); re-sending it after the service is back works and is not treated as a duplicate; retrying a finished capture is refused (409); and the day has one entry. <sub>`test_exhausted_capture_can_be_resent_or_retried`</sub>
- Checks that after a crash or restart, captures left in the inbox (half processed, still queued, or saved without a status) are processed on start-up, while an incomplete upload with no list of its files is left alone. <sub>`test_inbox_is_resumed_on_startup`</sub>

### How locations are written

File: `tests/prism/test_capture_api.py`

- Checks that the location shown in the journal combines the place name and coordinates neatly, works with only coordinates or only a name (tidying spaces and line breaks), and is left out when there is nothing useful to show. <sub>`test_format_location`</sub>

### Never overwriting your edits

File: `tests/prism/test_pipeline.py`

- Checks that after you edit a day (your own journal words, mood and notes), a later note does not rewrite it: your text, mood and notes stay, a short AI addition is appended under "## Later", labelled with the note's time, new people are added, the AI is shown your edited journal, and fact extraction only looks at the new entry. <sub>`test_edited_day_gets_additive_update`</sub>
- Checks that if you edit the day while the AI is still writing, the AI's version is not saved over yours; the new entry is added on top instead. <sub>`test_edit_during_generation_is_not_overwritten`</sub>

### When speech or AI services fail

File: `tests/prism/test_pipeline.py`

- Checks that when the main AI model is down or replies with something that isn't valid data, the backup model is used, the day file records which model did the work, and the activity record lists each attempt and why it failed. <sub>`test_fallback_model_is_used_and_recorded`</sub>
- Checks that when every AI model fails, the transcript is still saved in the day file (with an empty journal), the snapshot is written, and the errors are reported. <sub>`test_ai_failure_still_saves_the_transcript`</sub>
- Checks that if speech-to-text fails, nothing is written to the journal folders and the activity record shows the failure. <sub>`test_transcription_failure_writes_nothing`</sub>
- Checks that an English translation from speech-to-text is saved with the recording's transcript in the day file, and that speech-to-text warnings and the translation length appear in the activity record. <sub>`test_translation_is_saved_with_the_transcript`</sub>
- Checks that if the indexer can't be reached, the capture still succeeds. <sub>`test_nudge_failure_does_not_fail_the_capture`</sub>

### Repeated, empty and offline captures

File: `tests/prism/test_pipeline.py`

- Checks that processing the same capture again (for example after a crash) does not add a second entry or audio file; it only regenerates the journal and says so in a warning. <sub>`test_reprocessing_a_saved_capture_does_not_duplicate_it`</sub>
- Checks that when a recording contains no words, the AI steps are skipped entirely. <sub>`test_empty_transcript_skips_generation`</sub>
- Checks that the built-in `fake` AI model writes a simple journal (the note's text under "Summary") without any provider, so Lumitrace can be tried offline. <sub>`test_fake_llm_model_runs_offline`</sub>

### Activity records

File: `tests/prism/test_activity.py`

- Checks that each capture adds exactly one line to the monthly activity log with its id, status, date, models, prompt versions and how long each step took (compress audio, transcribe, write the day, extract facts, write the journal, write again, nudge), and that no names, places, transcript or journal words ever appear in it. <sub>`test_one_line_per_capture_without_content`</sub>
- Checks that the AI cost of each step is added up into a total. <sub>`test_cost_is_summed_when_known`</sub>
- Checks that a failing step is marked as failed with a short error message, and the error is still passed on. <sub>`test_failed_step_is_recorded_and_reraised`</sub>
- Checks that the log file is named by year and month and new records are added after the existing ones. <sub>`test_append_keeps_existing_lines`</sub>
- Checks that if storage is down, writing the activity record quietly gives up instead of breaking the capture. <sub>`test_append_never_raises`</sub>
- Checks that error messages saved in the log never include AI output or journal text (such as a name inside a validation error) and are kept short. <sub>`test_safe_error_hides_model_output`</sub>

### Audio

File: `tests/prism/test_media.py`

- Checks that without any audio tools installed the original audio is kept (with a warning), and the file extension is kept or sensibly chosen (`.mp4` becomes `.m4a`, no extension becomes `.audio`). <sub>`test_no_compressor_keeps_original`</sub>
- Checks that if ffmpeg fails, macOS's afconvert is tried next, and that both are asked for single-channel AAC audio at the configured quality. <sub>`test_ffmpeg_failure_falls_back_to_afconvert`</sub>
- Checks that if both tools fail (for example they time out), the original is kept and the warning names both failures. <sub>`test_all_compressors_failing_keeps_original`</sub>
- Checks that an `.m4a` file that is already smaller than the "compressed" result is kept as it is, without a warning. <sub>`test_m4a_original_smaller_than_output_is_kept`</sub>
- Checks with the real tools that a 2-second WAV recording becomes an `.m4a` file at least ten times smaller (skipped when no installed tool can make AAC audio). <sub>`test_real_compressor_makes_mono_m4a`</sub>
- Checks that when audio can't be compressed, it is stored under its original extension (`.wav`), the day file points to it, a warning is returned, and the activity record says no compressor was used. <sub>`test_processor_keeps_uncompressed_audio_with_its_extension`</sub>

### Photos

File: `tests/prism/test_media.py`

- Checks that large photos are shrunk to the maximum size (keeping their proportions) and saved as JPEG, while small ones are not enlarged. <sub>`test_resize_fits_max_dimension_as_jpeg`</sub>
- Checks that photos are turned upright using the camera's orientation tag, and that hidden metadata (including the GPS location) is removed. <sub>`test_resize_applies_exif_rotation_and_strips_exif`</sub>
- Checks that see-through images are turned into normal colour images, since JPEG has no transparency. <sub>`test_resize_flattens_transparency`</sub>
- Checks that iPhone HEIC photos are read and converted to JPEG (skipped when no HEIC encoder is available to make a test photo). <sub>`test_resize_reads_heic`</sub>
- Checks that a file that is not an image is refused. <sub>`test_resize_rejects_non_images`</sub>
- Checks that photos are numbered in order across captures of the same day (`photo-01`, then `photo-02` and `photo-03`), a broken photo is skipped with a warning, and saved photos are resized. <sub>`test_processor_numbers_photos_and_skips_bad_ones`</sub>

### Speech-to-text options

File: `tests/prism/test_stt.py`

- Checks that the offline fake speech-to-text returns uploaded text as the transcript (trimmed), and a placeholder such as "(fake transcript of 9 bytes of audio)" for real audio. <sub>`test_fake_transcriber`</sub>
- Checks that the LiteLLM option passes the configured model, language and audio file to the provider and trims the result. <sub>`test_litellm_transcriber_passes_settings`</sub>
- Checks, against an imitation of Amazon's services, that the AWS option uploads the audio, starts a job with the right format and language, waits for it, reads the transcript and deletes every file it created. <sub>`test_aws_transcribe_round_trip_and_cleanup`</sub>
- Checks that a failed AWS job still cleans up its files and reports the failure, and that an audio format AWS can't read is refused up front. <sub>`test_aws_transcribe_failure_still_cleans_up`</sub>
- Checks how the language setting is passed to AWS: a full code like "en-GB" as is, "es" as US Spanish, and an empty setting as "detect the language". <sub>`test_aws_language_options`</sub>
- Checks, against an imitation of Sarvam's batch service, that the Sarvam option runs a transcript job and a translation job on the same upload, sends the model, mode, Telugu language code and the family names plus extra keyterms, keeps the API key away from the file-storage links, uploads `.m4a` as `audio/x-m4a` (Sarvam returns an empty transcript for a generic type), and returns both texts. <sub>`test_sarvam_transcript_and_translation`</sub>
- Checks that an empty Sarvam transcript is reported as a warning (so it shows in the capture status) and that `.mp3` is uploaded as `audio/mpeg`. <sub>`test_sarvam_empty_transcript_is_a_warning`</sub>
- Checks the Sarvam options: translation can be turned off, keyterms are only sent to the v4 model, an empty language means "detect it", unsupported audio formats are refused, and a missing API key gives a clear error. <sub>`test_sarvam_options`</sub>
- Checks that when only Sarvam's translation fails, the transcript is still returned, with a warning that says why. <sub>`test_sarvam_failed_translation_keeps_the_transcript`</sub>
- Checks that a failed Sarvam transcript job raises an error with the reason, and that a refused upload reports only the HTTP status, never the secret upload link. <sub>`test_sarvam_failed_transcript_raises_without_leaking_urls`</sub>
- Checks that the speech-to-text setting picks the right option (fake, LiteLLM or Sarvam), and that choosing AWS without a storage bucket gives a clear error. <sub>`test_get_transcriber`</sub>

### Prompts and AI replies

File: `tests/prism/test_prompts_llm.py`

- Checks that all three AI instructions (extract facts, write the journal, write an addition) exist and are filled in completely with no `{{blanks}}` left, and that entries are shown to the AI with the date, weekday, time, entry type and location. <sub>`test_every_current_prompt_exists_and_renders`</sub>
- Checks that each prompt file has the expected layout and version label and tells the AI never to invent or guess. <sub>`test_prompt_files_follow_the_layout`</sub>
- Checks that a badly laid out prompt file, a missing value for a blank, or a missing prompt file give clear errors. <sub>`test_prompt_errors`</sub>
- Checks that the prompts folder is found in the project even when the program is started from another folder. <sub>`test_relative_prompts_dir_falls_back_to_repository`</sub>
- Checks that prompt versions are combined into one label (such as `extract_facts-v1+write_journal-v2`) for the day file. <sub>`test_combined_version`</sub>
- Checks that only the family members listed in the settings keep a family block: anyone else is dropped, names are spelled as in the settings ("leo" becomes "Leo"), they come in the settings' order, a name given twice keeps its first block, an empty list drops everyone, and every listed member the AI said nothing about gets an empty block. <sub>`test_keep_family_drops_unknown_names_and_uses_configured_spelling`</sub>
- Checks that the fact-extraction prompt tells the AI who is speaking and how each family member is related to them ("Sam (the author), Maya (the author's wife), Leo"), and says "(not given)" when nobody is marked "(me)". <sub>`test_extract_facts_sends_the_family_list`</sub>
- Checks that a recording with an English translation is shown to the AI as the translation first, then the original transcript as spoken. <sub>`test_captures_show_translation_and_original`</sub>
- Checks that the AI's structured (JSON) reply is understood even when wrapped in code fences or surrounded by chatty text, and refused when there is no data at all. <sub>`test_extract_json_tolerates_fences_and_chatter`</sub>
- Checks that extracted facts are held to the day-file format: a reply wrapped in a "facts" object is unwrapped, an out-of-range mood score and empty values are dropped, and badly shaped replies (not an object, a meal without a type) are refused. <sub>`test_parse_facts_validates_against_dayfacts`</sub>
- Checks that the AI client passes the timeout, retry and "reply in JSON" settings to the provider, switches to the backup model when the main one fails, records each attempt, tries a model only once when it is also the backup, and gives a clear error naming both models when all fail. <sub>`test_llm_client_passes_config_and_falls_back`</sub>

---

## Spectrum: the indexer

**Covered:** first and incremental syncs, deletions, broken files, retries, passages, edit
signals, rebuilds, backups, the nudge service and the command line. **Not covered:** the real
Google Drive change feed, real embedding providers and long-running polling.

### Keeping the index in step with storage

File: `tests/spectrum/test_sync.py`

- Checks that the first sync reads every day file and fills the index: day details (mood, city, audio, number of entries, not edited, prompt version), meals, people, places (searchable, "river trail"), activities, highlights, one row per family item (Leo's mood, food and moment, Maya's food and place), searchable passages with their embeddings, and a record of each file with its fingerprint. <sub>`test_first_sync_indexes_day_files`</sub>
- Checks that audio, photos, other Markdown notes, system files and stray files are not indexed or sent for embedding. <sub>`test_non_day_files_are_ignored`</sub>
- Checks that an unchanged file is skipped, and a file saved again with identical content is recognised by its fingerprint and not processed again. <sub>`test_unchanged_files_are_skipped`</sub>
- Checks that after a note is added to a day, only that new passage is sent for embedding, and it becomes searchable. <sub>`test_incremental_sync_reembeds_only_changed_passages`</sub>
- Checks that deleting a day file removes that day from the index (details, passages, keyword entries, embeddings) while other days and saved feedback remain. <sub>`test_deleted_day_file_is_removed`</sub>
- Checks that a full scan notices a day file that disappeared without storage reporting it, and removes it. <sub>`test_full_scan_drops_days_whose_files_vanished`</sub>
- Checks that a broken day file is skipped and logged by its path only (never its contents), is not retried until it changes, and is indexed once it is fixed. <sub>`test_malformed_file_is_logged_and_skipped`</sub>
- Checks that if an edit breaks a day file that was already indexed, the last good version stays searchable. <sub>`test_broken_edit_keeps_last_good_index`</sub>
- Checks that if a day file is copied into another day's folder, the folder's date wins over the date written inside the file. <sub>`test_front_matter_date_mismatch_uses_folder_date`</sub>
- Checks that a file that failed because the embedding service was briefly down is remembered and retried on the next sync, even though storage reports nothing new. <sub>`test_transient_failure_is_retried`</sub>
- Checks that paths sent in a nudge are indexed straight away, unsafe or non-day paths are ignored, unchanged ones are skipped, and deleted ones are removed. <sub>`test_index_paths_handles_nudged_paths`</sub>
- Checks that if the saved "where we left off" marker is unusable (for example from another storage type), the indexer falls back to a full scan. <sub>`test_bad_sync_token_falls_back_to_full_scan`</sub>

### Splitting days into searchable passages

File: `tests/spectrum/test_passages.py`

- Checks that the sample day is split, in order, into passages for the title, the facts (the mood lines, then Food, Places, People, Activities, one per family member, Highlights), each journal section, your notes and each transcript entry; headings are taken out of the text; the facts read as in the day file ("**Ate:** pasta" under Leo); and no passage is over the size limit. <sub>`test_sample_day_passages`</sub>
- Checks that the same text under different headings counts as different passages, and that the heading is part of what gets embedded. <sub>`test_text_hash_covers_heading`</sub>
- Checks that short paragraphs are kept together and long ones are split into pieces under the limit without losing any words. <sub>`test_chunk_text_packs_paragraphs_and_splits_long_ones`</sub>
- Checks that one enormous word is cut into fixed-size pieces, and blank text produces nothing. <sub>`test_chunk_text_hard_splits_giant_words`</sub>
- Checks that journal sections are found correctly: text before the first heading is kept, a heading with nothing under it (like "Sleep: 8 hours") is kept, and a `#` line inside a code block is not mistaken for a heading. <sub>`test_split_by_headings_ignores_code_fences_and_keeps_heading_only_sections`</sub>
- Checks that an empty day produces only a title passage and no facts. <sub>`test_empty_day_has_title_only`</sub>
- Checks that a recording's English translation becomes its own searchable transcript passage, headed "21:30 · Log My Day · English", right after the original. <sub>`test_translation_gets_its_own_transcript_passages`</sub>

### Learning from your edits (edit signals)

File: `tests/spectrum/test_edit_signals.py`

- Checks that nothing is recorded when the day file matches what Lumitrace last wrote. <sub>`test_no_signals_when_file_matches_snapshot`</sub>
- Checks that your changes to the mood, people, journal, notes, title and a transcript are each recorded separately with the before and after values (plus a line-by-line comparison for longer text) and the prompt and model versions that wrote the original, and that the day is marked as edited. <sub>`test_owner_edits_become_signals`</sub>
- Checks that saving the same edit again doesn't record it twice, a further edit to the same part replaces the earlier record, and undoing the edit removes it. <sub>`test_signals_are_deduplicated_and_superseded`</sub>
- Checks that a new entry added by Lumitrace (before its snapshot is updated) is not mistaken for your edit. <sub>`test_new_capture_is_not_an_edit`</sub>
- Checks that edits are not worked out against an out-of-date snapshot from an earlier generation. <sub>`test_stale_snapshot_is_not_compared`</sub>
- Checks that when only the snapshot changes, the edit records are worked out again without re-indexing the day. <sub>`test_snapshot_change_alone_refreshes_signals`</sub>
- Checks that rebuilding the index, or wiping its rebuildable parts, keeps the recorded edits without duplicating them. <sub>`test_rebuild_keeps_signals_without_duplicates`</sub>
- Checks that deleting a transcript entry counts as an edit (its text becomes empty). <sub>`test_deleted_capture_text_is_an_edit`</sub>
- Checks that text changes are shown in the standard "generated versus edited" comparison format. <sub>`test_text_diff_is_unified`</sub>

### Rebuilding the index

File: `tests/spectrum/test_rebuild.py`

- Checks that a rebuild repairs a damaged index (missing passages) by indexing every day again, while keeping feedback and edit records and noting when the rebuild happened. <sub>`test_rebuild_reindexes_everything_and_keeps_signals`</sub>
- Checks that changing the embedding size triggers an automatic rebuild on the next sync, after which search by meaning works at the new size, feedback is kept, and the MCP server can open the index with the new setting. <sub>`test_dimension_change_triggers_rebuild`</sub>
- Checks that switching to a different embedding model triggers an automatic rebuild and records the new model. <sub>`test_model_change_triggers_rebuild`</sub>
- Checks that an index made by an older Lumitrace (schema version 1) is rebuilt automatically on the next sync, fills in what the old version left out, records the new schema version, keeps feedback, and is not rebuilt again after that. <sub>`test_older_schema_version_triggers_rebuild`</sub>
- Checks that a rebuild with no day files works and records the embedding model. <sub>`test_rebuild_on_empty_storage`</sub>

### Backups

File: `tests/spectrum/test_backup.py`

- Checks that the backup in `_system/index-backup/` is a complete, self-contained copy of the index that opens on its own with days, passages and embeddings intact. <sub>`test_backup_writes_a_consistent_copy_to_storage`</sub>
- Checks that a backup is due at first, not again until a day has passed, and never when backups are turned off. <sub>`test_backup_is_due_by_interval`</sub>
- Checks that the backup file itself is not treated as a change to index. <sub>`test_backup_is_not_indexed`</sub>
- Checks that the indexer's regular cycle makes a backup when one is due and doesn't repeat it on the next cycle. <sub>`test_service_cycle_backs_up_when_due`</sub>

### The Spectrum service and nudges

File: `tests/spectrum/test_service.py`

- Checks the indexer's web endpoints: health reports the status and how many paths are waiting; a nudge is accepted (202) with or without paths and queues them; a badly formed nudge is refused. <sub>`test_health_and_nudge_queue`</sub>
- Checks that one indexer cycle indexes the nudged day and empties the queue. <sub>`test_run_once_indexes_nudged_paths`</sub>
- Checks that with the background worker running, a nudge gets a new day into the index promptly without waiting for the next poll, health shows the worker running with no errors, and the worker stops on shutdown. <sub>`test_worker_indexes_promptly_after_nudge`</sub>

### Spectrum command line

File: `tests/spectrum/test_cli.py`

- Checks that the `sync`, `rebuild` and `backup` commands work and print a short summary (a second `sync` finds nothing to do). <sub>`test_sync_rebuild_and_backup_commands`</sub>
- Checks that an unknown command is refused with the usual "wrong usage" exit code. <sub>`test_unknown_command_is_rejected`</sub>

---

## Lens: the MCP server

**Covered:** the five tools, hybrid search, date handling, feedback, the three login modes and
the full OAuth sign-in. **Not covered:** the real Claude, ChatGPT and Cursor connectors and the
quality of a real AI app's answers.

### The server and its instructions to AI apps

File: `tests/lens/test_server.py`

- Checks that the instructions given to AI apps say to answer only from what the tools return, cite the date, and say when nothing was found. <sub>`test_instructions_require_grounded_cited_answers`</sub>
- Checks that an AI app sees exactly the five tools, with the date format explained, the list of fact kinds, and only `feedback` marked as changing anything. <sub>`test_tools_are_listed_with_documented_dates`</sub>
- Checks each tool through a real MCP connection, that a bad date or unknown fact kind comes back as an error the AI can read, and that feedback ends up in the index. <sub>`test_tool_calls_over_mcp`</sub>
- Checks that before the index exists, search returns no results and a friendly "not been built" note rather than an error. <sub>`test_missing_index_over_mcp`</sub>
- Checks that the `reset-oauth` command deletes the saved sign-ins and tells you to reconnect your apps. <sub>`test_reset_oauth_command`</sub>

### Building a safe keyword search

File: `tests/lens/test_search.py`

- Checks that every word of a question is quoted in the keyword search, so search operators typed by the AI (AND, OR, NEAR, minus signs, wildcards) can't break it. <sub>`test_fts_expression_quotes_every_term`</sub>
- Checks that filler words ("what did I") are dropped unless the question has nothing else, and that punctuation alone gives no keyword search. <sub>`test_fts_expression_drops_stopwords_but_keeps_all_stopword_queries`</sub>
- Checks that awkward input (unbalanced quotes, "NOT", colons, accents) never causes a search error. <sub>`test_fts_expression_is_valid_fts5`</sub>

### Combining keyword and meaning results

File: `tests/lens/test_search.py`

- Checks that when keyword and meaning results are merged ("reciprocal rank fusion"), passages found by both rank above those found by one, with the expected scores, and each result remembers which method found it. <sub>`test_rrf_rewards_items_in_both_lists`</sub>
- Checks that ties are broken in a stable order, repeats in one list count once, and no lists give no results. <sub>`test_rrf_ties_are_deterministic_and_duplicates_ignored`</sub>
- Checks that the merge's smoothing constant can be changed. <sub>`test_rrf_respects_k`</sub>
- Checks that date limits are applied inside both the keyword and the meaning search, so results outside the range never appear. <sub>`test_keyword_and_vector_rankings_apply_date_filters`</sub>

### Searching your journal (`search`)

File: `tests/lens/test_search.py`

- Checks that searching "pumpkin patch" puts the right day first, with its date, section, heading, a snippet containing the word, the file path, a score and how it was found. <sub>`test_search_finds_the_right_day`</sub>
- Checks that results come in score order and the most relevant day ("grandma rose pasta") is first. <sub>`test_search_results_are_in_rrf_order`</sub>
- Checks that a "from" date, a "to" date, both, or the same day for both limit the results correctly. <sub>`test_search_date_filters`</sub>
- Checks that the result limit is respected. <sub>`test_search_limit`</sub>
- Checks that an empty question, a date not written as YYYY-MM-DD, or a "from" date after the "to" date are refused with a clear error. <sub>`test_search_bad_arguments`</sub>
- Checks that with no index, search returns nothing plus a note that the index is missing. <sub>`test_search_missing_index`</sub>
- Checks that with an empty index, search returns a note saying so. <sub>`test_search_empty_index`</sub>
- Checks that a damaged index file is treated as missing instead of crashing. <sub>`test_search_corrupt_index_is_treated_as_missing`</sub>
- Checks that if the embedding service is down, search still works with keywords only and says meaning search was unavailable. <sub>`test_search_falls_back_to_keywords_when_embedding_fails`</sub>
- Checks that if the index was built with a different embedding model, meaning search is skipped (keywords only) with a note. <sub>`test_search_skips_vectors_from_another_embedding_model`</sub>
- Checks that a search with no matches says "No matching entries". <sub>`test_search_reports_nothing_found`</sub>

### Snippets

File: `tests/lens/test_search.py`

- Checks that for long passages the snippet is centred on the matching word and trimmed with "…" at both ends. <sub>`test_snippet_centres_on_the_first_term`</sub>
- Checks that short passages are shown whole, with line breaks tidied. <sub>`test_snippet_short_text_is_whole`</sub>

### Dates the tools accept

File: `tests/lens/test_tools.py`

- Checks that dates are accepted as YYYY-MM-DD (extra spaces ignored), "today" or "yesterday" in any case, and that other forms ("10/10/2026", month 13, "last tuesday", no dashes, empty) are refused. <sub>`test_parse_date_formats`</sub>
- Checks that month-day dates for `on_this_day` ("10-10" or "--02-29") are understood, a full date is not mistaken for one, and month 13 is refused. <sub>`test_parse_month_day`</sub>

### Reading a whole day (`get_day`)

File: `tests/lens/test_tools.py`

- Checks that `get_day` returns the full day: path, title, facts, journal, notes, transcript entries in time order with times, text and translation (none here), a link to the audio, and photo links (with a "file not found" note for a photo missing from storage). <sub>`test_get_day_returns_everything`</sub>
- Checks that asking for a day without an entry returns "not found" with a note. <sub>`test_get_day_missing_day`</sub>
- Checks that `get_day` reads straight from storage, so it works even without an index. <sub>`test_get_day_works_without_index`</sub>
- Checks that a date like "October 10" is refused. <sub>`test_get_day_bad_date`</sub>

### Facts across days (`query_facts`)

File: `tests/lens/test_tools.py`

- Checks that searching meals for "PASTA" (any case) lists each matching day newest first, with counts (rows, days, first and last date), the most common items, and a flag saying nothing was cut off. <sub>`test_query_facts_meals`</sub>
- Checks that meal searches also match the meal type ("breakfast"), and that all meals can be summarised per meal type. <sub>`test_query_facts_meals_match_meal_type_and_aggregate`</sub>
- Checks that activities are totalled and averaged per kind (three runs, 115 minutes, 38.3 on average), treating "Run" and "run" as the same. <sub>`test_query_facts_activities`</sub>
- Checks that date limits apply to facts too (a total for 2026 only, a single-day range). <sub>`test_query_facts_date_filter`</sub>
- Checks that people are summarised by how many days you saw them and the first and last date, and that part of a name ("rose") is enough to search. <sub>`test_query_facts_people`</sub>
- Checks that mood results list each day's mood and summarise the average, lowest and highest score and how often each mood came up. <sub>`test_query_facts_mood`</sub>
- Checks that places are listed newest first in the order of the day file, summarised by how many days you went there and when first, and searchable by part of the name ("farm"). <sub>`test_query_facts_places`</sub>
- Checks that family facts can be narrowed to one person (any case) and a category ("food" lists everything Leo ate, newest first), are summarised per person and category (Maya's 90 minutes of activities, Leo's moments on two days) and by most common item, can be searched by text ("runny" finds Leo's runny nose under health), and that asking for a person with any other fact kind is refused. <sub>`test_query_facts_family`</sub>
- Checks that highlights can be listed and searched. <sub>`test_query_facts_highlights`</sub>
- Checks that a row limit is applied and the reply says the list was cut off, while the counts still cover everything. <sub>`test_query_facts_limit_and_truncation`</sub>
- Checks that "%" and "_" are searched as plain characters (not wildcards that match everything), and that no matches gives "No matching facts found." <sub>`test_query_facts_like_wildcards_are_literal`</sub>
- Checks that an unknown fact kind ("drinks") is refused. <sub>`test_query_facts_bad_kind`</sub>
- Checks that without an index, `query_facts` returns nothing plus the missing-index note. <sub>`test_query_facts_missing_index`</sub>

### Memories from past years (`on_this_day`)

File: `tests/lens/test_tools.py`

- Checks that `on_this_day` for 2026-10-10 returns the same date in earlier years, newest first, with how many years ago, the title, people, places, highlights, each family member's facts (Leo's pumpkin pie) and the journal summary. <sub>`test_on_this_day_with_full_date`</sub>
- Checks that a month-day like "10-10" counts back from the current year. <sub>`test_on_this_day_month_day_uses_current_year`</sub>
- Checks that with no date given it uses today. <sub>`test_on_this_day_defaults_to_today`</sub>
- Checks that "years back" limits how far back it looks. <sub>`test_on_this_day_years_back`</sub>
- Checks that a date with no past entries says so ("No entries on 02-02"). <sub>`test_on_this_day_nothing`</sub>
- Checks that without an index it returns the missing-index note. <sub>`test_on_this_day_missing_index`</sub>

### Feedback on answers (`feedback`)

File: `tests/lens/test_tools.py`

- Checks that feedback is saved in the index with the question, answer, comment, rating, tool and app, that the dates mentioned in the answer are picked out, and that a copy is saved in your storage under `_system/feedback/`. <sub>`test_feedback_writes_row_and_storage_copy`</sub>
- Checks that feedback is kept when the index is wiped for a rebuild. <sub>`test_feedback_survives_index_rebuild`</sub>
- Checks that feedback can be saved before the index exists (it is created), with dates given explicitly. <sub>`test_feedback_creates_index_when_missing`</sub>
- Checks that an unknown rating, a badly written date, or an empty question, answer and comment are refused. <sub>`test_feedback_validation`</sub>
- Checks that if saving the storage copy fails, the feedback is still saved in the index. <sub>`test_feedback_still_saved_when_storage_fails`</sub>

### Login settings

File: `tests/lens/test_auth.py`

- Checks that the static-token login no longer exists: the "token" mode is refused as a setting, there is no token setting, and OAuth is the default. <sub>`test_static_token_login_is_gone`</sub>
- Checks that "oauth" mode refuses to start without an owner password, with a public address that isn't https, or with a path in the address, and that a valid address gives the expected `/mcp` address. <sub>`test_oauth_mode_validation`</sub>
- Checks that "none" mode sets up no login at all. <sub>`test_none_mode_has_no_auth`</sub>
- Checks that the local connection used by desktop apps (stdio) starts even with incomplete login settings, since it isn't reachable over the network. <sub>`test_stdio_ignores_auth_settings`</sub>

### Connecting without a login (local only)

File: `tests/lens/test_auth.py`

- Checks that in "none" mode apps connect without a token. <sub>`test_none_mode_allows_requests`</sub>

### Signing in with OAuth (Claude and ChatGPT)

File: `tests/lens/test_auth.py`

- Checks that an app that isn't signed in is pointed to where it can learn how to sign in, and that the published sign-in details (addresses, registration, the PKCE security method) are correct. <sub>`test_oauth_discovery`</sub>
- Checks the full sign-in: an app registers and is sent to a password page (showing the app's name safely and its website, and refusing to be shown inside other sites); a wrong password is refused; the right one gives a one-time code; exchanging the code with the wrong proof is refused; the right exchange gives tokens that work; the code can't be used twice; a made-up token is refused; refreshing gives new tokens and retires the old ones; and a revoked token stops working and can't be refreshed. <sub>`test_oauth_full_flow`</sub>
- Checks that pressing "deny" sends the app an "access denied" answer and uses up the request, a sign-in for another server's address is refused, and an unknown sign-in request is refused. <sub>`test_oauth_deny_and_bad_resource`</sub>
- Checks that after too many wrong passwords even the right password is refused for a while (429). <sub>`test_oauth_password_lockout`</sub>
- Checks that a leftover `LUMITRACE_MCP_AUTH_TOKEN` setting opens nothing: that token is refused (401, pointing to a bearer sign-in) and the health page reports OAuth as the login mode. <sub>`test_oauth_ignores_an_old_static_token_setting`</sub>
- Checks that sign-ins survive a restart, that only fingerprints (hashes) of tokens are saved and never the tokens themselves, and that the file can be read only by its owner. <sub>`test_oauth_state_survives_restart_and_stores_only_hashes`</sub>
- Checks that a damaged sign-in file is treated as empty instead of crashing. <sub>`test_oauth_corrupt_state_starts_empty`</sub>
- Checks that a session length under one day is refused, that the password page says how long the app stays connected, that refreshing keeps an app connected only until 7 days after the sign-in (the last token is cut short to that moment), and that after the 7 days both the access token and the refresh token are refused. <sub>`test_oauth_session_ends_after_session_days`</sub>
- Checks that tokens saved before sessions had an end are treated as signed in when the server starts: they now expire 7 days later at the latest, and the new limit is saved. <sub>`test_oauth_tokens_saved_before_session_limits_get_one`</sub>

### Managing connected apps (private admin API)

File: `tests/lens/test_admin.py`

- Checks that the Lens serves the admin API on its own port (127.0.0.1:8003 by default) next to the MCP port, and not at all when the admin port is 0 or there is no OAuth sign-in. <sub>`test_lens_serves_the_admin_api_only_with_oauth`</sub>
- Checks that the admin API refuses a missing or wrong API token (401), is turned off (503) while the API token is a placeholder, and is not reachable on the public MCP port. <sub>`test_admin_api_needs_the_api_token`</sub>
- Checks that a signed-in app is listed with its name, website, sign-in time, a session end 7 days later and when it was last used; that disconnecting it makes its current access token fail on the very next request and its refresh token fail too, removes its tokens from the saved file while keeping its registration, and shows it as signed out; that the same app can connect again with the password; and that an unknown app gives 404. <sub>`test_admin_lists_and_disconnects_an_app`</sub>
- Checks that "disconnect all" reports how many apps were signed in, ends every app's access and refresh tokens, and keeps the apps listed as signed out. <sub>`test_admin_signs_out_every_app`</sub>
- Checks that an app's first use is saved at once and later uses at most once a minute, so busy apps don't rewrite the file on every request. <sub>`test_last_used_is_saved_at_most_once_a_minute`</sub>

---

## Frames: day files

**Covered:** where files go, the 4 a.m. rule, reading and writing without losing a character,
spotting your edits, and the rules for adding entries and AI output. **Not covered:** how
Obsidian displays the files.

### Where files go

File: `tests/frames/test_dayfile.py`

- Checks the folder and file names: `2026/10/2026-10-10/2026-10-10.md`, audio named by date and time (a 1:30 a.m. recording goes in the previous day's folder), photos `photo-01.jpg` (with three digits when needed, starting at 1), and the snapshot and system paths. <sub>`test_path_conventions`</sub>
- Checks that new photos continue after the highest existing number, and that a file name already taken gets `-2`, `-3` and so on. <sub>`test_next_photo_names_and_unique_names`</sub>
- Checks that only correctly placed day files count as day files (the month folder, day folder and file name must agree, the date must exist, and the path must start at the Lumitrace folder), and that files are sorted into day files, audio, photos, system files and others. <sub>`test_parse_day_file_path_and_classify`</sub>

### Which day an entry belongs to

File: `tests/frames/test_dayfile.py`

- Checks the 4 a.m. rule (5 cases): 9:30 p.m., 4:00 a.m. and 11:59 p.m. count as that day; 3:59 a.m. and 12:40 a.m. count as the day before. <sub>`test_entry_date_rollover`</sub>
- Checks that times in UTC are converted to your timezone first, a time without a timezone is taken as local, and the switch-over hour can be set to midnight. <sub>`test_entry_date_converts_timezones_and_naive`</sub>

### A new day and its entries

File: `tests/frames/test_dayfile.py`

- Checks that a new day gets a title like "Saturday, October 10, 2026", the current format version, and isn't considered edited. <sub>`test_new_day_defaults`</sub>
- Checks that an entry time without a timezone is refused. <sub>`test_capture_requires_aware_datetime`</sub>

### Reading and writing without losing anything

File: `tests/frames/test_dayfile.py`

- Checks that the sample day file is read correctly (facts, title, journal, notes, three entries with audio and photos) and written back exactly the same, character for character. <sub>`test_sample_fixture_roundtrips`</sub>
- Checks that a day file written under an earlier project name (LifeLog's `lifelog:` markers and `lifelog_format` key, Bookshelf's `bookshelf:` markers and `bookshelf_format` key, or Lumen's `lumen:` markers and `lumen_format` key; run once for each) is read exactly like a new one, and is written back with the new Lumitrace names. <sub>`test_parses_files_written_before_the_rename`</sub>
- Checks that tricky content survives reading and writing unchanged: apostrophes and accents, values that look special ("null", "a: b"), comment arrows (`-->`), headings in notes, picture embeds, empty entries, and extra fields of your own such as tags. <sub>`test_roundtrip_model_equality_with_tricky_content`</sub>
- Checks that a recording's English translation is written below its transcript under a marker and an "English translation" heading, reads back unchanged (also for a recording with only a translation), and is still found when the heading is deleted or an older marker name is used. <sub>`test_capture_translation_roundtrip_and_hand_edits`</sub>
- Checks that the example in `docs/frames-format.md` is identical to the sample file the tests use. <sub>`test_docs_example_matches_fixture`</sub>
- Checks that a day file's parts are written in the documented order: front matter, title, "At a glance" facts (Food, Places, People, Activities, Family, Highlights), journal, My notes, Transcript. <sub>`test_render_layout_markers_in_order`</sub>
- Checks that a day file in the old layout (facts in the front matter) is read with the same facts, its old "family events" moved into highlights, still counts as unedited, and is written back in the new layout. <sub>`test_reads_format_1_files_and_writes_format_2`</sub>
- Checks that an old-layout file you had edited still counts as edited after the upgrade. <sub>`test_edited_format_1_file_stays_edited`</sub>
- Checks that a fact you type into the front matter of a new-layout file is kept there as your own field and doesn't replace the "At a glance" fact. <sub>`test_fact_keys_in_the_front_matter_of_a_format_2_file_are_kept`</sub>
- Checks that hand-typed facts are understood: labels without bold or bullets, other heading levels, "Meals" and "places visited" as section names, a food line without a meal type (counted as Snacks), minutes on an activity; lines that fit nowhere (like "Sleep: 8 hours" or an unknown "Dreams" section) move into your notes. <sub>`test_facts_section_tolerates_hand_edits`</sub>
- Checks that hand-typed family blocks are understood: any heading under Family starts a person, "Food", "Milestones" and "Work" work as labels, minutes are read from activities, a person with nothing under them is kept and written back with every line saying "none", and a line before any name or with an unknown label ("Shoe size") moves into your notes. <sub>`test_family_blocks_tolerate_hand_edits`</sub>
- Checks that a family member's items are split at their separator (commas for food, semicolons for moments), a semicolon inside an activity becomes a comma, family members without a name are dropped and those without any facts are kept, so writing and reading give the same facts. <sub>`test_family_items_never_contain_their_separator`</sub>
- Checks that fact values are tidied so writing and reading agree: whitespace and line breaks collapse to one line, empty and "none" items are dropped, items with commas are split, and meals end up as one per fixed type in the fixed order ("Breakfast:" becomes breakfast, "Supper" dinner, "drink" drinks, "dessert" snacks, two breakfasts are merged). <sub>`test_fact_values_are_normalised_so_render_and_parse_agree`</sub>
- Checks that every day file has exactly the same "At a glance" lines: Mood, City and Weather, all five meal types, every section heading and all seven lines of each family member, with "none" where there is nothing; that "none" reads back as empty; and that the index's view leaves the "none" lines out. <sub>`test_every_day_file_has_the_same_fact_lines`</sub>
- Checks that a generated journal gets the fixed headings in the fixed order (Summary, Morning, Afternoon, Evening, Thoughts): text before any heading goes to Summary, "Night" counts as Evening and "Reflections" as Thoughts, an unknown heading becomes a bold line in its section, a `#` line in a code block is left alone, doing it twice changes nothing, and a full generation applies it. <sub>`test_generated_journal_gets_the_fixed_headings`</sub>
- Checks that files without front matter, with broken front matter, without a date, or with an out-of-range mood score are reported as unreadable. <sub>`test_parse_errors`</sub>
- Checks that an almost empty file can be read using the date from its folder, with any loose text treated as your notes. <sub>`test_parse_minimal_and_fallback_date`</sub>
- Checks that Windows line endings and an invisible byte-order mark at the start don't change how a file is read. <sub>`test_parse_tolerates_windows_newlines_and_bom`</sub>
- Checks that text you typed in unexpected places (above My notes, at the very end, inside the transcript area) is moved into your notes and never lost. <sub>`test_stray_text_moves_into_notes_and_is_never_lost`</sub>
- Checks that if the journal's start and end markers are deleted, the journal text is kept as notes and the day counts as edited. <sub>`test_missing_markers_keep_content_as_notes`</sub>
- Checks that a corrected transcript is kept exactly as you wrote it, and doesn't by itself mark the day as edited. <sub>`test_user_edited_transcript_text_is_preserved`</sub>

### Spotting your edits

File: `tests/frames/test_dayfile.py`

- Checks (5 cases) that changing the mood, adding a meal item, deleting a place, changing the title, or rewording the journal marks the day as edited by you. <sub>`test_edits_to_facts_title_or_journal_are_detected`</sub>
- Checks that changing your own notes, or the record of which prompt was used, does not count as editing what Lumitrace wrote. <sub>`test_edits_to_notes_or_provenance_are_not_user_edits`</sub>

### Adding an entry to a day

File: `tests/frames/test_dayfile.py`

- Checks that the first entry of a day creates the day and lists its audio and photos. <sub>`test_merge_capture_creates_day_and_updates_front_matter`</sub>
- Checks that entries are kept in time order, adding the same entry twice changes nothing, and the earlier version of the day is left untouched. <sub>`test_merge_capture_sorts_is_idempotent_and_pure`</sub>
- Checks that adding an entry never changes the title, journal, notes or facts, and the day stays "unedited". <sub>`test_merge_capture_never_touches_generated_or_notes`</sub>
- Checks that adding an entry to the wrong day is refused. <sub>`test_merge_capture_wrong_day_raises`</sub>

### Never overwriting your edits

File: `tests/frames/test_dayfile.py`

- Checks that AI output sets the title, facts, journal and versions and stores a fingerprint so later edits can be spotted; generating again replaces the facts but keeps the title and versions when none are given. <sub>`test_apply_generation_sets_content_and_hash`</sub>
- Checks that a full rewrite is refused once you have edited the day, unless explicitly forced (which still keeps your notes). <sub>`test_apply_generation_refuses_user_edits`</sub>
- Checks that adding AI output to an edited day keeps your mood, adds new people and places without duplicates (ignoring upper/lower case), merges family blocks by name (Leo keeps his mood and gains "ice cream", Maya gains "headache"), adds new meal items (a "snack" goes to Snacks, meals stay in the fixed order) and activities without changing yours, appends the journal addition under "## Later" with its time label (a second addition joins the same Later section), keeps your notes, and leaves the day marked as edited. <sub>`test_additive_merge_on_edited_day_keeps_edits`</sub>
- Checks that adding AI output to an unedited day keeps it counted as unedited. <sub>`test_additive_merge_on_clean_day_refreshes_hash`</sub>

---

## Frames: storage

**Covered:** the local folder backend and the Google Drive backend, the latter against an
in-memory imitation of Drive. **Not covered:** the real Google Drive service and the
`lumitrace-drive-login` sign-in.

### Local folder storage

File: `tests/frames/storage/test_local.py`

- Checks that a file can be written and read back exactly, with its size and a modified time that includes the timezone. <sub>`test_write_read_roundtrip`</sub>
- Checks that text with accents and symbols comes back unchanged. <sub>`test_text_roundtrip_unicode`</sub>
- Checks that writing a file again replaces it. <sub>`test_overwrite_replaces`</sub>
- Checks that reading, inspecting, deleting or linking a missing file gives a "not found" error, unless a delete is told that missing is fine. <sub>`test_missing_file_raises`</sub>
- Checks that "exists" is true only for files (not folders) and that the size is reported. <sub>`test_exists_and_stat`</sub>
- Checks that listing includes subfolders, is sorted, and that a folder filter matches whole folder names (`2026/10` doesn't include `2026/100`). <sub>`test_list_is_recursive_sorted_and_prefix_is_a_folder`</sub>
- Checks that hidden files and folders (such as `.obsidian` and `.DS_Store`) are ignored in listings and changes. <sub>`test_hidden_files_are_ignored`</sub>
- Checks that deleting the last file in a folder removes the empty folders, but never the Lumitrace folder itself. <sub>`test_delete_removes_empty_folders`</sub>
- Checks (5 cases) that unsafe or invalid paths are refused: absolute paths, paths that climb out with `..`, empty paths and backslashes. <sub>`test_invalid_paths_rejected`</sub>
- Checks that paths are tidied (double slashes, `./`, a trailing slash). <sub>`test_normalize_path`</sub>
- Checks that writing a file leaves no temporary files behind. <sub>`test_atomic_write_leaves_no_temp_files`</sub>
- Checks the change feed: everything the first time, then nothing, then exactly the files added, changed and deleted since last time. <sub>`test_list_changes_full_then_incremental`</sub>
- Checks that a change marker from another storage type is refused. <sub>`test_list_changes_rejects_foreign_token`</sub>
- Checks that links to files are local `file://` links. <sub>`test_share_link_is_file_uri`</sub>
- Checks that the "local" setting creates local storage in the configured folder. <sub>`test_get_storage_local`</sub>

### Google Drive storage (against an imitation of Drive)

File: `tests/frames/storage/test_gdrive.py`

- Checks that the Lumitrace folder is created once in My Drive and reused afterwards. <sub>`test_root_folder_created_once_in_my_drive`</sub>
- Checks that writing a day file creates the year, month and day folders, saves it as Markdown, and reads back. <sub>`test_write_creates_folders_and_reads_back`</sub>
- Checks that writing again updates the same Drive file instead of making a copy. <sub>`test_overwrite_updates_same_file`</sub>
- Checks that "exists" is true only for files, sizes are reported, and missing files give "not found". <sub>`test_exists_stat_missing`</sub>
- Checks that names containing apostrophes and quotes work (Drive searches need them escaped). <sub>`test_names_with_quotes`</sub>
- Checks that listing includes subfolders, is sorted, and that folder filters match whole folder names. <sub>`test_list_recursive_with_prefix`</sub>
- Checks that deleting moves the file to the Drive trash (so it can be recovered) and it then counts as gone. <sub>`test_delete_trashes`</sub>
- Checks that links point to the file's Google Drive page, and that a missing file gives an error. <sub>`test_share_link`</sub>
- Checks Drive's change feed: everything the first time, then nothing, then exactly the files added, changed (once, even if changed twice) and deleted. <sub>`test_list_changes_full_then_incremental`</sub>
- Checks that after a restart, a deletion is still reported under the file's path. <sub>`test_changes_after_restart_map_deletions`</sub>
- Checks that renaming a file in Drive is reported as the old name deleted and the new name added. <sub>`test_rename_by_owner_is_delete_plus_upsert`</sub>
- Checks that renaming a folder reports every file inside it as moved. <sub>`test_folder_rename_moves_children`</sub>
- Checks that changes outside the Lumitrace folder, and hidden files, are ignored. <sub>`test_changes_outside_root_are_ignored`</sub>
- Checks that choosing Google Drive before signing in gives an error telling you to run `lumitrace-drive-login`. <sub>`test_get_storage_gdrive_without_token_errors`</sub>

---

## Index schema

**Covered:** the tables, keyword and vector search, the clean-up rules between tables, and what
survives a reset. **Not covered:** size and speed with years of entries.

### The search index's structure

File: `tests/index/test_schema.py`

- Checks that the vector-search add-on for SQLite loads on this computer. <sub>`test_sqlite_vec_loads_on_this_machine`</sub>
- Checks that a new index has all its tables, records its version, embedding size and model, and uses the settings that allow safe reading while it is being written. <sub>`test_schema_tables_exist`</sub>
- Checks that opening the index repeatedly is safe, opening it with a different embedding size is refused, and a read-only connection can't write. <sub>`test_connect_is_idempotent_and_checks_dimension`</sub>
- Checks that keyword search finds word variants ("pancake" finds "pancakes"), vector search returns the closest passage first, the keyword index follows text changes, and removing a file's record removes its passages, vectors and keyword entries. <sub>`test_fts_and_vector_search_and_cascade`</sub>
- Checks that facts can only belong to a day that exists and are removed together with it. <sub>`test_fact_tables_cascade_from_days`</sub>
- Checks that the same edit record can't be stored twice. <sub>`test_edit_signals_dedupe_by_hash`</sub>
- Checks that wiping the rebuildable parts empties files, passages, vectors, keyword entries and days, forgets the change marker and records the new embedding size and model, but keeps feedback and edit records. <sub>`test_reset_derived_keeps_signals_and_feedback`</sub>
- Checks that an embedding size of zero is refused. <sub>`test_invalid_dimension`</sub>

---

## Config and shared helpers

**Covered:** settings and their defaults, `.env.example`, the fake embeddings, nudges, the Bruno
collection, and the completeness of this catalog. **Not covered:** real embedding providers,
running the collection in the Bruno app itself.

### Settings

File: `tests/test_config.py`

- Checks the defaults with no environment variables: Chicago time, 4 a.m. switch-over, local storage, a Drive folder named "Lumitrace", and embedding size 1536. <sub>`test_defaults_without_env`</sub>
- Checks that `LUMITRACE_*` environment variables override the defaults and that the API token is hidden when settings are printed. <sub>`test_env_overrides`</sub>
- Checks that an unknown timezone, a switch-over hour of 24, or an unsupported storage type are refused. <sub>`test_validation`</sub>
- Checks that `.env.example` lists every setting, and nothing that doesn't exist. <sub>`test_env_example_documents_every_setting`</sub>
- Checks that `LUMITRACE_FAMILY` is read as a list of names: spaces trimmed, empty entries and repeats (ignoring case) dropped, and an empty setting means no family. <sub>`test_family_members_from_a_comma_separated_list`</sub>
- Checks that relations in `LUMITRACE_FAMILY` ("Sam (me), Maya (wife), Leo (son)") are read per name, that "(me)" or "(self)" marks the owner, that names without a relation still count, and that a broken entry is skipped. <sub>`test_family_relations_and_owner`</sub>
- Checks that the speech-to-text keyterms are the family names followed by `LUMITRACE_STT_KEYTERMS`, trimmed and without repeats (ignoring case). <sub>`test_stt_keyterms_start_with_the_family`</sub>

### Embeddings and nudges

File: `tests/test_shared_helpers.py`

- Checks that the offline fake embeddings are repeatable, have the configured size and length 1, differ for different texts, and handle empty input. <sub>`test_fake_embeddings_are_deterministic_unit_vectors`</sub>
- Checks that fake embeddings put texts that share words closer together, so search by meaning behaves sensibly in tests. <sub>`test_fake_embeddings_rank_shared_words_closer`</sub>
- Checks that a nudge sends the changed paths to the indexer's address. <sub>`test_nudge_posts_paths`</sub>
- Checks that a nudge reports failure instead of crashing when the indexer is down, answers with an error, or has no address configured. <sub>`test_nudge_never_raises`</sub>
- Checks that even with debug logging the HTTP client libraries only log warnings, so request URLs (Sarvam's signed storage links) never reach the logs. <sub>`test_http_client_logs_never_show_request_urls`</sub>

### Bruno collection

File: `tests/test_bruno_collection.py`

- Checks that every request in the Bruno collection (`bruno/`) calls a route that really exists in the Prism, Spectrum or Lens, with the right method (ignoring any query string). <sub>`test_every_request_matches_a_real_route`</sub>
- Checks that the collection's MCP requests, sent in order against a real Lens with an access token from an OAuth sign-in, open a session, list the tools, call all five tools without errors and close the session. <sub>`test_lens_mcp_requests_run_in_order`</sub>
- Checks that the collection contains no tokens: requests use `{{variables}}`, environments read tokens from the git-ignored `bruno/.env`, and `.env.example` leaves them blank. <sub>`test_collection_holds_no_secrets`</sub>

### Keeping this catalog complete

File: `tests/test_docs_test_cases.py`

- Checks that every test in `tests/` is described in this document under its own file's section, and that the document doesn't describe tests that no longer exist. <sub>`test_every_test_is_described_in_test_cases_doc`</sub>

---

## Entry points

**Covered:** each program starts and its commands are installed. **Not covered:** running the
programs in Docker.

### Starting the programs

File: `tests/test_entrypoints.py`

- Checks that the Prism (recording API) starts and its health page answers "ok". <sub>`test_prism_health`</sub>
- Checks that the Lens (MCP server) starts and offers exactly the five tools. <sub>`test_lens_lists_tools`</sub>
- Checks that the Spectrum (indexer) command line shows its help and exits normally. <sub>`test_spectrum_cli_help`</sub>
- Checks that the Prism command line shows its help (`lumitrace-prism --help`) and exits without starting the server. <sub>`test_prism_cli_help`</sub>
- Checks that the four installed commands (`lumitrace-prism`, `lumitrace-spectrum`, `lumitrace-lens`, `lumitrace-drive-login`) point to real functions. <sub>`test_console_scripts_resolve`</sub>
