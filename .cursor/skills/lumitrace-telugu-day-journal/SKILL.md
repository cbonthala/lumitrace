---
name: lumitrace-telugu-day-journal
description: Fill a Lumitrace day file (prompts/day-template.md) from Telugu code-mixed transcripts and the family file, without inventing facts. Use when writing, checking or fixing a day's journal, food, places, health, feelings or memories from Telugu recordings.
---

# Telugu transcript to Lumitrace day file

## Before you start
- Read `prompts/day-template.md`. It defines the structured facts and is pasted into the
  fill-day prompt.
- The day file has a title, At a glance facts, the journal (Summary, Morning, Afternoon,
  Evening, Thoughts), My notes, and the Telugu transcript. Do not write a translation.
- Read `secrets/family.md` at the repository root. It holds the family (names, relations, birth dates) and the notes (other people, relation words, foods, places, usual routines). It is git-ignored.
  - Missing? Copy `docs/templates/family.example.md` to `secrets/family.md` and fill it in.
- The person with `relation: me` is the author.
- Read every capture of the day, oldest first.

## What the input looks like
- Audio is mostly Telugu, often mixed with English words.
- The Prism gives one text per recording: the code-mixed transcript (English words in English, Telugu in Telugu script). There is no English translation (ADR 0048).
- An older day file may still show a translation. Ignore it. The Telugu transcript is the
  source; write the structured facts from the transcript and My notes.
- Names, relations and spellings are in `secrets/family.md`.
- The journal is written in **English**.

## Source rules
- Read the Telugu. Verb endings show who did it.
- Two recordings disagree? The newer one wins. Keep both in the transcript section.
- The recordings and the day's My notes are the only sources for what happened today. My notes
  are direct owner input and win when they correct a recording.
- Cover the transcript to its last sentence. Before returning, check the final third of each recording is reflected in the journal or facts.
- Keep events in the order they were spoken. Reorder only when a time is stated.
- If the speaker says నిన్న or "yesterday", those events belong to the previous date, not today.
- Every proper noun must appear in the transcript, keyterms, or glossary. Otherwise write [uncertain: name unclear]. Never invent a name.

## Steps
1. List the people in the day. Match every name to `secrets/family.md`.
2. For each sentence, find the subject.
   - Telugu verb endings show who did it.
3. Tag each event: who, what, where, when, any feeling word.
4. Check names and sound-alikes against the family file.
5. Cover each checklist topic in the structured facts and inside the journal.
6. Make it quick to read: short bullets, one fact each.
7. Run the check list.

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
  - 3 to 5 short bullets in time order.
  - End with `Remember:` and the one moment worth keeping.
  - Keep small emotional moments.
- **Food**
  - Split by person, then breakfast, lunch, dinner, snacks, drinks.
  - "We" means everyone present. A named person means only that person.
  - Give an item to a person only if the transcript names them or uses 'we' for it. 'I drank coffee' is the author only.
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
  - Null unless a weather lookup is passed in as input.
  - The transcript does not set the weather.
- **Things we did**
  - One activity per bullet, with who.
- **Audio and transcript**
  - Telugu untouched. Do not add an English translation.

## Never do
- Invent a meal, place, symptom, feeling or reason (no "omelet", no "went to <store>", no "felt sad because of X").
- Put one person's food, places or health under another person.
- Count a delivery as a visit.
- Treat a show or character as a friend.
- Drop an emotional moment because it seems small.
- Edit the raw Telugu.

## Check list
- [ ] Every bullet has a phrase behind it.
- [ ] The final third of each recording shows up in the journal or facts.
- [ ] An "I" item is the author's only. A shared item names the person or says "we".
- [ ] Each action's subject re-checked against the Telugu.
- [ ] Nobody's food, places or health sits under someone else.
- [ ] No delivery under Places. No show under People.
- [ ] Every family member has a subsection in every per-person section.
- [ ] Unclear items carry `[uncertain: ...]`.
- [ ] Newer recordings override older ones.
- [ ] Highlight ends with `Remember:`.
- [ ] Reads in under a minute.

## When you learn a new error
- Add it to `secrets/family.md`.
- If it is a pattern (not just one name), add a line under "Known hearing errors" and to `docs/learnings.md`.
