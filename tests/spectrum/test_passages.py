from __future__ import annotations

from lumitrace.frames.dayfile import parse
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
        "Food",
        "Places",
        "People",
        "Activities",
        "Leo",
        "Maya",
        "Highlights",
    ]
    assert [p.ordinal for p in passages if p.section == "facts"] == list(range(8))
    assert (
        facts["Leo"] == "- **Mood:** proud\n- **Ate:** pasta\n- **Moments:** lost his first tooth"
    )
    assert "- **Mood:** happy (4/5)" in facts[None]
    assert "- **Breakfast:** oatmeal, blueberries" in facts["Food"]
    assert facts["Places"] == "- the river trail\n- the taco truck\n- home"
    assert facts["Activities"] == "- run (40 min)\n- reading"
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


def test_empty_day_has_title_only() -> None:
    import datetime as dt

    from lumitrace.frames.dayfile import DayFile

    day = DayFile.new(dt.date(2026, 1, 2))
    passages = build_passages(day)
    assert [p.section for p in passages] == ["title"]
