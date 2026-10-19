---
name: lumitrace-telugu-day-journal
description: Fill a Lumitrace day file (prompts/day-template.md) from Telugu code-mixed transcripts and the family file, without inventing facts. Use when writing, checking or fixing a day's journal, food, places, health, feelings or memories from Telugu recordings.
---

# Telugu transcript to Lumitrace day file

## Before you start
- Read `prompts/day-template.md`. It defines the Format 6 timeline and family tracker tables and
  is pasted into both day prompts.
- The day file has a title, one generated content region, My notes, and the Telugu transcript.
  The content region has a chronological timeline, family trackers, pregnancy/baby details and
  tags. Do not write a separate journal or translation.
- Read `secrets/family.md` at the repository root. It holds the family (names, relations, birth dates) and the notes (other people, relation words, foods, places, usual routines). It is git-ignored.
  - Missing? Copy `docs/templates/family.example.md` to `secrets/family.md` and fill it in.
- The person with `relation: me` is the author.
- Read every capture of the day, oldest first.

## What the input looks like
- Audio is mostly Telugu, often mixed with English words.
- The Prism gives one text per recording: the code-mixed transcript (English words in English, Telugu in Telugu script). There is no English translation (ADR 0048).
- An older day file may still show a translation or the Format 5 At a glance/journal layout.
  Ignore the translation. The Telugu transcript and My notes are the sources for new content.
- Names, relations and spellings are in `secrets/family.md`.
- Timeline and tracker text are written in **English**.

## Source rules
- Read the Telugu. Verb endings show who did it.
- Two recordings disagree? The newer one wins. Keep both in the transcript section.
- The recordings and the day's My notes are the only sources for what happened today. My notes
  are direct owner input and win when they correct a recording. Capture metadata is evidence
  only for its time, location and attached media; weather requires a supplied lookup.
- Cover the transcript to its last sentence. Before returning, check the final third of each
  recording is reflected in the timeline or trackers, or intentionally omitted as repeated,
  corrected, irrelevant or too uncertain.
- Keep events in the order they were spoken. Reorder only when a time is stated.
- If the speaker says నిన్న or "yesterday", those events belong to the previous date, not today.
- A plan is not a completed event. A canceled or skipped plan is included only when stated.
- A small inference is allowed only when one interpretation follows from an explicit fact and it
  adds no event, person, feeling, quantity or cause. Never calculate duration, gestational age
  or a score.
- Every proper noun must appear in the transcript, My notes, keyterms, glossary or configured
  family background. Otherwise write `[uncertain: name unclear]`. Never invent a name.

For an update, the current page is authoritative where the owner may have edited it. Preserve
its wording and facts unless newer evidence directly contradicts them. Do not remove something
merely because it is absent from the recordings.

## Steps
1. List the people in the day. Match every name to `secrets/family.md`.
2. For each sentence, find the subject.
   - Telugu verb endings show who did it.
3. Tag each event: who, what, where, when, any feeling word.
4. Check names and sound-alikes against the family file.
5. Put each fact in its most specific tracker; use the timeline only when it contributes to the
   story.
6. Make it quick to read: short bullets, one fact each.
7. On an update, identify exact timeline additions, replacements or deletions.
8. Run the check list.

## The main rule
- Every line needs a phrase in the transcript behind it.
- If you cannot tell what happened, drop it. If you can tell what happened but not a detail, keep it and end with `[uncertain: why]`.
- Never fill a gap to make a section look complete.

## Known hearing errors
- **Wrong subject**
  - The speaker became "my father".
  - "He didn't give the kiss" was the daughter.
  - The dad put the daughter in the car, not the reverse.
- **Sound-alike words**
  - potty heard as "party"
  - straw heard as "strong"
  - a sweet's name heard as a person's name
- **Wrong names**
  - two similar names mixed up (e.g. a child and her daycare friend)
  - a kids' TV show read as a friend
- **Relation words** (Nanna, Amma, Thatha, ...)
  - Resolve them from the speaker's point of view.
  - Telugu parents often say "<child's name> Nanna" for themselves.
  - "my Nanna" is the speaker's own father.
  - When the author is talking about their own child, a bare Nanna (నాన్న) means the author. Otherwise end the item with [uncertain: who is Nanna].
- **Foods**
  - Keep the Telugu word with English in brackets.
  - Do not swap one dish for a similar one (thotakura is amaranth, not spinach).

## Section rules
- **Highlight**
  - At most one explicit, meaningful, important or unusual event.
  - `Remember` is separate: one vivid quote, gesture, expression, funny detail or milestone.
  - Do not repeat Highlight word for word; leave either field empty when nothing stands out.
- **Timeline**
  - Morning, Afternoon, Evening and Night require support from a time, temporal phrase, meal,
    waking, bedtime or nearby clearly timed context.
  - Put a valid event in Time not stated when its time cannot be determined.
  - One concise past-tense event per bullet. Do not copy routine table details into the story.
- **Day context**
  - Weather comes only from a supplied lookup.
  - Places are physical visits; list participating family members only when known.
  - People are non-household people actually met or visited, with relation/context when stated.
  - Media comes only from capture metadata or an explicit existing reference.
- **Food**
  - One row per configured person. Each meal status is consumed, skipped or not recorded.
  - "We" always includes the author; assign it to anyone else only when they are clear.
  - A first-person verb stays with the author even when someone else was present.
  - Drinks go under snacks/drinks. Delivery is food, not a visit.
  - Food response requires an explicit appetite, preference or physical response.
- **Health and fitness**
  - Record sleep, movement, energy, mood, body/digestion, symptoms and medication only when
    plainly said.
  - Mood and energy descriptions keep the speaker's wording. A score exists only when stated.
  - Behaviour is not a feeling; chronology alone is not a food reaction or cause.
  - Exercise minutes are an integer only when that exact duration was spoken. Do not multiply,
    average or choose the midpoint of a range.
- **Pregnancy and baby**
  - The family file may identify the pregnant person but is not evidence for today's details.
  - Do not calculate gestational age or interpret symptoms and medical results.
  - Record symptoms, cravings, medication, rest, movement, appointments and concerns only when
    explicitly stated.
- **Daily routine**
  - Work/daycare attendance is not assumed from normal routine.
  - Put chores, errands, caregiving and appointments under responsibilities; intentional
    exercise stays under health.
  - Reading/learning and screen/media require explicit activity.
- **Interests and preferences**
  - Enjoyed, disliked or avoided requires an explicit statement or unambiguous response.
  - A current interest needs evidence that it is ongoing; one ordinary action is not enough.
- **Growth and learning**
  - Practice is intentional; progress needs a comparison; a new skill needs "new", "first" or a
    meaningful stated change.
  - Preserve reliable exact quotes. Do not label ordinary toddler behavior as development.
- **Tags**
  - Use a small number of stable, supported tags. Do not copy template examples or create
    diagnoses and personality labels.
- **Transcript**
  - Telugu stays untouched. Do not add an English translation.

## Never do
- Invent a meal, place, symptom, feeling or reason (no "omelet", no "went to <store>", no "felt sad because of X").
- Put one person's food, places or health under another person.
- Count a delivery as a visit.
- Treat a show or character as a friend.
- Turn a plan into an event, behavior into a feeling, or one action into a lasting preference or
  milestone.
- Duplicate the same detailed fact across timeline and trackers.
- Reword or reorganize an existing owner-edited page for style.
- Edit the raw Telugu.

## Check list
- [ ] Every bullet has a phrase behind it.
- [ ] The final third of each recording was checked.
- [ ] An "I" item is the author's only. A shared item names the person or says "we".
- [ ] Each action's subject re-checked against the Telugu.
- [ ] Nobody's food, places or health sits under someone else.
- [ ] No delivery under Places. No show under People.
- [ ] Every configured family member has exactly one tracker row.
- [ ] Unclear items carry `[uncertain: ...]`.
- [ ] Newer recordings override older ones.
- [ ] Timeline periods are supported; otherwise Time not stated is used.
- [ ] Highlight and Remember each have at most one distinct item.
- [ ] Scores, durations and pregnancy details were not calculated.
- [ ] Updates preserve existing words and use exact timeline matches.
- [ ] Reads in under a minute.

## When you learn a new error
- Add it to `secrets/family.md`.
- If it is a pattern (not just one name), add a line under "Known hearing errors" and to `docs/learnings.md`.
