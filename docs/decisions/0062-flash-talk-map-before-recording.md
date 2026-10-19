# 0062. Flash shows a Format 6 talk map before recording

- Status: accepted
- Date: 2026-10-19

## Context

Format 6 day files have a timeline, day context, per-person food, health, routine, likes and
growth tables, and a pregnancy tracker. A spoken Log My Day take only fills those cells if the
owner actually says them. A long checklist is too much to read at the microphone. The owner
asked for a popup on the red record button that covers the whole page without turning into an
essay.

## Decision

* Tapping the red button on an idle Capture card opens a bottom sheet (a centred card from
  600 px) of glanceable tiles, one `data-field` per speakable Format 6 path.
* **Start talking** starts the microphone. The sheet stays open so the owner can scroll the
  cards while talking. Discard, Pause/Resume and Stop use the same icons as the record card.
  Tapping a card marks it covered. The sheet does not upload. After Stop, review, crop and Send
  are unchanged (ADR 0054).
* Tags are omitted (derived). `pregnant_person` is omitted (it comes from the family file).
  Weather, gestational age and heartbeat still appear, with copy that says not to guess.
* The Flash web test walks `DayContent` and fails if a new speakable field has no tile.

## Consequences

* The first tap no longer starts the mic. **Start talking** does. Escape or a tap on the
  dimmed background closes the sheet only before the mic starts. While recording, the map stays
  until Stop or Discard.
* iPhone Shortcuts are unchanged; they have no talk map.
* Not yet checked on a real iPhone Home Screen.
