# Frames: day file format (format version 2)

The Frames are the day files: one Markdown file per day, the source of truth. Code:
`lumen/frames/dayfile.py` (format) and `lumen/frames/storage/` (where they live). Always use
`parse` / `render` and the merge helpers; never edit day files with string manipulation.

## Location and names

All paths are relative to the `Lumen` root folder.

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

## At a glance

<!-- lumen:facts:start (...) -->      DayFile.facts: always the same lines: mood, city,
- **Mood:** happy (4/5)                   weather, then "###" sections Food (five meal
### Food                                  lines), Places, People, Activities, Family
- **Breakfast:** oatmeal, blueberries     (a "####" block of seven lines per family
- **Snacks:** none                        member), Highlights; "none" when empty
### Family
#### Leo
- **Ate:** pasta
<!-- lumen:facts:end -->

<!-- lumen:journal:start (...) -->    DayFile.journal: generated Markdown, "##" sections
## Summary                                Summary, Morning, Afternoon, Evening, Thoughts,
...                                       Later (fixed names and order)
<!-- lumen:journal:end -->

## My notes

<!-- lumen:notes:start (...) -->      DayFile.notes: the owner's own text
...
<!-- lumen:notes:end -->

## Transcript

<!-- lumen:transcript:start (...) --> DayFile.captures, oldest first
<!-- lumen:capture {json} -->         one block per Capture
### HH:MM · Log My Day | Quick Note
![[audio.m4a]]                            embeds derived from the capture metadata
![[photo-01.jpg]]

raw transcript or note text
<!-- lumen:transcript:end -->
```

Markers are HTML comments, invisible in Obsidian's reading view. Parsing matches the marker name
(`lumen:journal:start`, etc.), so the explanatory text inside the comment can change. Files
written under the project's earlier names use `lifelog:` (LifeLog, 0.1.0) or `bookshelf:`
(Bookshelf) markers and a `lifelog_format` or `bookshelf_format` key; `parse` still reads them
and the next `render` writes the `lumen:` names (decisions 0008 and 0009).

### Front matter fields

The front matter holds only the date, the media and provenance. The facts are in "At a glance".

| Field | Type | Notes |
|---|---|---|
| `date` | date | the entry date |
| `audio`, `photos` | list of file names | in the day folder, in capture order |
| `prompt_version` | string or null | prompts used for the last generation |
| `models_used` | map task → model | e.g. `stt`, `extract_facts`, `write_journal` |
| `generated_at` | ISO-8601 datetime or null | last generation |
| `generated_hash` | string or null | edit detection, see below |
| `lumen_format` | int | `2` (read from `bookshelf_format` or `lifelog_format` in files written under the earlier names) |
| *anything else* | | preserved as is (e.g. Obsidian `tags`) |

### "At a glance": the facts (`DayFacts`)

The Prism extracts these from the recordings; Spectrum indexes them exactly as they are written
here (one row per item in the fact tables, see `docs/index-schema.md`).

**Every day file has exactly the same lines, in the same order**, whatever the day held: the
Mood, City and Weather lines, all six `###` sections, all five Food lines and, for each family
member, all seven labelled lines. Anything empty is written as `none` (`- **Snacks:** none`,
`- none` under an empty section) and read back as empty. Search and the index never see the
`none` lines (`render_facts_section(facts, include_empty=False)`).

| Line or section | Field | Rendered as |
|---|---|---|
| `- **Mood:** ...` | `mood` (string), `mood_score` (1–5) | `happy (4/5)`, `happy`, `4/5` or `none` |
| `- **City:** ...`, `- **Weather:** ...` | `city`, `weather` | the text or `none` |
| `### Food` | `meals`: list of `{type, items}` | always five lines in this order: `- **Breakfast:**`, `**Lunch:**`, `**Dinner:**`, `**Snacks:**`, `**Drinks:**`, each with comma-separated items or `none`. `MEAL_TYPES` are the only types: `snack`→snacks, `drink`/`beverage`→drinks, `supper`→dinner, `brunch`→lunch, anything else → snacks |
| `### Places` | `places`: list of strings | one bullet per place visited |
| `### People` | `people`: list of strings | one bullet per person |
| `### Activities` | `activities`: list of `{kind, minutes}` | `- run (40 min)` or `- reading` |
| `### Family` | `family`: list of `FamilyMember`, see below | one `#### name` block per member |
| `### Highlights` | `highlights`: list of strings | one bullet each |

**Family.** Every family member named in `LUMEN_FAMILY` gets a `#### name` block under
`### Family` on every generated day, in the configured order and spelling, even if the day says
nothing about them (the Prism drops anyone else; the owner may add other names by hand). With
no family configured, Family holds `- none`. A block always has these seven lines:

| Line | `FamilyMember` field | Items separated by |
|---|---|---|
| `- **Mood:** proud` | `mood` (string) | |
| `- **Ate:** pasta, apple juice` | `food` | `, ` |
| `- **Went to:** school, the dentist` | `places` | `, ` |
| `- **Did:** soccer (60 min); drawing` | `activities` (`{kind, minutes}`) | `; ` |
| `- **Moments:** lost his first tooth` | `moments` | `; ` |
| `- **Health:** a cold; saw the dentist` | `health` | `; ` |
| `- **School/work:** spelling test` | `school` | `; ` |

Values are normalised so that rendering and parsing give back the same facts: each value is one
line (whitespace collapsed); empty and `none` items and meals without items are dropped; meals
of the same type are merged and kept in `MEAL_TYPES` order; family members without a name are
dropped (members without facts are kept); items never contain their separator (`"eggs, toast"`
becomes two items, and a `;` inside an activity becomes `,`).

Hand edits are tolerated: bullets (`-`, `*`, `+`) are optional, labels may be bold or not
(`Mood: great`), headings may use any level, and `Meals`, `Places visited` and `Family events`
are accepted as section names. Under Family, any heading that is not a section name starts a
member's block, and `Food`/`Meals`, `Places`, `Activities`, `Moment`/`Milestones` and
`School`/`Work` are accepted as labels. A food line without a label counts as Snacks; an
activity ending in `(N min)` or `(N minutes)` gets its minutes. Lines that fit nowhere (an
unknown label such as `- Sleep: 8 hours`, a line under Family before any name, an unknown
heading outside Family and everything under it) are moved into `My notes` on the next system
write, so nothing is lost. Hand edits are rewritten to the standard names and lines on the
next system write.

### The journal

A journal written by the Prism only uses these `##` headings, in this order, each only when it
has text: `Summary`, `Morning`, `Afternoon`, `Evening`, `Thoughts`, `Later` (`JOURNAL_SECTIONS`).
`apply_generation` enforces it with `normalize_journal`: text before the first heading goes to
Summary, repeated sections are merged, `Night`/`Tonight` count as Evening and
`Reflections`/`Plans` as Thoughts, and any other heading becomes a bold line in the section it
appears in. `Later` holds what is added after the owner edited the day
(`merge_generation_additive`): each addition starts with a bold label such as
`**22:15 · Quick Note**`, and a `## Later` heading is only opened when the journal does not
already end with one. A journal the owner edited is never re-normalised.

### Format 1 files

Format 1 (0.1.0) kept the facts in the front matter (`mood`, `mood_score`, `city`, `weather`,
`people`, `meals`, `activities`, `family_events`, `highlights`) and had no facts region. `parse`
reads those keys as the facts when the facts region is missing (`family_events`, which had no
person, are added to `highlights`), and the next `render` writes format 2. If the file's
`generated_hash` matches its format 1 content, `parse` re-stamps it with the format 2 hash, so an
unedited day stays unedited; an edited day keeps its old hash and stays marked as edited. In a
format 2 file, fact-named keys the owner adds to the front matter are ordinary extra keys: kept,
but not read as facts.

### Capture metadata

The `<!-- lumen:capture {...} -->` comment holds JSON: `id` (unique within the day; merging an
existing id is a no-op, so retries from the offline inbox are safe), `kind` (`recording` or
`note`), `captured_at` (ISO-8601 with offset), `audio`, `photos`, `location`. The heading and
embed lines are regenerated from it; the text below them is the transcript and may be edited.

## Never overwrite the owner's edits

* **Notes** (`My notes`) are never modified by the system.
* **Transcript** blocks are append-only; edits to their text are kept.
* **Generated content** (facts in "At a glance", title, journal) carries `generated_hash`, a
  hash of exactly what
  the system wrote. `DayFile.is_user_edited()` compares it with the current content.
  * `apply_generation(...)` replaces facts/title/journal, and raises `UserEditsDetected` if the
    owner edited them (unless `force=True`, reserved for an explicit owner request).
  * `merge_generation_additive(...)` only adds: fills empty facts, adds new list items, appends a
    journal addendum. On an edited day it keeps the old hash, so the day stays marked as edited.
* **Stray text** typed outside the regions (or a region whose markers were deleted) is moved into
  `My notes` on the next system write, so nothing is lost.
* Provenance fields (`prompt_version`, `models_used`, `generated_at`) and transcript text are not
  part of the hash.

The Prism also writes the exact rendered file to `generated_snapshot_path(d)` every time
it writes a day file; Spectrum diffs the live file against that snapshot to record
`edit_signals`.

## Example

Fictional data (also `tests/fixtures/sample-day.md`, which is the canonical rendering; the same
day in format 1 is `tests/fixtures/sample-day-v1.md`):

```markdown
---
date: 2026-10-10
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
generated_hash: 2c4980bf67ca8a30
lumen_format: 2
---

# Saturday, October 10, 2026 · First tooth

## At a glance

<!-- lumen:facts:start (found by Lumen; if you edit them, your edits are kept) -->
- **Mood:** happy (4/5)
- **City:** Austin
- **Weather:** sunny, 24°C

### Food

- **Breakfast:** oatmeal, blueberries
- **Lunch:** fish tacos
- **Dinner:** pasta
- **Snacks:** none
- **Drinks:** horchata

### Places

- the river trail
- the taco truck
- home

### People

- Maya
- Leo

### Activities

- run (40 min)
- reading

### Family

#### Leo

- **Mood:** proud
- **Ate:** pasta
- **Went to:** none
- **Did:** none
- **Moments:** lost his first tooth
- **Health:** none
- **School/work:** none

#### Maya

- **Mood:** none
- **Ate:** fish tacos
- **Went to:** the taco truck
- **Did:** none
- **Moments:** none
- **Health:** none
- **School/work:** none

### Highlights

- Leo lost his first tooth
- Finished a book
<!-- lumen:facts:end -->

<!-- lumen:journal:start (written by Lumen; if you edit it, your edits are kept) -->
## Summary

A full, happy Saturday that started with a run by the river and ended with a family milestone.

## Morning

A forty-minute run along the river, then oatmeal with blueberries.

## Afternoon

Fish tacos and a horchata from the taco truck with Maya.

## Evening

Pasta at home. Leo lost his first tooth and was very proud. Late at night you finished the book you had been reading.
<!-- lumen:journal:end -->

## My notes

<!-- lumen:notes:start (your own notes; Lumen never changes this section) -->
Remember to put the tooth under the pillow tomorrow too.
<!-- lumen:notes:end -->

## Transcript

<!-- lumen:transcript:start (raw transcripts, added by Lumen) -->
<!-- lumen:capture {"id": "20261010T130500-note", "kind": "note", "captured_at": "2026-10-10T13:05:00-05:00", "audio": null, "photos": [], "location": "Austin, TX"} -->
### 13:05 · Quick Note

Lunch at the taco truck with Maya. Fish tacos and a horchata.

<!-- lumen:capture {"id": "20261010T213000-recording", "kind": "recording", "captured_at": "2026-10-10T21:30:00-05:00", "audio": "2026-10-10-2130.m4a", "photos": ["photo-01.jpg", "photo-02.jpg"], "location": "Austin, TX"} -->
### 21:30 · Log My Day
![[2026-10-10-2130.m4a]]
![[photo-01.jpg]]
![[photo-02.jpg]]

Long day. Morning run, about forty minutes along the river. Oatmeal with blueberries for breakfast. Leo lost his first tooth tonight, he was so proud. Dinner was pasta at home.

<!-- lumen:capture {"id": "20261011T004000-note", "kind": "note", "captured_at": "2026-10-11T00:40:00-05:00", "audio": null, "photos": [], "location": null} -->
### 00:40 · Quick Note

Forgot to say: finished the book I was reading.
<!-- lumen:transcript:end -->
```

## Typical write sequence (Prism)

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
