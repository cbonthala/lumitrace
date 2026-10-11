from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from lumen.frames import dayfile as D

TZ = ZoneInfo("America/Chicago")
DAY = dt.date(2026, 10, 10)


def at(hour: int, minute: int = 0, day: int = 10) -> dt.datetime:
    return dt.datetime(2026, 10, day, hour, minute, tzinfo=TZ)


def capture(cid: str, when: dt.datetime, **kw) -> D.Capture:
    return D.Capture(id=cid, kind=kw.pop("kind", "note"), captured_at=when, **kw)


# --- paths ----------------------------------------------------------------------------------


def test_path_conventions() -> None:
    assert D.day_dir(DAY) == "2026/10/2026-10-10"
    assert D.day_file_path(DAY) == "2026/10/2026-10-10/2026-10-10.md"
    assert D.audio_file_name(DAY, at(21, 30)) == "2026-10-10-2130.m4a"
    assert D.audio_file_name(DAY, at(1, 30, day=11)) == "2026-10-10-0130.m4a"
    assert D.audio_file_path(DAY, dt.time(9, 5)) == "2026/10/2026-10-10/2026-10-10-0905.m4a"
    assert D.photo_file_name(1) == "photo-01.jpg"
    assert D.photo_file_name(123) == "photo-123.jpg"
    assert D.photo_file_path(DAY, 2) == "2026/10/2026-10-10/photo-02.jpg"
    assert D.generated_snapshot_path(DAY) == "_system/generated/2026/10/2026-10-10.md"
    assert D.system_path("runs", "/2026/") == "_system/runs/2026"
    with pytest.raises(ValueError):
        D.photo_file_name(0)


def test_next_photo_names_and_unique_names() -> None:
    assert D.next_photo_names([], 2) == ["photo-01.jpg", "photo-02.jpg"]
    assert D.next_photo_names(["photo-01.jpg", "x/photo-07.jpg", "other.jpg"], 1) == [
        "photo-08.jpg"
    ]
    assert D.unique_file_name("a.m4a", []) == "a.m4a"
    assert D.unique_file_name("a.m4a", ["a.m4a", "a-2.m4a"]) == "a-3.m4a"
    assert D.unique_file_name("README", ["README"]) == "README-2"


def test_parse_day_file_path_and_classify() -> None:
    assert D.parse_day_file_path("2026/10/2026-10-10/2026-10-10.md") == DAY
    assert D.parse_day_file_path("2026/11/2026-10-10/2026-10-10.md") is None
    assert D.parse_day_file_path("2026/10/2026-10-10/2026-10-11.md") is None
    assert D.parse_day_file_path("2026/02/2026-02-30/2026-02-30.md") is None
    assert D.parse_day_file_path("Lumen/2026/10/2026-10-10/2026-10-10.md") is None
    assert D.date_of_path("2026/10/2026-10-10/photo-01.jpg") == DAY
    assert D.classify_path("2026/10/2026-10-10/2026-10-10.md") == "day"
    assert D.classify_path("2026/10/2026-10-10/2026-10-10-2130.m4a") == "audio"
    assert D.classify_path("2026/10/2026-10-10/photo-03.jpg") == "photo"
    assert D.classify_path("2026/10/2026-10-10/scan.pdf") == "other"
    assert D.classify_path("_system/runs/x.json") == "system"
    assert D.classify_path("inbox/thing.md") == "other"


# --- entry dates ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        (at(21, 30), DAY),
        (at(4, 0), DAY),
        (at(3, 59), dt.date(2026, 10, 9)),
        (at(0, 40, day=11), DAY),
        (at(23, 59), DAY),
    ],
)
def test_entry_date_rollover(when: dt.datetime, expected: dt.date) -> None:
    assert D.entry_date(when, TZ, 4) == expected


def test_entry_date_converts_timezones_and_naive() -> None:
    utc = dt.datetime(2026, 10, 11, 5, 0, tzinfo=dt.UTC)  # 00:00 in Chicago (CDT)
    assert D.entry_date(utc, "America/Chicago", 4) == DAY
    assert D.entry_date(utc, "UTC", 4) == dt.date(2026, 10, 11)
    assert D.entry_date(dt.datetime(2026, 10, 11, 2, 0), "America/Chicago") == DAY
    assert D.entry_date(at(2), TZ, rollover_hour=0) == DAY


# --- model ----------------------------------------------------------------------------------


def test_new_day_defaults() -> None:
    day = D.DayFile.new(DAY)
    assert day.title == "Saturday, October 10, 2026"
    assert day.meta.lumen_format == D.FORMAT_VERSION
    assert day.meta.generated_hash is None
    assert not day.is_user_edited()


def test_capture_requires_aware_datetime() -> None:
    with pytest.raises(ValueError):
        D.Capture(id="x", kind="note", captured_at=dt.datetime(2026, 10, 10, 9, 0))


# --- parse / render -------------------------------------------------------------------------


def test_sample_fixture_roundtrips(sample_day_markdown: str) -> None:
    day = D.parse(sample_day_markdown)
    assert day.date == DAY
    assert day.title == "Saturday, October 10, 2026 · First tooth"
    assert day.meta.people == ["Maya", "Leo"]
    assert day.meta.meals[0] == D.Meal(type="breakfast", items=["oatmeal", "blueberries"])
    assert day.meta.activities[1] == D.Activity(kind="reading", minutes=None)
    assert day.meta.audio == ["2026-10-10-2130.m4a"]
    assert day.meta.photos == ["photo-01.jpg", "photo-02.jpg"]
    assert day.meta.models_used["write_journal"] == "openai/gpt-4o"
    assert day.meta.generated_at == dt.datetime(2026, 10, 11, 0, 41, tzinfo=TZ)
    assert day.journal.startswith("## Summary")
    assert day.notes == "Remember to put the tooth under the pillow tomorrow too."
    assert [c.id for c in day.captures] == [
        "20261010T130500-note",
        "20261010T213000-recording",
        "20261011T004000-note",
    ]
    rec = day.captures[1]
    assert rec.kind == "recording"
    assert rec.audio == "2026-10-10-2130.m4a"
    assert rec.photos == ["photo-01.jpg", "photo-02.jpg"]
    assert rec.text.startswith("Long day.")
    assert not day.is_user_edited()
    assert D.render(day) == sample_day_markdown


@pytest.mark.parametrize("old_name", ["lifelog", "bookshelf"])
def test_parses_files_written_before_the_rename(sample_day_markdown: str, old_name: str) -> None:
    legacy = sample_day_markdown.replace("<!-- lumen:", f"<!-- {old_name}:").replace(
        "lumen_format:", f"{old_name}_format:"
    )
    assert "lumen" not in legacy
    day = D.parse(legacy)
    assert day == D.parse(sample_day_markdown)
    assert day.meta.model_extra == {}
    assert D.render(day) == sample_day_markdown


def test_roundtrip_model_equality_with_tricky_content() -> None:
    day = D.DayFile(
        meta=D.FrontMatter(
            date=DAY,
            mood="yes",
            people=["O'Brien", "Zoë"],
            highlights=["null", "a: b", "- dash"],
            models_used={"stt": "fake"},
            generated_at=at(22),
            tags=["journal", "family"],
        ),
        title="Title with # hash and --> arrow",
        journal="## Section\n\nLine with <!-- comment --> and ![[photo-01.jpg]]",
        notes="# Not the title\n\nMy own *notes*.",
        captures=[
            capture(
                "c1",
                at(9),
                kind="recording",
                text='Has --> arrow and "quotes" and > angle\n\nSecond paragraph',
                audio="2026-10-10-0900.m4a",
                photos=["photo-01.jpg"],
                location='Paris -> "France"',
            ),
            capture("c2", at(10), text=""),
            capture("c3", at(11), text="![[not-an-embed-of-mine.png]] starts the text"),
        ],
    )
    md = D.render(day)
    parsed = D.parse(md)
    assert parsed == day
    assert D.render(parsed) == md
    assert parsed.meta.model_extra == {"tags": ["journal", "family"]}


def test_docs_example_matches_fixture(sample_day_markdown: str) -> None:
    from pathlib import Path

    doc = (Path(__file__).resolve().parents[2] / "docs" / "frames-format.md").read_text()
    example = doc.split("## Example", 1)[1].split("```markdown\n", 1)[1].split("\n```\n", 1)[0]
    assert example + "\n" == sample_day_markdown


def test_render_layout_markers_in_order(sample_day_markdown: str) -> None:
    md = sample_day_markdown
    order = [
        md.index("---\n"),
        md.index("\n# "),
        md.index(D.JOURNAL_START),
        md.index(D.JOURNAL_END),
        md.index(D.NOTES_HEADING),
        md.index(D.NOTES_START),
        md.index(D.NOTES_END),
        md.index(D.TRANSCRIPT_HEADING),
        md.index(D.TRANSCRIPT_START),
        md.index(D.TRANSCRIPT_END),
    ]
    assert order == sorted(order)


def test_parse_errors() -> None:
    with pytest.raises(D.DayFileParseError):
        D.parse("# no front matter\n")
    with pytest.raises(D.DayFileParseError):
        D.parse("---\ndate: [unclosed\n---\n")
    with pytest.raises(D.DayFileParseError):
        D.parse("---\nmood: ok\n---\n")
    with pytest.raises(D.DayFileParseError):
        D.parse("---\ndate: 2026-10-10\nmood_score: 9\n---\n")


def test_parse_minimal_and_fallback_date() -> None:
    day = D.parse("---\n---\n\nJust some text.\n", fallback_date=DAY)
    assert day.date == DAY
    assert day.notes == "Just some text."
    assert day.title == D.default_title(DAY)
    assert day.captures == []


def test_parse_tolerates_windows_newlines_and_bom(sample_day_markdown: str) -> None:
    crlf = "\ufeff" + sample_day_markdown.replace("\n", "\r\n")
    assert D.parse(crlf) == D.parse(sample_day_markdown)


def test_stray_text_moves_into_notes_and_is_never_lost(sample_day_markdown: str) -> None:
    edited = (
        sample_day_markdown.replace("## My notes", "Typed above my notes heading.\n\n## My notes")
        + "\nTyped at the very end.\n"
    )
    edited = edited.replace(
        D.TRANSCRIPT_START, D.TRANSCRIPT_START + "\nStray inside transcript before captures."
    )
    day = D.parse(edited)
    assert day.notes.startswith("Remember to put the tooth")
    for text in [
        "Typed above my notes heading.",
        "Typed at the very end.",
        "Stray inside transcript before captures.",
    ]:
        assert text in day.notes
    rendered = D.render(day)
    assert D.parse(rendered) == day


def test_missing_markers_keep_content_as_notes(sample_day_markdown: str) -> None:
    stripped = sample_day_markdown.replace(D.JOURNAL_START, "").replace(D.JOURNAL_END, "")
    day = D.parse(stripped)
    assert day.journal == ""
    assert "A full, happy Saturday" in day.notes
    assert day.is_user_edited()


def test_user_edited_transcript_text_is_preserved(sample_day_markdown: str) -> None:
    edited = sample_day_markdown.replace("Fish tacos and a horchata.", "Fish tacos, horchata.")
    day = D.parse(edited)
    assert day.captures[0].text == "Lunch at the taco truck with Maya. Fish tacos, horchata."
    assert not day.is_user_edited()  # transcript edits don't affect the generated hash


# --- edit detection -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("mood: happy", "mood: tired"),
        ("  - pasta", "  - pasta\n  - salad"),
        ("# Saturday, October 10, 2026 · First tooth", "# My own title"),
        ("then oatmeal with blueberries.", "then oatmeal with strawberries."),
    ],
)
def test_edits_to_facts_title_or_journal_are_detected(
    sample_day_markdown: str, old: str, new: str
) -> None:
    assert old in sample_day_markdown
    day = D.parse(sample_day_markdown.replace(old, new, 1))
    assert day.is_user_edited()


def test_edits_to_notes_or_provenance_are_not_user_edits(sample_day_markdown: str) -> None:
    md = sample_day_markdown.replace("Remember to put", "Do not forget to put")
    md = md.replace("prompt_version: journal-v1", "prompt_version: other")
    assert not D.parse(md).is_user_edited()


# --- merge_capture --------------------------------------------------------------------------


def test_merge_capture_creates_day_and_updates_front_matter() -> None:
    c = capture(
        "r1",
        at(21, 30),
        kind="recording",
        text="hi",
        audio="2026-10-10-2130.m4a",
        photos=["photo-01.jpg"],
    )
    day = D.merge_capture(None, c, DAY)
    assert day.date == DAY
    assert day.captures == [c]
    assert day.meta.audio == ["2026-10-10-2130.m4a"]
    assert day.meta.photos == ["photo-01.jpg"]
    assert day.meta.generated_hash is None


def test_merge_capture_sorts_is_idempotent_and_pure() -> None:
    late = capture("late", at(21))
    early = capture("early", at(8))
    day1 = D.merge_capture(None, late, DAY)
    day2 = D.merge_capture(day1, early, DAY)
    assert [c.id for c in day2.captures] == ["early", "late"]
    assert [c.id for c in day1.captures] == ["late"]
    assert D.merge_capture(day2, early, DAY) == day2


def test_merge_capture_never_touches_generated_or_notes(sample_day_markdown: str) -> None:
    day = D.parse(sample_day_markdown)
    new = D.merge_capture(
        day,
        capture(
            "extra",
            at(23),
            kind="recording",
            text="one more",
            audio="2026-10-10-2300.m4a",
            photos=["photo-03.jpg"],
        ),
        DAY,
    )
    assert (new.title, new.journal, new.notes) == (day.title, day.journal, day.notes)
    assert new.meta.facts() == day.meta.facts()
    assert new.meta.generated_hash == day.meta.generated_hash
    assert not new.is_user_edited()
    assert new.meta.audio == ["2026-10-10-2130.m4a", "2026-10-10-2300.m4a"]
    assert new.meta.photos[-1] == "photo-03.jpg"
    assert D.parse(D.render(new)) == new


def test_merge_capture_wrong_day_raises(sample_day_markdown: str) -> None:
    with pytest.raises(ValueError):
        D.merge_capture(
            D.parse(sample_day_markdown), capture("x", at(9, day=12)), dt.date(2026, 10, 12)
        )


# --- generation -----------------------------------------------------------------------------


def _facts(**kw) -> D.DayFacts:
    return D.DayFacts(**kw)


def test_apply_generation_sets_content_and_hash() -> None:
    day = D.merge_capture(None, capture("a", at(9), text="eggs"), DAY)
    gen = D.apply_generation(
        day,
        facts=_facts(meals=[D.Meal(type="breakfast", items=["eggs"])]),
        journal="## Summary\n\nEggs.",
        title="Eggs day",
        prompt_version="v1",
        models_used={"extract_facts": "m"},
        generated_at=at(9, 5),
    )
    assert gen.title == "Eggs day"
    assert gen.meta.meals[0].items == ["eggs"]
    assert gen.meta.prompt_version == "v1"
    assert gen.meta.generated_hash == gen.compute_generated_hash()
    assert not gen.is_user_edited()
    regen = D.apply_generation(gen, facts=_facts(mood="ok"), journal="New.")
    assert regen.title == "Eggs day"
    assert regen.meta.meals == []
    assert regen.meta.prompt_version == "v1"


def test_apply_generation_refuses_user_edits(sample_day_markdown: str) -> None:
    day = D.parse(sample_day_markdown.replace("mood: happy", "mood: great"))
    with pytest.raises(D.UserEditsDetected):
        D.apply_generation(day, facts=_facts(), journal="x")
    forced = D.apply_generation(day, facts=_facts(), journal="x", force=True)
    assert forced.notes == day.notes
    assert not forced.is_user_edited()


def test_additive_merge_on_edited_day_keeps_edits(sample_day_markdown: str) -> None:
    day = D.parse(sample_day_markdown.replace("mood: happy", "mood: great"))
    assert day.is_user_edited()
    merged = D.merge_generation_additive(
        day,
        facts=_facts(
            mood="sad",
            people=["maya", "Sam"],
            meals=[
                D.Meal(type="Dinner", items=["pasta", "salad"]),
                D.Meal(type="snack", items=["apple"]),
            ],
            activities=[D.Activity(kind="run", minutes=10), D.Activity(kind="yoga", minutes=20)],
            highlights=["Night walk"],
        ),
        journal_addendum="A late walk.",
        addendum_heading="Added at 23:00",
        prompt_version="v2",
        generated_at=at(23),
    )
    assert merged.meta.mood == "great"
    assert merged.meta.people == ["Maya", "Leo", "Sam"]
    dinner = next(m for m in merged.meta.meals if m.type == "dinner")
    assert dinner.items == ["pasta", "salad"]
    assert merged.meta.meals[-1] == D.Meal(type="snack", items=["apple"])
    assert [a.kind for a in merged.meta.activities] == ["run", "reading", "yoga"]
    assert merged.meta.activities[0].minutes == 40
    assert merged.journal.startswith(day.journal)
    assert merged.journal.endswith("### Added at 23:00\n\nA late walk.")
    assert merged.notes == day.notes
    assert merged.meta.prompt_version == "v2"
    assert merged.meta.generated_hash == day.meta.generated_hash
    assert merged.is_user_edited()


def test_additive_merge_on_clean_day_refreshes_hash(sample_day_markdown: str) -> None:
    day = D.parse(sample_day_markdown)
    merged = D.merge_generation_additive(day, facts=_facts(people=["Sam"]))
    assert merged.meta.people[-1] == "Sam"
    assert not merged.is_user_edited()
