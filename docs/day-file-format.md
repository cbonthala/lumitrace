# Day file format (format version 1)

One Markdown file per day is the source of truth. Code: `lifelog/dayfile.py`. Always use
`parse` / `render` and the merge helpers; never edit day files with string manipulation.

## Location and names

All paths are relative to the `LifeLog` root folder.

| What | Path | Helper |
|---|---|---|
| Day folder | `YYYY/MM/YYYY-MM-DD/` | `day_dir(d)` |
| Day file | `YYYY/MM/YYYY-MM-DD/YYYY-MM-DD.md` | `day_file_path(d)` |
| Audio | `YYYY-MM-DD-HHMM.m4a` in the day folder | `audio_file_name(d, local_time)` |
| Photos | `photo-NN.jpg` in the day folder (01, 02, ...) | `photo_file_name(n)`, `next_photo_names()` |
| System snapshot | `_system/generated/YYYY/MM/YYYY-MM-DD.md` | `generated_snapshot_path(d)` |

* **Entry date:** `entry_date(captured_at, tz, rollover_hour)`. Captures before 4 a.m. local time
  belong to the previous day. The audio file name uses the *entry date* plus the *local capture
  time*, so a 01:30 recording on Oct 11 that belongs to Oct 10 is `2026-10-10-0130.m4a`.
* Name collisions within a folder: `unique_file_name(name, existing)` → `...-2.m4a`.

## Structure

```
---                          YAML front matter (FrontMatter)
...
---

# Title                      DayFile.title (default: "Saturday, October 10, 2026")

<!-- lifelog:journal:start (...) -->      DayFile.journal: generated Markdown, "##" sections
...
<!-- lifelog:journal:end -->

## My notes

<!-- lifelog:notes:start (...) -->        DayFile.notes: the owner's own text
...
<!-- lifelog:notes:end -->

## Transcript

<!-- lifelog:transcript:start (...) -->   DayFile.captures, oldest first
<!-- lifelog:capture {json} -->           one block per Capture
### HH:MM · Log My Day | Quick Note
![[audio.m4a]]                            embeds derived from the capture metadata
![[photo-01.jpg]]

raw transcript or note text
<!-- lifelog:transcript:end -->
```

Markers are HTML comments, invisible in Obsidian's reading view. Parsing matches the marker name
(`lifelog:journal:start`, etc.), so the explanatory text inside the comment can change.

### Front matter fields

| Field | Type | Notes |
|---|---|---|
| `date` | date | the entry date |
| `mood` | string or null | free text, e.g. "happy" |
| `mood_score` | 1–5 or null | for mood colours later |
| `city`, `weather` | string or null | |
| `people` | list of strings | |
| `meals` | list of `{type, items}` | type: breakfast, lunch, dinner, snack, drink (free text accepted) |
| `activities` | list of `{kind, minutes}` | minutes may be null |
| `family_events`, `highlights` | list of strings | |
| `audio`, `photos` | list of file names | in the day folder, in capture order |
| `prompt_version` | string or null | prompts used for the last generation |
| `models_used` | map task → model | e.g. `stt`, `extract_facts`, `write_journal` |
| `generated_at` | ISO-8601 datetime or null | last generation |
| `generated_hash` | string or null | edit detection, see below |
| `lifelog_format` | int | `1` |
| *anything else* | | preserved as is (e.g. Obsidian `tags`) |

### Capture metadata

The `<!-- lifelog:capture {...} -->` comment holds JSON: `id` (unique within the day; merging an
existing id is a no-op, so retries from the offline inbox are safe), `kind` (`recording` or
`note`), `captured_at` (ISO-8601 with offset), `audio`, `photos`, `location`. The heading and
embed lines are regenerated from it; the text below them is the transcript and may be edited.

## Never overwrite the owner's edits

* **Notes** (`My notes`) are never modified by the system.
* **Transcript** blocks are append-only; edits to their text are kept.
* **Generated content** (facts, title, journal) carries `generated_hash`, a hash of exactly what
  the system wrote. `DayFile.is_user_edited()` compares it with the current content.
  * `apply_generation(...)` replaces facts/title/journal, and raises `UserEditsDetected` if the
    owner edited them (unless `force=True`, reserved for an explicit owner request).
  * `merge_generation_additive(...)` only adds: fills empty facts, adds new list items, appends a
    journal addendum. On an edited day it keeps the old hash, so the day stays marked as edited.
* **Stray text** typed outside the regions (or a region whose markers were deleted) is moved into
  `My notes` on the next system write, so nothing is lost.
* Provenance fields (`prompt_version`, `models_used`, `generated_at`) and transcript text are not
  part of the hash.

The recording API also writes the exact rendered file to `generated_snapshot_path(d)` every time
it writes a day file; the indexer diffs the live file against that snapshot to record
`edit_signals`.

## Example

Fictional data (also `tests/fixtures/sample-day.md`, which is the canonical rendering):

```markdown
---
date: 2026-10-10
mood: happy
mood_score: 4
city: Austin
weather: sunny, 24°C
people:
- Maya
- Leo
meals:
- type: breakfast
  items:
  - oatmeal
  - blueberries
- type: lunch
  items:
  - fish tacos
- type: drink
  items:
  - horchata
- type: dinner
  items:
  - pasta
activities:
- kind: run
  minutes: 40
- kind: reading
  minutes: null
family_events:
- Leo lost his first tooth
highlights:
- Leo lost his first tooth
- Finished a book
audio:
- 2026-10-10-2130.m4a
photos:
- photo-01.jpg
- photo-02.jpg
prompt_version: journal-v1
models_used:
  stt: openai/gpt-4o-transcribe
  extract_facts: openai/gpt-4o-mini
  write_journal: openai/gpt-4o
generated_at: '2026-10-11T00:41:00-05:00'
generated_hash: f95b9b427b956b91
lifelog_format: 1
---

# Saturday, October 10, 2026 · First tooth

<!-- lifelog:journal:start (written by LifeLog; if you edit it, your edits are kept) -->
## Summary

A full, happy Saturday that started with a run by the river and ended with a family milestone.

## Morning

A forty-minute run along the river, then oatmeal with blueberries.

## Afternoon

Fish tacos and a horchata from the taco truck with Maya.

## Evening

Pasta at home. Leo lost his first tooth and was very proud. Late at night you finished the book you had been reading.
<!-- lifelog:journal:end -->

## My notes

<!-- lifelog:notes:start (your own notes; LifeLog never changes this section) -->
Remember to put the tooth under the pillow tomorrow too.
<!-- lifelog:notes:end -->

## Transcript

<!-- lifelog:transcript:start (raw transcripts, added by LifeLog) -->
<!-- lifelog:capture {"id": "20261010T130500-note", "kind": "note", "captured_at": "2026-10-10T13:05:00-05:00", "audio": null, "photos": [], "location": "Austin, TX"} -->
### 13:05 · Quick Note

Lunch at the taco truck with Maya. Fish tacos and a horchata.

<!-- lifelog:capture {"id": "20261010T213000-recording", "kind": "recording", "captured_at": "2026-10-10T21:30:00-05:00", "audio": "2026-10-10-2130.m4a", "photos": ["photo-01.jpg", "photo-02.jpg"], "location": "Austin, TX"} -->
### 21:30 · Log My Day
![[2026-10-10-2130.m4a]]
![[photo-01.jpg]]
![[photo-02.jpg]]

Long day. Morning run, about forty minutes along the river. Oatmeal with blueberries for breakfast. Leo lost his first tooth tonight, he was so proud. Dinner was pasta at home.

<!-- lifelog:capture {"id": "20261011T004000-note", "kind": "note", "captured_at": "2026-10-11T00:40:00-05:00", "audio": null, "photos": [], "location": null} -->
### 00:40 · Quick Note

Forgot to say: finished the book I was reading.
<!-- lifelog:transcript:end -->
```

## Typical write sequence (recording API)

```python
day_date = entry_date(captured_at, settings.tz, settings.day_rollover_hour)
path = day_file_path(day_date)
day = parse(storage.read_text(path), fallback_date=day_date) if storage.exists(path) else None
day = merge_capture(day, capture, day_date)
if day.is_user_edited():
    day = merge_generation_additive(day, facts=new_facts, journal_addendum=..., ...)
else:
    day = apply_generation(day, facts=facts_for_whole_day, journal=journal, title=title, ...)
text = render(day)
storage.write_text(path, text)
storage.write_text(generated_snapshot_path(day_date), text)
```

## Changing the format

Bump `FORMAT_VERSION`, keep `parse` able to read older versions, add tests with an old-format
fixture, and update this page, `docs/contracts.md` and `CHANGELOG.md` in the same commit.
