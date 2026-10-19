# Frames: day file format (format version 6)

The Frames are the day files: one Markdown file per day, the source of truth. Code:
`lumitrace/frames/dayfile.py` (file envelope and compatibility) and
`lumitrace/frames/daycontent.py` (Format 6 content), plus `lumitrace/frames/storage/` (where they
live). Always use `parse` / `render` and the merge helpers; never edit day files with string
manipulation. Decision: ADR 0061.

## Location and names

All paths are relative to the `Lumitrace` root folder.

| What | Path | Helper |
|---|---|---|
| Day folder | `YYYY/MM/YYYY-MM-DD/` | `day_dir(d)` |
| Day file | `YYYY/MM/YYYY-MM-DD/YYYY-MM-DD.md` | `day_file_path(d)` |
| Audio | `YYYY-MM-DD-HHMM.m4a` in the day folder | `audio_file_name(d, local_time)` |
| Photos | `photo-NN.jpg` in the day folder (01, 02, ...) | `photo_file_name(n)`, `next_photo_names()` |
| System snapshot | `_system/generated/YYYY/MM/YYYY-MM-DD.md` | `generated_snapshot_path(d)` |
| Generated facts base | `_system/generated-facts/YYYY/MM/YYYY-MM-DD.json` | `generated_facts_path(d)` |

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

<!-- lumitrace:content:start (...) -->    DayFile.content: structured, owner-editable content
## Day timeline
### Highlight / Day context
### Morning / Afternoon / Evening / Night
### Time not stated                       only when it has entries
- **Remember:** ...
## Family trackers
### Food / Health and fitness / Pregnancy and baby
### Daily routine / Interests and preferences / Growth and learning
## Tags
<!-- lumitrace:content:end -->

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

raw transcript or note text               Telugu, as spoken. No translation block.
<!-- lumitrace:transcript:end -->
```

Markers are HTML comments, invisible in Obsidian's reading view. Parsing matches the marker name
(`lumitrace:content:start`, etc.), so the explanatory text inside the comment can change. Files
written under the project's earlier names use `lifelog:` (LifeLog, 0.1.0), `bookshelf:`
(Bookshelf) or `lumen:` (Lumen) markers and a `lifelog_format`, `bookshelf_format` or
`lumen_format` key; `parse` still reads them and the next `render` writes the `lumitrace:` names
(decisions 0008, 0009 and 0042).

### Front matter fields

The front matter holds only the date, the media and provenance.

| Field | Type | Notes |
|---|---|---|
| `date` | date | the entry date |
| `audio`, `photos` | list of file names | in the day folder, in capture order |
| `prompt_version` | string or null | prompt task for the last generation (`fill_day` or `update_day`). Older files may still say `fill_day-v1` or `journal-v1` |
| `models_used` | map task → model | e.g. `stt`, `fill_day`, `update_day` |
| `generated_at` | ISO-8601 datetime or null | last generation |
| `generated_hash` | string or null | edit detection, see below |
| `generated_source_hash` | string or null | recordings and My notes already incorporated into the journal |
| `lumitrace_format` | int | `6` for a Format 6 content region; a parsed legacy day remains `5` until generation migrates it |
| *anything else* | | preserved as is (e.g. Obsidian `tags`) |

### Format 6 content (`DayContent`)

`DayContent` is the generated source of truth for a new day. The old `DayFacts` and journal
fields remain on `DayFile` as compatibility projections; they are not separately rendered in a
Format 6 file.

The timeline has:

* one optional `highlight`;
* `DayContext`: optional weather, places visited and people met (each may name the participating
  family members), special occasions and media;
* ordered `morning`, `afternoon`, `evening`, `night` and `time_not_stated` lists;
* one optional `remember` detail.

`Time not stated` is omitted when empty. Every other time section is rendered, using a single
`—` bullet when empty. `Remember` follows the time sections.

The family trackers have one row per `FamilyTracker.name`:

| Section | Stored fields |
|---|---|
| Food | breakfast, lunch, dinner, snacks/drinks and food response |
| Health and fitness | sleep, exercise/movement with optional minutes, energy and mood ratings, body/digestion, symptoms/medication |
| Daily routine | work/daycare, responsibilities/activities, reading/learning, screen/media |
| Interests and preferences | enjoyed, disliked/avoided, current interests |
| Growth and learning | learned/practiced, progress/change, new skill/behavior, words/quotes |

The pregnancy table is day-level: pregnant person, gestational age, maternal symptoms,
cravings/aversions, supplements/medication, rest/self-care, baby movement, appointment/scan,
heartbeat/growth and questions/concerns. Tags are stored without a leading `#` and rendered with
one.

**Canonical Markdown.** Empty table values render as `—`. Multiple values in one cell use
`<br>`. A meal keeps the distinction between `not_recorded`, `skipped` and `consumed`;
`Skipped` and `Consumed` are written explicitly when needed. Ratings render as `4/5`,
`4/5 · energetic`, or just the description. Pipes and backslashes in table cells are escaped,
and `parse(render(content)) == content`. The parser reads the canonical headings and table
shape emitted by `render`; it is not a general Markdown-table importer.

### Format 5 compatibility (`DayFacts` and journal)

Format 5 stores an `## At a glance` facts region and a separate journal (ADR 0059). `parse`
continues to read it. `content_for_day` conservatively projects those facts and journal sections
to `DayContent` when generation needs to migrate the day; ordinary parse/render keeps Format 5.

Format 6 also computes a best-effort `DayFacts` projection so existing fact tables and callers
keep working. It includes the highlight, remember value, weather, places, people, special
occasions, consumed or skipped meals, selected health/growth facts and routine activities. It
does not represent every Format 6 field or the full timeline, so Spectrum separately indexes
canonical content and the Lens returns it directly.

The layout is
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
| `### Food` | `FamilyMember.meals`, `meals` | per person: `- **Morning:**`, `**Lunch:**`, `**Dinner:**`, `**Snacks / drinks / other:**` (`MEAL_TYPES` breakfast, lunch, dinner, snacks); `#### Everyone` is the union of those meals, each item tagged with who had it (`oatmeal (Maya, Leo)`) |
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
dinner, `brunch` lunch); a comma splits meal items, except a comma inside parentheses
(`oatmeal (Maya, Leo)` stays one item); members without a name are dropped (members without
facts are kept). The Prism fills `#### Everyone` after the model replies (ADR 0056). The model
is not asked for that list.

Hand edits are tolerated: bullets and bold are optional, headings may use any level, and
common alternative names (`Meals`, `Places`, `People`, `Activities`) are accepted for the
sections. A food line without a known label counts as snacks. Lines that fit nowhere are moved
into `My notes` on the next system write, so nothing is lost. Hand edits are rewritten to the
standard names and lines on the next system write.

### The Format 5 journal

The separate journal exists only in Format 5 and older files. It uses these `##` headings, in
this order, each only when it
has text: `Summary`, `Morning`, `Afternoon`, `Evening`, `Thoughts` (`JOURNAL_SECTIONS`).
`apply_generation` enforces it with `normalize_journal`: text before the first heading goes to
Summary, repeated sections are merged, `Night`/`Tonight` count as Evening and
`Reflections`/`Plans` as Thoughts, and any other heading becomes a bold line in the section it
appears in. Later source is returned as section-classified bullets and
`merge_journal_sections` inserts each one under the requested normal heading. Existing journal
words are never re-normalised or replaced; a missing heading is inserted in the fixed order.

### Older formats

* **Format 6** is the current content-region layout described above.
* **Format 5** has the topic-first At a glance section plus a separate journal. It stays Format
  5 when parsed and rendered; the next successful content generation migrates it.
* **Format 2** (decision 0042 era) had `###` sections Food (five meal lines), Places, People,
  Activities, Family and Highlights, with a seven-line `####` block per member. `parse` reads
  it (`parse_facts_section(..., source_format=2)`) and converts it: a member's food becomes
  that member's meals (snacks when no meal is known), their places and activities become day
  places and things we did marked `(Name)`, school/work becomes things we did, moments become
  memories, and the rest keep their names. A render without generation preserves the legacy
  compatibility layout; generation can migrate it to Format 6.
* **Format 3** is the topic-first "At a glance" layout above. `parse` still reads it and the next
  compatibility render writes Format 5.
* **Format 4** omitted At a glance. `parse` reads it as empty facts. Its next Generate call runs
  even when the source hash is unchanged and migrates the available journal into Format 6
  before applying the model's complete content.
* **Format 1** (0.1.0) kept the facts in the front matter and had no facts region; `parse` reads
  those keys as facts; compatibility rendering uses Format 5 until generation migrates it.

**Edit detection across formats.** `generated_hash` covers the rendered facts, so a day written
in format 1 or 2 cannot reproduce its old hash and looks edited after migration. Generate and
`lumitrace-prism regenerate` still update that day: they keep the title and journal words, add
missing bullets, and merge facts. They do not replace an existing journal (`docs/prism.md`).

### Capture metadata

The `<!-- lumitrace:capture {...} -->` comment holds JSON: `id` (unique within the day; merging an
existing id is a no-op, so retries from the offline inbox are safe), `kind` (`recording` or
`note`), `captured_at` (ISO-8601 with offset), `audio`, `photos`, `location`. The heading and
embed lines are regenerated from it; the text below them is the transcript and may be edited.

**English translation** (`Capture.translation`, ADR 0043). `render` does not write it (ADR 0057).
New recordings never store one. `parse` still reads an older block: everything after
`<!-- lumitrace:translation (...) -->` is the translation (the heading is dropped if present).
The next system write drops the block. The Telugu transcript above it stays. Spectrum indexes a
translation only while the block is still in the file, as passages headed
`HH:MM · Log My Day · English`.

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
  They are direct generation input: the first write and later safe updates use them alongside
  the recordings.
* **Transcript** blocks are append-only; edits to their text are kept.
* **Generated content** carries `generated_hash`. For Format 6 it hashes the title and complete
  typed content; for legacy files it hashes facts, title and journal.
  `DayFile.is_user_edited()` compares the stored hash with the current value.
  * `apply_content_generation(...)` writes complete Format 6 content and refuses an edited day
    unless `force=True`. The first generation uses `force=True`.
  * `merge_content_generation_three_way(...)` merges previous model content, current live
    content and incoming complete content. Owner changes to scalars, lists, rows and cells win;
    untouched model values follow the incoming reply.
  * Timeline update helpers match bullet text exactly. Replacements may move a bullet between
    Morning, Afternoon, Evening, Night and Time not stated; then deletions and additions run.
    Adding an exact duplicate is a no-op.
  * The older `apply_generation`, additive journal and facts merge helpers remain compatibility
    APIs for Format 5 callers.
  * `apply_generation(...)` replaces facts/title/journal, and raises `UserEditsDetected` if the
    owner edited them (unless `force=True`). Only the first journal generation uses
    `force=True`.
  * `merge_generation_additive(...)` only adds: it inserts model-returned bullets into Summary,
    Morning, Afternoon, Evening or Thoughts. A later recording or changed My notes uses this,
    whether or not the owner edited the file. On an edited day it keeps the old hash.
  * `merge_generation_three_way(...)` applies the complete new facts using the model's previous
    `_system/generated-facts/` value as base. Owner additions, changes and removals win. Journal
    bullets still use the additive section merge.
* `generated_source_hash` covers capture ids, times, text and locations plus My notes. It prevents
  repeated Generate clicks and capture replays from adding the same source twice.
* **Stray text** typed outside the regions (or a region whose markers were deleted) is moved into
  `My notes` on the next system write, so nothing is lost.
* Provenance fields (`prompt_version`, `models_used`, `generated_at`) and transcript text are not
  part of the hash.

The Prism also writes the exact rendered file to `generated_snapshot_path(d)` every time
it writes a day file; Spectrum diffs the live file against that snapshot to record
`edit_signals`. The separate generated-facts JSON stores the model-owned merge base; it must
not replace the exact snapshot.

## Example

The fenced file below is an older format 3 day (`tests/fixtures/sample-day.md`). `parse` still
reads it. A compatibility `render` preserves "At a glance" and omits any translation. Format 2 is
`tests/fixtures/sample-day-v2.md` and format 1 is `tests/fixtures/sample-day-v1.md`.

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
  stt: sarvam/saaras:v4
  fill_day: gemini/gemini-3.8-flash
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
source_hash = day.compute_source_hash()
state = read_generated_facts(day_date)
snapshot = read_generated_snapshot(day_date)
base_content = state.content if state and state.content else (
    content_for_day(snapshot) if snapshot else None
)
if day.meta.generated_at is None:
    day = apply_content_generation(
        day, content=generated_content, title=title,
        generated_source_hash=source_hash, force=True, ...
    )
elif day.meta.generated_source_hash != source_hash or state is None:
    day = merge_content_generation_three_way(
        day, base_content=base_content, content=generated_content,
        generated_source_hash=source_hash, ...
    )
else:
    return "unchanged"
text = render(day)
storage.write_text(path, text)
storage.write_text(generated_snapshot_path(day_date), text)
write_generated_facts(day_date, source_hash, generated_content)
```

## Changing the format

Bump `FORMAT_VERSION`, keep `parse` able to read older versions, add tests with an old-format
fixture, and update this page, `docs/contracts.md` and `CHANGELOG.md` in the same commit. Keep
`LEGACY_FORMAT_VERSION` explicit when an old layout can still be rendered unchanged.
