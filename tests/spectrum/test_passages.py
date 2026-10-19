from __future__ import annotations

import datetime as dt

from lumitrace.frames import daycontent as C
from lumitrace.frames.dayfile import DayFile, parse
from lumitrace.spectrum.passages import (
    MAX_CHARS,
    build_passages,
    chunk_text,
    split_by_headings,
)


def test_sample_day_passages(sample_day_markdown: str) -> None:
    day = parse(sample_day_markdown)
    passages = build_passages(day)
    sections = [p.section for p in passages]
    assert sections[0] == "title"
    assert set(sections) == {"title", "facts", "journal", "notes", "transcript"}

    journal = [p for p in passages if p.section == "journal"]
    assert [p.heading for p in journal] == ["Summary", "Morning", "Afternoon", "Evening"]
    assert [p.ordinal for p in journal] == [0, 1, 2, 3]
    assert "Fish tacos" in journal[2].text
    assert all(not p.text.startswith("#") for p in journal)

    transcript = [p for p in passages if p.section == "transcript"]
    assert [p.capture_id for p in transcript] == [c.id for c in day.captures]
    assert transcript[0].heading == "13:05 · Quick Note"
    assert [p.ordinal for p in transcript] == list(range(len(transcript)))

    facts = {p.heading: p.text for p in passages if p.section == "facts"}
    assert list(facts) == [
        None,
        "Highlight",
        "Food · Sam",
        "Food · Maya",
        "Food · Leo",
        "Places visited",
        "People we met or visited",
        "Feelings · Sam",
        "Feelings · Leo",
        "Memories · Together",
        "Memories · Leo",
        "Weather",
        "Things we did",
    ]
    assert [p.ordinal for p in passages if p.section == "facts"] == list(range(13))
    assert facts["Food · Leo"] == "- **Dinner:** pasta"
    assert facts["Food · Maya"] == "- **Lunch:** fish tacos"
    assert "- **Mood:** happy (4/5)" in facts[None]
    assert "- **Morning:** oatmeal, blueberries" in facts["Food · Sam"]
    assert "- **Remember:** Leo lost his first tooth and was very proud" in facts["Highlight"]
    assert facts["Places visited"].splitlines()[0] == "- the river trail (Sam)"
    assert facts["Things we did"] == "- run (Sam) (40 min)\n- reading (Sam)"
    assert facts["Weather"] == "- sunny, 24°C"
    assert all(len(p.text) <= MAX_CHARS for p in passages)


def test_text_hash_covers_heading() -> None:
    from lumitrace.spectrum.passages import Passage

    a = Passage("journal", "Morning", None, 0, "Soup.")
    b = Passage("journal", "Evening", None, 0, "Soup.")
    assert a.text_hash != b.text_hash
    assert a.embed_input == "Morning\nSoup."


def test_chunk_text_packs_paragraphs_and_splits_long_ones() -> None:
    short = "One.\n\nTwo.\n\nThree."
    assert chunk_text(short) == ["One.\n\nTwo.\n\nThree."]

    sentence = "We walked along the river and talked about the week ahead. "
    long_para = sentence * 60
    chunks = chunk_text(long_para, max_chars=300)
    assert len(chunks) > 1
    assert all(len(c) <= 300 for c in chunks)
    assert " ".join(chunks).split() == long_para.split()


def test_chunk_text_hard_splits_giant_words() -> None:
    chunks = chunk_text("x" * 2500, max_chars=1000)
    assert [len(c) for c in chunks] == [1000, 1000, 500]
    assert chunk_text("   ") == []


def test_split_by_headings_ignores_code_fences_and_keeps_heading_only_sections() -> None:
    md = "Intro line\n\n## Sleep: 8 hours\n## Code\n```\n# not a heading\n```\n"
    parts = split_by_headings(md)
    assert parts[0] == (None, "Intro line")
    assert parts[1] == ("Sleep: 8 hours", "")
    assert parts[2][0] == "Code"
    assert "# not a heading" in parts[2][1]


def test_translation_gets_its_own_transcript_passages() -> None:
    import datetime as dt
    from zoneinfo import ZoneInfo

    from lumitrace.frames.dayfile import Capture, DayFile

    day = DayFile.new(dt.date(2026, 10, 10))
    at = dt.datetime(2026, 10, 10, 21, 30, tzinfo=ZoneInfo("America/Chicago"))
    day.captures = [
        Capture(
            id="c1",
            kind="recording",
            captured_at=at,
            text="mana park ki vellam",
            translation="We went to the park.",
        )
    ]
    transcript = [p for p in build_passages(day) if p.section == "transcript"]
    assert [(p.heading, p.capture_id, p.ordinal, p.text) for p in transcript] == [
        ("21:30 · Log My Day", "c1", 0, "mana park ki vellam"),
        ("21:30 · Log My Day · English", "c1", 1, "We went to the park."),
    ]


def test_empty_day_has_title_only() -> None:
    day = DayFile.new(dt.date(2026, 1, 2))
    passages = build_passages(day)
    assert [p.section for p in passages] == ["title"]


def test_format6_passages_use_canonical_content() -> None:
    day = DayFile.new(dt.date(2026, 10, 12))
    day.content = C.DayContent(
        timeline=C.Timeline(
            morning=["Packed cardamom pancakes"],
            context=C.DayContext(
                people_met=[
                    C.PersonContext(
                        name="Dr. Rao",
                        relationship="pediatrician",
                        context="annual visit",
                    )
                ]
            ),
        ),
        family=[
            C.FamilyTracker(
                name="Maya",
                growth_learning=C.GrowthLearning(new_skill_behavior=["rode a bicycle"]),
            )
        ],
        pregnancy_baby=C.PregnancyBaby(baby_movement=["two strong kicks"]),
        tags=["family-adventure"],
    )

    passages = build_passages(day)

    assert "content" in {passage.section for passage in passages}
    assert "facts" not in {passage.section for passage in passages}
    assert "journal" not in {passage.section for passage in passages}
    content = [passage for passage in passages if passage.section == "content"]
    assert any(p.heading == "Morning" and "cardamom pancakes" in p.text for p in content)
    assert any(p.heading == "Day context" and "annual visit" in p.text for p in content)
    assert any(p.heading == "Growth and learning" and "rode a bicycle" in p.text for p in content)
    assert any(p.heading == "Pregnancy and baby" and "two strong kicks" in p.text for p in content)
    assert any(p.heading == "Tags" and "#family-adventure" in p.text for p in content)
