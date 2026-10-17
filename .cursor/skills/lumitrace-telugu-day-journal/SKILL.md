---
name: lumitrace-telugu-day-journal
description: Fill a Lumitrace day file (docs/templates/day-template.md) from Telugu voice transcripts and their machine English translation, without inventing facts. Use when writing, checking or fixing a day's journal, food, places, health, feelings or memories from Telugu recordings.
---

# Telugu transcript to Lumitrace day file

## Before you start
- Read `docs/templates/day-template.md`. It is the output shape.
- Read `glossary.local.md` in this folder. It holds the real names, relations and fixes. It is git-ignored.
  - Missing? Copy `glossary.example.md` to `glossary.local.md` and fill it in.
- Read the family list: `LUMITRACE_FAMILY` (`Name (me)` marks the author).
- Read every capture of the day, oldest first.

## What the input looks like
- Audio is mostly Telugu, often mixed with English words.
- The Prism gives two texts per recording:
  - **Original transcript** (Telugu, as spoken).
  - **English translation** (made by Sarvam from the audio, with no family context).
- The journal is written in **English**.

## Source rules
- The Telugu original wins when the two texts disagree (ADR 0018).
- Use the English translation as a hint for meaning only.
- No translation (the job failed)? Work from the Telugu alone.
- Two recordings disagree? The newer one wins. Keep both in the transcript section.
- Facts JSON from another model can be wrong. The transcript wins over it.

## Steps
1. List the people in the day. Match every name to the family list or the glossary.
2. For each sentence, find the subject.
   - Telugu verb endings show who did it.
   - The translation often guesses wrong. Re-derive the subject from the Telugu.
3. Tag each event: who, what, where, when, any feeling word.
4. Check names and sound-alikes against the glossary.
5. Fill each template section from the tags.
6. Make it quick to read: short bullets, one fact each.
7. Run the check list.

## The main rule
- Every line needs a phrase in the transcript behind it.
- Not said: write `not mentioned`.
- Said but unclear: end the line with `[uncertain: <why>]`.
- Never fill a gap to make a section look complete.

## Known translation errors
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
  - A bare "Nanna" is unclear. Check the verb and the scene, else mark `[uncertain]`.
- **Foods**
  - Keep the Telugu word with English in brackets.
  - Do not swap one dish for a similar one (thotakura is amaranth, not spinach).

## Section rules
- **Highlight**
  - 3 to 5 short bullets in time order.
  - End with `Remember:` and the one moment worth keeping.
  - Keep small emotional moments.
- **Food**
  - Split by person, then Morning / Lunch / Dinner / Snacks.
  - "We" means everyone present. A named person means only that person.
  - Delivery is food, not a visit.
- **Places visited**
  - Only places someone physically went.
  - Add who went.
  - Keep spoken names ("Ravi's house").
- **People we met or visited**
  - Real people only, with relation and who met them.
  - Daycare friends and relatives go here.
  - A TV show is not a person.
- **Health and fitness**
  - High bar: only what was plainly said.
  - A guess is not a health fact.
- **Feelings**
  - Stated emotions only, per person.
  - Behaviour is not a feeling.
  - No invented cause.
- **Memories**
  - Exact quotes, firsts, sweet moments.
  - One line each, with the name.
- **Weather**
  - Only from a lookup by place and date.
  - Otherwise `not looked up`.
- **Things we did**
  - One activity per bullet, with who.
- **Audio and transcript**
  - Telugu untouched. English translation under it.

## Never do
- Invent a meal, place, symptom, feeling or reason (no "omelet", no "went to <store>", no "felt sad because of X").
- Put one person's food, places or health under another person.
- Count a delivery as a visit.
- Treat a show or character as a friend.
- Drop an emotional moment because it seems small.
- Edit the raw Telugu.

## Check list
- [ ] Every bullet has a phrase behind it.
- [ ] Each action's subject re-checked against the Telugu.
- [ ] Nobody's food, places or health sits under someone else.
- [ ] No delivery under Places. No show under People.
- [ ] Every family member has a subsection in every per-person section.
- [ ] Unclear items carry `[uncertain: ...]`.
- [ ] Newer recordings override older ones.
- [ ] Highlight ends with `Remember:`.
- [ ] Reads in under a minute.

## When you learn a new error
- Add it to `glossary.local.md`.
- If it is a pattern (not just one name), add a line under "Known translation errors" and to `docs/learnings.md`.
