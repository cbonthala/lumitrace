from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from lumitrace.frames import dayfile as D

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
    assert D.parse_day_file_path("Lumitrace/2026/10/2026-10-10/2026-10-10.md") is None
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
    assert day.meta.lumitrace_format == D.FORMAT_VERSION
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
    assert (day.facts.mood, day.facts.mood_score, day.facts.city) == ("happy", 4, "Austin")
    assert day.facts.people == ["Maya", "Leo"]
    assert day.facts.places == ["the river trail", "the taco truck", "home"]
    assert day.facts.meals[0] == D.Meal(type="breakfast", items=["oatmeal", "blueberries"])
    assert day.facts.activities[1] == D.Activity(kind="reading", minutes=None)
    assert day.meta.model_extra == {}
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


@pytest.mark.parametrize("old_name", ["lifelog", "bookshelf", "lumen"])
def test_parses_files_written_before_the_rename(sample_day_markdown: str, old_name: str) -> None:
    legacy = sample_day_markdown.replace("<!-- lumitrace:", f"<!-- {old_name}:").replace(
        "lumitrace_format:", f"{old_name}_format:"
    )
    assert "lumitrace" not in legacy
    day = D.parse(legacy)
    assert day == D.parse(sample_day_markdown)
    assert day.meta.model_extra == {}
    assert D.render(day) == sample_day_markdown


def test_reads_format_1_files_and_writes_format_2(
    sample_day_v1_markdown: str, sample_day_markdown: str
) -> None:
    old = D.parse(sample_day_v1_markdown)
    new = D.parse(sample_day_markdown)
    assert old.facts == new.facts.model_copy(update={"places": [], "family": []})
    assert old.facts.highlights == ["Leo lost his first tooth", "Finished a book"]
    assert old.meta.model_extra == {}
    assert old.meta.lumitrace_format == D.FORMAT_VERSION
    assert not old.is_user_edited()  # matched the format 1 hash, so it was re-stamped
    rendered = D.render(old)
    front = rendered.split("\n---\n", 1)[0]
    assert "mood" not in front and "meals" not in front
    assert "lumitrace_format: 2" in front
    assert "- **Mood:** happy (4/5)" in rendered
    assert D.parse(rendered) == old


def test_facts_section_tolerates_hand_edits() -> None:
    md = (
        "---\ndate: 2026-10-10\n---\n\n# Title\n\n## At a glance\n\n"
        "<!-- lumitrace:facts:start -->\n"
        "Mood: great\n"
        "* **City**: Austin\n"
        "- Sleep: 8 hours\n\n"
        "## Meals\n- Breakfast: eggs,toast\n- a muffin\n\n"
        "#### places visited\nthe library\n\n"
        "### Activities\n- swim (25 minutes)\n- yoga (1 hour)\n\n"
        "### Dreams\n- flying over the lake\n"
        "<!-- lumitrace:facts:end -->\n"
    )
    day = D.parse(md)
    facts = day.facts
    assert (facts.mood, facts.mood_score, facts.city) == ("great", None, "Austin")
    assert facts.meals == [
        D.Meal(type="breakfast", items=["eggs", "toast"]),
        D.Meal(type="snacks", items=["a muffin"]),
    ]
    assert facts.places == ["the library"]
    assert facts.activities == [
        D.Activity(kind="swim", minutes=25),
        D.Activity(kind="yoga (1 hour)"),
    ]
    for stray in ["- Sleep: 8 hours", "### Dreams", "- flying over the lake"]:
        assert stray in day.notes
    assert D.parse(D.render(day)) == day


def test_family_blocks_tolerate_hand_edits() -> None:
    md = (
        "---\ndate: 2026-10-10\n---\n\n# Title\n\n## At a glance\n\n"
        "<!-- lumitrace:facts:start -->\n"
        "### Family events\n"
        "- typed before any name\n\n"
        "#### Leo\n"
        "- Food: pizza, apple juice\n"
        "* **Went to**: school\n"
        "- Did: soccer (60 minutes); drawing\n"
        "- Milestones: lost a tooth; first goal\n"
        "- Health: a cold\n"
        "- Work: spelling test\n"
        "- Shoe size: 12\n\n"
        "### Sam\n"
        "Mood: grumpy\n\n"
        "#### Nobody\n\n"
        "### Highlights\n- a good day\n"
        "<!-- lumitrace:facts:end -->\n"
    )
    day = D.parse(md)
    leo, sam, nobody = day.facts.family
    assert leo == D.FamilyMember(
        name="Leo",
        food=["pizza", "apple juice"],
        places=["school"],
        activities=[D.Activity(kind="soccer", minutes=60), D.Activity(kind="drawing")],
        moments=["lost a tooth", "first goal"],
        health=["a cold"],
        school=["spelling test"],
    )
    assert sam == D.FamilyMember(name="Sam", mood="grumpy")
    assert nobody == D.FamilyMember(name="Nobody")
    assert day.facts.highlights == ["a good day"]
    assert "- typed before any name" in day.notes and "- Shoe size: 12" in day.notes
    rendered = D.render(day)
    assert "#### Leo\n\n- **Mood:** none\n- **Ate:** pizza, apple juice\n" in rendered
    assert "- **Did:** soccer (60 min); drawing\n- **Moments:** lost a tooth; first goal\n" in (
        rendered
    )
    assert "#### Nobody\n\n- **Mood:** none\n- **Ate:** none\n" in rendered
    assert D.parse(rendered) == day


def test_family_items_never_contain_their_separator() -> None:
    member = D.FamilyMember(
        name=" Leo ",
        food=["pizza, juice"],
        moments=["tooth; goal"],
        activities=[D.Activity(kind="swim; dive")],
    )
    assert member.name == "Leo"
    assert member.food == ["pizza", "juice"]
    assert member.moments == ["tooth", "goal"]
    assert member.activities[0].kind == "swim, dive"
    facts = D.DayFacts(
        family=[member, D.FamilyMember(name="Empty"), D.FamilyMember(name="", food=["x"])]
    )
    assert [m.name for m in facts.family] == ["Leo", "Empty"]
    assert D.parse_facts_section(D.render_facts_section(facts)) == (facts, "")


def test_edited_format_1_file_stays_edited(sample_day_v1_markdown: str) -> None:
    day = D.parse(sample_day_v1_markdown.replace("mood: happy", "mood: great"))
    assert day.facts.mood == "great"
    assert day.is_user_edited()
    assert day.meta.generated_hash == "f95b9b427b956b91"


def test_fact_values_are_normalised_so_render_and_parse_agree() -> None:
    facts = D.DayFacts(
        mood="  tired\nbut fine ",
        city="",
        people=["Maya ", "", "  "],
        meals=[
            D.Meal(type="Supper", items=["soup"]),
            D.Meal(type="Breakfast:", items=["eggs, toast", " ", "None"]),
            D.Meal(type="lunch", items=[]),
            D.Meal(type="dessert", items=["cake"]),
            D.Meal(type="drink", items=["tea"]),
            D.Meal(type="breakfast", items=["Toast", "coffee"]),
        ],
        activities=[D.Activity(kind="  "), D.Activity(kind="none"), D.Activity(kind="long\nwalk")],
        highlights=["two\n\nlines", "none"],
        weather="None",
    )
    assert facts.mood == "tired but fine"
    assert (facts.city, facts.weather) == (None, None)
    assert facts.people == ["Maya"]
    assert facts.meals == [
        D.Meal(type="breakfast", items=["eggs", "toast", "coffee"]),
        D.Meal(type="dinner", items=["soup"]),
        D.Meal(type="snacks", items=["cake"]),
        D.Meal(type="drinks", items=["tea"]),
    ]
    assert facts.activities == [D.Activity(kind="long walk")]
    assert facts.highlights == ["two lines"]
    section = D.render_facts_section(facts)
    assert D.parse_facts_section(section) == (facts, "")


def test_every_day_file_has_the_same_fact_lines() -> None:
    assert D.render_facts_section(D.DayFacts(family=[D.FamilyMember(name="Leo")])) == (
        "- **Mood:** none\n- **City:** none\n- **Weather:** none\n\n"
        "### Food\n\n"
        "- **Breakfast:** none\n- **Lunch:** none\n- **Dinner:** none\n"
        "- **Snacks:** none\n- **Drinks:** none\n\n"
        "### Places\n\n- none\n\n"
        "### People\n\n- none\n\n"
        "### Activities\n\n- none\n\n"
        "### Family\n\n#### Leo\n\n"
        "- **Mood:** none\n- **Ate:** none\n- **Went to:** none\n- **Did:** none\n"
        "- **Moments:** none\n- **Health:** none\n- **School/work:** none\n\n"
        "### Highlights\n\n- none"
    )
    assert D.render_facts_section(D.DayFacts()).count("- none") == 5
    assert D.parse_facts_section(D.render_facts_section(D.DayFacts())) == (D.DayFacts(), "")
    assert D.render_facts_section(D.DayFacts(), include_empty=False) == ""
    compact = D.render_facts_section(
        D.DayFacts(mood="ok", family=[D.FamilyMember(name="Leo")]), include_empty=False
    )
    assert compact == "- **Mood:** ok"


def test_generated_journal_gets_the_fixed_headings() -> None:
    raw = (
        "A quiet day.\n\n"
        "## Evening\n\nPasta at home.\n\n"
        "## Morning:\n\nA run.\n\n"
        "### Dinner with friends\n\nTacos.\n\n"
        "```\n## not a heading\n```\n\n"
        "## Night\n\nStars.\n\n"
        "## Reflections\n\nNeed more sleep."
    )
    journal = D.normalize_journal(raw)
    assert journal == (
        "## Summary\n\nA quiet day.\n\n"
        "## Morning\n\nA run.\n\n**Dinner with friends**\n\nTacos.\n\n"
        "```\n## not a heading\n```\n\n"
        "## Evening\n\nPasta at home.\n\nStars.\n\n"
        "## Thoughts\n\nNeed more sleep."
    )
    assert D.normalize_journal(journal) == journal
    day = D.apply_generation(D.DayFile.new(DAY), facts=D.DayFacts(), journal=raw)
    assert day.journal == journal


def test_fact_keys_in_the_front_matter_of_a_format_2_file_are_kept(
    sample_day_markdown: str,
) -> None:
    md = sample_day_markdown.replace("lumitrace_format: 2", "lumitrace_format: 2\nmood: sleepy")
    day = D.parse(md)
    assert day.facts.mood == "happy"
    assert day.meta.model_extra == {"mood": "sleepy"}
    assert "mood: sleepy" in D.render(day)


def test_roundtrip_model_equality_with_tricky_content() -> None:
    day = D.DayFile(
        meta=D.FrontMatter(
            date=DAY,
            models_used={"stt": "fake"},
            generated_at=at(22),
            tags=["journal", "family"],
        ),
        facts=D.DayFacts(
            mood="yes",
            people=["O'Brien", "Zoë"],
            places=["Café **Nord**", "# not a heading"],
            highlights=["null", "a: b", "- dash"],
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
        md.index(D.FACTS_HEADING),
        md.index(D.FACTS_START),
        md.index("### Food"),
        md.index("### Places"),
        md.index("### People"),
        md.index("### Activities"),
        md.index("### Family"),
        md.index("### Highlights"),
        md.index(D.FACTS_END),
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
        ("- **Mood:** happy (4/5)", "- **Mood:** tired (4/5)"),
        ("- **Dinner:** pasta", "- **Dinner:** pasta, salad"),
        ("- the taco truck\n", ""),
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
    assert new.facts == day.facts
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
    assert gen.facts.meals[0].items == ["eggs"]
    assert gen.meta.prompt_version == "v1"
    assert gen.meta.generated_hash == gen.compute_generated_hash()
    assert not gen.is_user_edited()
    regen = D.apply_generation(gen, facts=_facts(mood="ok"), journal="New.")
    assert regen.title == "Eggs day"
    assert regen.facts.meals == []
    assert regen.meta.prompt_version == "v1"


def test_apply_generation_refuses_user_edits(sample_day_markdown: str) -> None:
    day = D.parse(sample_day_markdown.replace("**Mood:** happy", "**Mood:** great"))
    with pytest.raises(D.UserEditsDetected):
        D.apply_generation(day, facts=_facts(), journal="x")
    forced = D.apply_generation(day, facts=_facts(), journal="x", force=True)
    assert forced.notes == day.notes
    assert not forced.is_user_edited()


def test_additive_merge_on_edited_day_keeps_edits(sample_day_markdown: str) -> None:
    day = D.parse(sample_day_markdown.replace("**Mood:** happy", "**Mood:** great"))
    assert day.is_user_edited()
    merged = D.merge_generation_additive(
        day,
        facts=_facts(
            mood="sad",
            people=["maya", "Sam"],
            places=["Home", "the night market"],
            family=[
                D.FamilyMember(name="leo", mood="sleepy", food=["Pasta", "ice cream"]),
                D.FamilyMember(name="Maya", health=["headache"]),
            ],
            meals=[
                D.Meal(type="Dinner", items=["pasta", "salad"]),
                D.Meal(type="snack", items=["apple"]),
            ],
            activities=[D.Activity(kind="run", minutes=10), D.Activity(kind="yoga", minutes=20)],
            highlights=["Night walk"],
        ),
        journal_addendum="A late walk.",
        addendum_label="23:00 · Quick Note",
        prompt_version="v2",
        generated_at=at(23),
    )
    assert merged.facts.mood == "great"
    assert merged.facts.people == ["Maya", "Leo", "Sam"]
    assert merged.facts.places == ["the river trail", "the taco truck", "home", "the night market"]
    leo, maya = merged.facts.family
    assert (leo.name, leo.mood, leo.food) == ("Leo", "proud", ["pasta", "ice cream"])
    assert leo.moments == ["lost his first tooth"]
    assert (maya.food, maya.health) == (["fish tacos"], ["headache"])
    dinner = next(m for m in merged.facts.meals if m.type == "dinner")
    assert dinner.items == ["pasta", "salad"]
    assert [m.type for m in merged.facts.meals] == list(D.MEAL_TYPES)
    assert merged.facts.meals[3] == D.Meal(type="snacks", items=["apple"])
    assert [a.kind for a in merged.facts.activities] == ["run", "reading", "yoga"]
    assert merged.facts.activities[0].minutes == 40
    assert merged.journal.startswith(day.journal)
    assert merged.journal.endswith("## Later\n\n**23:00 · Quick Note**\n\nA late walk.")
    assert merged.notes == day.notes
    assert merged.meta.prompt_version == "v2"
    assert merged.meta.generated_hash == day.meta.generated_hash
    assert merged.is_user_edited()
    again = D.merge_generation_additive(
        merged, facts=D.DayFacts(), journal_addendum="Stars.", addendum_label="23:30 · Quick Note"
    )
    assert again.journal.count("## Later") == 1
    assert again.journal.endswith("A late walk.\n\n**23:30 · Quick Note**\n\nStars.")


def test_additive_merge_on_clean_day_refreshes_hash(sample_day_markdown: str) -> None:
    day = D.parse(sample_day_markdown)
    merged = D.merge_generation_additive(day, facts=_facts(people=["Sam"]))
    assert merged.facts.people[-1] == "Sam"
    assert not merged.is_user_edited()
