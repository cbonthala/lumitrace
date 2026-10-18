# Frames: day file format (format version 3)

The Frames are the day files: one Markdown file per day, the source of truth. Code:
`lumitrace/frames/dayfile.py` (format) and `lumitrace/frames/storage/` (where they live). Always use
`parse` / `render` and the merge helpers; never edit day files with string manipulation.

## Location and names

All paths are relative to the `Lumitrace` root folder.

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

<!-- lumitrace:facts:start (...) -->      DayFile.facts: Mood and City lines, then "###"
- **Mood:** happy (4/5)                   topic sections; Food, Health and fitness,
### Highlight                             Feelings and Memories hold one "####" block
### Food                                  per family member
#### Leo
- **Morning:** oatmeal
<!-- lumitrace:facts:end -->

<!-- lumitrace:journal:start (...) -->    DayFile.journal: generated Markdown, "##" sections
## Summary                                Summary, Morning, Afternoon, Evening, Thoughts,
...                                       Later (fixed names and order)
<!-- lumitrace:journal:end -->

## My notes

<!-- lumitrace:notes:start (...) -->      DayFile.notes: the owner's own text
...
<!-- lumitrace:notes:end -->

## Transcript

<!-- lumitrace:transcript:start (...) --> DayFile.captures, oldest first
<!-- lumitrace:capture {json} -->         one block per Capture
### HH:MM · Log My Day | Quick Note
![[audio.m4a]]                            embeds derived from the capture metadata
![[photo-01.jpg]]

raw transcript or note text
<!-- lumitrace:translation (...) -->      optional: Capture.translation
#### English translation

English translation of the recording
<!-- lumitrace:transcript:end -->
```

Markers are HTML comments, invisible in Obsidian's reading view. Parsing matches the marker name
(`lumitrace:journal:start`, etc.), so the explanatory text inside the comment can change. Files
written under the project's earlier names use `lifelog:` (LifeLog, 0.1.0), `bookshelf:`
(Bookshelf) or `lumen:` (Lumen) markers and a `lifelog_format`, `bookshelf_format` or
`lumen_format` key; `parse` still reads them and the next `render` writes the `lumitrace:` names
(decisions 0008, 0009 and 0042).

### Front matter fields

The front matter holds only the date, the media and provenance. The facts are in "At a glance".

| Field | Type | Notes |
|---|---|---|
| `date` | date | the entry date |
| `audio`, `photos` | list of file names | in the day folder, in capture order |
| `prompt_version` | string or null | prompt task for the last generation (`fill_day` or `update_day`). Older files may still say `fill_day-v1` or `journal-v1` |
| `models_used` | map task → model | e.g. `stt`, `fill_day`, `update_day` |
| `generated_at` | ISO-8601 datetime or null | last generation |
| `generated_hash` | string or null | edit detection, see below |
| `lumitrace_format` | int | `3` (read from `lumen_format`, `bookshelf_format` or `lifelog_format` in files written under the earlier names) |
| *anything else* | | preserved as is (e.g. Obsidian `tags`) |

### "At a glance": the facts (`DayFacts`)

The Prism extracts these from the recordings; Spectrum indexes them exactly as they are written
here (one row per item in the fact tables, see `docs/index-schema.md`). The layout is
**topic first** (decision 0045): each topic is a `###` section and, where it differs per person,
holds one `#### name` block per family member. A family member named in `secrets/family.md` gets
a block in every such section on every generated day, in the configured order and spelling, so a
new member appears everywhere without any change.

**The same lines every day.** Anything empty is written `not mentioned` (never left blank, so
"nothing was said" is visible) and read back as empty; Weather says `not looked up` until a
weather lookup fills it. Search and the index never see those lines
(`render_facts_section(facts, include_empty=False)`).

| Section | Field | Rendered as |
|---|---|---|
| `- **Mood:**`, `- **City:**` | `mood`, `mood_score` (1-5), `city` | `happy (4/5)`, the city or `not mentioned` |
| `### Highlight` | `highlights`, `remember` | one short bullet per highlight, then `- **Remember:** ...`, the one moment worth keeping |
| `### Food` | `FamilyMember.meals`, `meals` | per person: `- **Morning:**`, `**Lunch:**`, `**Dinner:**`, `**Snacks / drinks / other:**` (`MEAL_TYPES` breakfast, lunch, dinner, snacks); `#### Everyone` for meals nobody is named for |
| `### Places visited` | `places` | one bullet per place; add `(Name)` when only some went |
| `### People we met or visited` | `people` | one bullet: `Rachel, friend - at the park (Maya)` |
| `### Health and fitness` | `FamilyMember.health` | per person, one bullet per item (exercise, symptoms, sleep) |
| `### Feelings` | `FamilyMember.feelings` | per person, one bullet per feeling |
| `### Memories` | `FamilyMember.moments`, `memories` | per person; `#### Together` for memories the whole family shares |
| `### Weather` | `weather` | the weather for the places visited, or `not looked up` |
| `### Things we did` | `activities` | one bullet per thing (`grocery shopping`, `play area (Maya, Leo)`) |

A fact the AI was not sure about ends with `[uncertain: why]` (no commas or semicolons inside
the brackets). It stays ordinary text: it is indexed and searched like the rest, so the owner can
see and fix it.

Values are normalised so that rendering and parsing give back the same facts: each value is one
line (whitespace collapsed); empty and `not mentioned` items are dropped; meals of the same type
are merged and kept in `MEAL_TYPES` order (`snack`, `drink`, `other` become snacks, `supper`
dinner, `brunch` lunch); members without a name are dropped (members without facts are kept).

Hand edits are tolerated: bullets and bold are optional, headings may use any level, and
common alternative names (`Meals`, `Places`, `People`, `Activities`) are accepted for the
sections. A food line without a known label counts as snacks. Lines that fit nowhere are moved
into `My notes` on the next system write, so nothing is lost. Hand edits are rewritten to the
standard names and lines on the next system write.

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

### Older formats

* **Format 2** (decision 0042 era) had `###` sections Food (five meal lines), Places, People,
  Activities, Family and Highlights, with a seven-line `####` block per member. `parse` reads
  it (`parse_facts_section(..., source_format=2)`) and converts it: a member's food becomes
  that member's meals (snacks when no meal is known), their places and activities become day
  places and things we did marked `(Name)`, school/work becomes things we did, moments become
  memories, and the rest keep their names. The next `render` writes format 3.
* **Format 1** (0.1.0) kept the facts in the front matter and had no facts region; `parse` reads
  those keys as the facts and the next `render` writes format 3.

**Edit detection across formats.** `generated_hash` covers the rendered facts, so a day written
in format 1 or 2 cannot reproduce its old hash and looks edited after migration. To redo old
days safely, compare the live file with its `_system/generated` snapshot: identical means the
owner never edited it (`lumitrace-prism regenerate` does exactly this, `docs/prism.md`).

### Capture metadata

The `<!-- lumitrace:capture {...} -->` comment holds JSON: `id` (unique within the day; merging an
existing id is a no-op, so retries from the offline inbox are safe), `kind` (`recording` or
`note`), `captured_at` (ISO-8601 with offset), `audio`, `photos`, `location`. The heading and
embed lines are regenerated from it; the text below them is the transcript and may be edited.

**English translation** (`Capture.translation`, ADR 0043). Older recordings that were translated
keep the block after the transcript: the `<!-- lumitrace:translation (...) -->` marker, a
`#### English translation` heading and the translated text. New recordings do not get one
(ADR 0048). The raw transcript above it is kept as spoken. On parsing,
everything after the marker is the translation (the heading is dropped if present, so deleting
it by hand is harmless); a block without the marker has no translation. The translation may be
edited like the transcript. Spectrum indexes it as extra transcript passages headed
`HH:MM · Log My Day · English`, so English searches find days spoken in another language.

```markdown
<!-- lumitrace:capture {"id": "...", "kind": "recording", ...} -->
### 21:30 · Log My Day
![[2026-10-10-2130.m4a]]

mana park ki vellam, Leo slide meeda chala sepu aadadu

<!-- lumitrace:translation (English translation of the recording) -->
#### English translation

We went to the park, and Leo played on the slide for a long time.
```

## Never overwrite the owner's edits

* **Notes** (`My notes`) are never modified by the system.
* **Transcript** blocks are append-only; edits to their text are kept.
* **Generated content** (facts in "At a glance", title, journal) carries `generated_hash`, a
  hash of exactly what
  the system wrote. `DayFile.is_user_edited()` compares it with the current content.
  * `apply_generation(...)` replaces facts/title/journal, and raises `UserEditsDetected` if the
    owner edited them (unless `force=True`). The 4:05 a.m. fill uses `force=True` (ADR 0050).
  * `merge_generation_additive(...)` only adds: fills empty facts, adds new list items, appends
    journal lines under `## Later`. A recording that arrives after the journal exists uses this,
    whether or not the owner edited the file. On an edited day it keeps the old hash.
* **Stray text** typed outside the regions (or a region whose markers were deleted) is moved into
  `My notes` on the next system write, so nothing is lost.
* Provenance fields (`prompt_version`, `models_used`, `generated_at`) and transcript text are not
  part of the hash.

The Prism also writes the exact rendered file to `generated_snapshot_path(d)` every time
it writes a day file; Spectrum diffs the live file against that snapshot to record
`edit_signals`.

## Example

Fictional data (also `tests/fixtures/sample-day.md`, which is the canonical rendering; the same
day in format 2 is `tests/fixtures/sample-day-v2.md` and in format 1 `tests/fixtures/sample-day-v1.md`):

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
generated_hash: 66bd9471a8c0b8c9
lumitrace_format: 3
---

# Saturday, October 10, 2026 · First tooth

## At a glance

<!-- lumitrace:facts:start (found by Lumitrace; if you edit them, your edits are kept) -->
- **Mood:** happy (4/5)
- **City:** Austin

### Highlight

- Morning run by the river
- Fish tacos from the taco truck
- Leo lost his first tooth
- Finished a book late at night
- **Remember:** Leo lost his first tooth and was very proud

### Food

#### Sam

- **Morning:** oatmeal, blueberries
- **Lunch:** fish tacos
- **Dinner:** pasta
- **Snacks / drinks / other:** horchata

#### Maya

- **Morning:** not mentioned
- **Lunch:** fish tacos
- **Dinner:** not mentioned
- **Snacks / drinks / other:** not mentioned

#### Leo

- **Morning:** not mentioned
- **Lunch:** not mentioned
- **Dinner:** pasta
- **Snacks / drinks / other:** not mentioned

### Places visited

- the river trail (Sam)
- the taco truck (Sam, Maya)
- home (Sam, Maya, Leo)

### People we met or visited

- Ravi, neighbour - at the river trail (Sam)

### Health and fitness

#### Sam

- not mentioned

#### Maya

- not mentioned

#### Leo

- not mentioned

### Feelings

#### Sam

- happy

#### Maya

- not mentioned

#### Leo

- proud

### Memories

#### Together

- Leo's first tooth came out at bedtime

#### Sam

- not mentioned

#### Maya

- not mentioned

#### Leo

- lost his first tooth

### Weather

- sunny, 24°C

### Things we did

- run (Sam) (40 min)
- reading (Sam)
<!-- lumitrace:facts:end -->

<!-- lumitrace:journal:start (written by Lumitrace; if you edit it, your edits are kept) -->
## Summary

A full, happy Saturday that started with a run by the river and ended with a family milestone.

## Morning

A forty-minute run along the river, then oatmeal with blueberries.

## Afternoon

Fish tacos and a horchata from the taco truck with Maya.

## Evening

Pasta at home. Leo lost his first tooth and was very proud. Late at night you finished the book you had been reading.
<!-- lumitrace:journal:end -->

## My notes

<!-- lumitrace:notes:start (your own notes; Lumitrace never changes this section) -->
Remember to put the tooth under the pillow tomorrow too.
<!-- lumitrace:notes:end -->

## Transcript

<!-- lumitrace:transcript:start (raw transcripts, added by Lumitrace) -->
<!-- lumitrace:capture {"id": "20261010T130500-note", "kind": "note", "captured_at": "2026-10-10T13:05:00-05:00", "audio": null, "photos": [], "location": "Austin, TX"} -->
### 13:05 · Quick Note

Lunch at the taco truck with Maya. Fish tacos and a horchata.

<!-- lumitrace:capture {"id": "20261010T213000-recording", "kind": "recording", "captured_at": "2026-10-10T21:30:00-05:00", "audio": "2026-10-10-2130.m4a", "photos": ["photo-01.jpg", "photo-02.jpg"], "location": "Austin, TX"} -->
### 21:30 · Log My Day
![[2026-10-10-2130.m4a]]
![[photo-01.jpg]]
![[photo-02.jpg]]

Long day. Morning run, about forty minutes along the river. Oatmeal with blueberries for breakfast. Leo lost his first tooth tonight, he was so proud. Dinner was pasta at home.

<!-- lumitrace:capture {"id": "20261011T004000-note", "kind": "note", "captured_at": "2026-10-11T00:40:00-05:00", "audio": null, "photos": [], "location": null} -->
### 00:40 · Quick Note

Forgot to say: finished the book I was reading.
<!-- lumitrace:transcript:end -->
```

## Typical write sequence (Prism)

```python
day_date = entry_date(captured_at, settings.tz, settings.day_rollover_hour)
path = day_file_path(day_date)
day = parse(storage.read_text(path), fallback_date=day_date) if storage.exists(path) else None
day = merge_capture(day, capture, day_date)
if day.meta.generated_at is None:
    day = apply_generation(
        day, facts=facts_for_whole_day, journal=journal, title=title, force=True, ...
    )
else:
    day = merge_generation_additive(day, facts=new_facts, journal_addendum=..., ...)
text = render(day)
storage.write_text(path, text)
storage.write_text(generated_snapshot_path(day_date), text)
```

## Changing the format

Bump `FORMAT_VERSION`, keep `parse` able to read older versions, add tests with an old-format
fixture, and update this page, `docs/contracts.md` and `CHANGELOG.md` in the same commit.
