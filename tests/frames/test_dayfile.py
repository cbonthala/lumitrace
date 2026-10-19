from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from lumitrace.frames import daycontent as C
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
    assert D.generated_facts_path(DAY) == "_system/generated-facts/2026/10/2026-10-10.json"
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
    assert day.facts.weather == "sunny, 24°C"
    assert day.facts.people == ["Ravi, neighbour - at the river trail (Sam)"]
    assert day.facts.places == [
        "the river trail (Sam)",
        "the taco truck (Sam, Maya)",
        "home (Sam, Maya, Leo)",
    ]
    assert day.facts.remember == "Leo lost his first tooth and was very proud"
    assert day.facts.memories == ["Leo's first tooth came out at bedtime"]
    sam, maya, leo = day.facts.family
    assert sam.meals[0] == D.Meal(type="breakfast", items=["oatmeal", "blueberries"])
    assert (sam.feelings, leo.feelings, leo.moments) == (
        ["happy"],
        ["proud"],
        ["lost his first tooth"],
    )
    assert maya.meals == [D.Meal(type="lunch", items=["fish tacos"])]
    assert day.facts.activities[1] == D.Activity(kind="reading (Sam)", minutes=None)
    assert day.meta.model_extra == {}
    assert day.meta.audio == ["2026-10-10-2130.m4a"]
    assert day.meta.photos == ["photo-01.jpg", "photo-02.jpg"]
    assert day.meta.models_used["fill_day"] == "gemini/gemini-3.8-flash"
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
    rendered = D.render(day)
    assert "## At a glance" in rendered
    assert "English translation" not in rendered
    rewritten = D.parse(rendered)
    assert rewritten.facts == day.facts
    assert rewritten.journal == day.journal
    assert rewritten.notes == day.notes
    assert rewritten.title == day.title
    assert [c.text for c in rewritten.captures] == [c.text for c in day.captures]
    assert not rewritten.is_user_edited()


# --- Format 6 parse / render and owner safety ------------------------------------------------


def _format6_content() -> C.DayContent:
    return C.DayContent(
        timeline=C.Timeline(
            highlight="Park day",
            context=C.DayContext(
                weather="sunny",
                places_visited=[C.PlaceContext(name="River Park", family_members=["Sam"])],
            ),
            morning=["Walked", "Kept this detail"],
            remember="Sam found a smooth stone",
        ),
        family=[
            C.FamilyTracker(
                name="Sam",
                food=C.FoodTracker(breakfast=C.Meal(status="consumed", items=["eggs", "toast"])),
                health_fitness=C.HealthFitness(sleep=["7 hours"]),
                daily_routine=C.DailyRoutine(responsibilities_activities=["chores"]),
            )
        ],
        tags=["family", "park"],
    )


def test_format5_is_preserved_until_content_regeneration() -> None:
    legacy = D.apply_generation(
        D.DayFile.new(DAY),
        facts=D.DayFacts(
            highlights=["Legacy highlight"],
            family=[
                D.FamilyMember(
                    name="Sam",
                    meals=[D.Meal(type="breakfast", items=["eggs"])],
                )
            ],
        ),
        journal="## Summary\n\nA readable legacy journal.",
        generated_at=at(20),
    )

    legacy_markdown = D.render(legacy)
    assert f"{D.FORMAT_KEY}: {D.LEGACY_FORMAT_VERSION}" in legacy_markdown
    assert D.FACTS_START in legacy_markdown
    assert D.JOURNAL_START in legacy_markdown
    assert D.CONTENT_START not in legacy_markdown

    parsed = D.parse(legacy_markdown)
    assert parsed.content is None
    assert parsed.facts == legacy.facts
    assert parsed.journal == legacy.journal
    assert D.render(parsed) == legacy_markdown
    assert not parsed.is_user_edited()

    regenerated = D.apply_content_generation(
        parsed,
        content=_format6_content(),
        generated_at=at(21),
    )
    regenerated_markdown = D.render(regenerated)
    assert f"{D.FORMAT_KEY}: {D.FORMAT_VERSION}" in regenerated_markdown
    assert D.CONTENT_START in regenerated_markdown
    assert D.FACTS_START not in regenerated_markdown
    assert D.JOURNAL_START not in regenerated_markdown


def test_format6_marker_order_hash_roundtrip_and_legacy_projection() -> None:
    content = _format6_content()
    day = D.DayFile(
        meta=D.FrontMatter(date=DAY),
        notes="Owner note.",
        captures=[capture("n1", at(9), text="Raw note")],
    )
    generated = D.apply_content_generation(
        day,
        content=content,
        title="A generated title",
        generated_at=at(20),
    )

    markdown = D.render(generated)
    order = [
        markdown.index("\n# A generated title"),
        markdown.index(D.CONTENT_START),
        markdown.index("## Day timeline"),
        markdown.index("## Family trackers"),
        markdown.index("## Tags"),
        markdown.index(D.CONTENT_END),
        markdown.index(D.NOTES_HEADING),
        markdown.index(D.NOTES_START),
        markdown.index(D.NOTES_END),
        markdown.index(D.TRANSCRIPT_HEADING),
        markdown.index(D.TRANSCRIPT_START),
        markdown.index(D.TRANSCRIPT_END),
    ]
    assert order == sorted(order)
    assert D.FACTS_START not in markdown
    assert D.JOURNAL_START not in markdown
    assert len(generated.meta.generated_hash or "") == 16

    parsed = D.parse(markdown)
    assert parsed.content == content
    assert parsed.facts == D.DayFacts.model_validate(C.to_legacy_facts(content))
    assert parsed.meta.generated_hash == parsed.compute_generated_hash()
    assert not parsed.is_user_edited()
    assert D.render(parsed) == markdown

    notes_edit = D.parse(markdown.replace("Owner note.", "Owner note, edited."))
    assert not notes_edit.is_user_edited()
    cell_edit = D.parse(markdown.replace("eggs<br>toast", "oatmeal", 1))
    assert cell_edit.is_user_edited()


def test_format6_three_way_merge_keeps_owner_cell_list_and_timeline_edits() -> None:
    base = _format6_content()
    generated = D.apply_content_generation(
        D.DayFile.new(DAY),
        content=base,
        generated_at=at(20),
    )
    original_hash = generated.meta.generated_hash
    markdown = D.render(generated)
    edited_markdown = (
        markdown.replace("- **Weather:** sunny", "- **Weather:** owner weather")
        .replace(
            "### Morning\n\n- Walked\n- Kept this detail",
            "### Morning\n\n- Owner rewrote this detail",
        )
        .replace("### Evening\n\n- —", "### Evening\n\n- Walked")
        .replace("eggs<br>toast", "eggs<br>owner fruit", 1)
        .replace(
            "| Sam | — | chores | — | — |",
            "| Sam | — | owner chores | — | — |",
            1,
        )
        .replace("#family #park", "#family #owner-tag")
    )
    current = D.parse(edited_markdown)
    assert current.is_user_edited()

    incoming = C.DayContent(
        timeline=C.Timeline(
            highlight="River day",
            context=C.DayContext(weather="rainy"),
            morning=["Walked", "New model event"],
            remember="A new model memory",
        ),
        family=[
            C.FamilyTracker(
                name="Sam",
                food=C.FoodTracker(
                    breakfast=C.Meal(
                        status="consumed",
                        items=["eggs", "toast", "berries"],
                    )
                ),
                health_fitness=C.HealthFitness(sleep=["8 hours"]),
                daily_routine=C.DailyRoutine(
                    responsibilities_activities=["chores", "new model task"]
                ),
            ),
            C.FamilyTracker(name="Bo"),
        ],
        tags=["family", "park", "river"],
    )

    merged = D.merge_content_generation_three_way(
        current,
        base_content=base,
        content=incoming,
        generated_at=at(22),
    )

    assert merged.content is not None
    assert merged.content.timeline.highlight == "River day"
    assert merged.content.timeline.context.weather == "owner weather"
    assert merged.content.timeline.morning == [
        "New model event",
        "Owner rewrote this detail",
    ]
    assert merged.content.timeline.evening == ["Walked"]
    assert merged.content.family[0].food.breakfast.items == [
        "eggs",
        "berries",
        "owner fruit",
    ]
    assert merged.content.family[0].health_fitness.sleep == ["8 hours"]
    assert merged.content.family[0].daily_routine.responsibilities_activities == [
        "new model task",
        "owner chores",
    ]
    assert [member.name for member in merged.content.family] == ["Sam", "Bo"]
    assert merged.content.tags == ["family", "river", "owner-tag"]
    assert merged.meta.generated_hash == original_hash
    assert merged.is_user_edited()
    assert D.parse(D.render(merged)).content == merged.content


def test_clean_format6_three_way_merge_refreshes_generated_hash() -> None:
    base = _format6_content()
    generated = D.apply_content_generation(D.DayFile.new(DAY), content=base)
    incoming = base.model_copy(deep=True)
    incoming.timeline.highlight = "Updated highlight"

    merged = D.merge_content_generation_three_way(
        generated,
        base_content=base,
        content=incoming,
    )

    assert merged.meta.generated_hash == merged.compute_generated_hash()
    assert merged.meta.generated_hash != generated.meta.generated_hash
    assert not merged.is_user_edited()


@pytest.mark.parametrize("old_name", ["lifelog", "bookshelf", "lumen"])
def test_parses_files_written_before_the_rename(sample_day_markdown: str, old_name: str) -> None:
    legacy = sample_day_markdown.replace("<!-- lumitrace:", f"<!-- {old_name}:").replace(
        "lumitrace_format:", f"{old_name}_format:"
    )
    assert "lumitrace" not in legacy
    day = D.parse(legacy)
    assert day == D.parse(sample_day_markdown)
    assert day.meta.model_extra == {}
    rendered = D.render(day)
    assert f"{old_name}:" not in rendered
    assert "## At a glance" in rendered


def test_reads_format_1_files_and_preserves_the_legacy_layout(
    sample_day_v1_markdown: str,
) -> None:
    old = D.parse(sample_day_v1_markdown)
    assert old.facts.highlights == ["Leo lost his first tooth", "Finished a book"]
    assert (old.facts.mood, old.facts.mood_score, old.facts.city) == ("happy", 4, "Austin")
    assert old.facts.meals[0] == D.Meal(type="breakfast", items=["oatmeal", "blueberries"])
    assert old.meta.model_extra == {}
    assert old.meta.lumitrace_format == D.LEGACY_FORMAT_VERSION
    assert not old.is_user_edited()  # matched the format 1 hash, so it was re-stamped
    rendered = D.render(old)
    front = rendered.split("\n---\n", 1)[0]
    assert "mood" not in front and "meals" not in front
    assert f"lumitrace_format: {D.LEGACY_FORMAT_VERSION}" in front
    assert "## At a glance" in rendered
    rewritten = D.parse(rendered)
    assert rewritten.facts == old.facts
    assert (rewritten.title, rewritten.journal) == (old.title, old.journal)
    assert not rewritten.is_user_edited()


def test_reads_format_2_files_and_preserves_the_legacy_layout(
    sample_day_v2_markdown: str,
) -> None:
    day = D.parse(sample_day_v2_markdown)
    facts = day.facts
    assert (facts.mood, facts.mood_score, facts.city) == ("happy", 4, "Austin")
    assert facts.people == ["Maya", "Leo"]
    assert facts.places == ["the river trail", "the taco truck", "home", "the taco truck (Maya)"]
    assert facts.meals[0] == D.Meal(type="breakfast", items=["oatmeal", "blueberries"])
    leo = next(m for m in facts.family if m.name == "Leo")
    assert (leo.feelings, leo.moments) == (["proud"], ["lost his first tooth"])
    assert leo.meals == [D.Meal(type="snacks", items=["pasta"])]
    assert day.meta.lumitrace_format == D.LEGACY_FORMAT_VERSION
    assert day.is_user_edited()  # the format 2 hash does not match, so it is never overwritten
    rendered = D.render(day)
    assert "## At a glance" in rendered
    rewritten = D.parse(rendered)
    assert rewritten.facts == day.facts
    assert rewritten.journal == day.journal
    assert rewritten.is_user_edited()


def test_format_2_family_lines_become_places_and_things_we_did() -> None:
    md = (
        "---\ndate: 2026-10-10\nlumitrace_format: 2\n---\n\n# T\n\n## At a glance\n\n"
        "<!-- lumitrace:facts:start -->\n### Family\n\n#### Leo\n\n"
        "- **Mood:** proud\n- **Ate:** pizza, apple juice\n- **Went to:** school\n"
        "- **Did:** soccer (60 min); drawing\n- **School/work:** spelling test\n"
        "<!-- lumitrace:facts:end -->\n"
    )
    facts = D.parse(md).facts
    assert facts.places == ["school (Leo)"]
    assert facts.activities == [
        D.Activity(kind="soccer (Leo)", minutes=60),
        D.Activity(kind="drawing (Leo)"),
        D.Activity(kind="school/work: spelling test (Leo)"),
    ]
    assert facts.family == [
        D.FamilyMember(
            name="Leo",
            feelings=["proud"],
            meals=[D.Meal(type="snacks", items=["pizza", "apple juice"])],
        )
    ]


def test_format_2_day_meals_go_to_the_person_who_ate_them() -> None:
    facts = D.DayFacts.model_validate(
        {
            "meals": [
                {"type": "breakfast", "items": ["eggs"]},
                {"type": "dinner", "items": ["soup"]},
            ],
            "family": [
                {"name": "Sam", "food": ["eggs", "soup", "tea"]},
                {"name": "Leo", "food": ["milk"]},
            ],
        }
    )
    assert facts.meals == []
    sam, leo = facts.family
    assert sam.meals == [
        D.Meal(type="breakfast", items=["eggs"]),
        D.Meal(type="dinner", items=["soup"]),
        D.Meal(type="snacks", items=["tea"]),
    ]
    assert leo.meals == [D.Meal(type="snacks", items=["milk"])]
    unclaimed = D.DayFacts.model_validate({"meals": [{"type": "lunch", "items": ["rice"]}]})
    assert unclaimed.meals == [D.Meal(type="lunch", items=["rice"])]
    assert "#### Everyone\n\n- **Lunch:** rice" in D.render_facts_section(unclaimed)


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
    rewritten = D.parse(D.render(day))
    assert rewritten.facts == day.facts
    for stray in ["- Sleep: 8 hours", "### Dreams", "- flying over the lake"]:
        assert stray in rewritten.notes


def test_person_sections_tolerate_hand_edits() -> None:
    md = (
        f"---\ndate: 2026-10-10\n{D.FORMAT_KEY}: {D.FORMAT_VERSION}\n---\n\n# Title\n\n"
        "## At a glance\n\n<!-- lumitrace:facts:start -->\n"
        "Mood: grumpy\n\n"
        "### Food\n"
        "- eggs\n\n"
        "#### Leo\n"
        "- Morning: pancakes,juice\n"
        "* **Snacks / drinks / other**: apple\n"
        "\n"
        "#### Sam\n- not mentioned\n\n"
        "### Feelings\n#### Leo\n- proud\n- a bit tired\n\n"
        "### memories\n- sang in the car\n#### Leo\n- lost a tooth; first goal\n\n"
        "### Health and fitness\n- a stray line\n\n"
        "### Highlight\n- a good day\n- Remember: the tooth\n\n"
        "### Weather\n- not looked up (Austin)\n\n"
        "### Dreams\n- flying\n"
        "<!-- lumitrace:facts:end -->\n"
    )
    day = D.parse(md)
    facts = day.facts
    assert facts.mood == "grumpy"
    assert facts.meals == [D.Meal(type="snacks", items=["eggs"])]
    leo, sam = facts.family
    assert leo == D.FamilyMember(
        name="Leo",
        meals=[
            D.Meal(type="breakfast", items=["pancakes", "juice"]),
            D.Meal(type="snacks", items=["apple"]),
        ],
        feelings=["proud", "a bit tired"],
        moments=["lost a tooth", "first goal"],
    )
    assert sam == D.FamilyMember(name="Sam")
    assert facts.memories == ["sang in the car"]
    assert facts.highlights == ["a good day"]
    assert facts.remember == "the tooth"
    assert facts.weather is None
    for stray in ["- a stray line", "### Dreams", "- flying"]:
        assert stray in day.notes
    rewritten = D.parse(D.render(day))
    assert rewritten.facts == day.facts
    for stray in ["- a stray line", "### Dreams", "- flying"]:
        assert stray in rewritten.notes


def test_person_items_never_contain_their_separator() -> None:
    member = D.FamilyMember(
        name=" Leo ",
        meals=[D.Meal(type="lunch", items=["pizza, juice"])],
        moments=["tooth; goal"],
        feelings=["happy; tired"],
    )
    assert member.name == "Leo"
    assert member.meals == [D.Meal(type="lunch", items=["pizza", "juice"])]
    assert member.moments == ["tooth", "goal"]
    assert member.feelings == ["happy", "tired"]
    facts = D.DayFacts(
        family=[member, D.FamilyMember(name="Empty"), D.FamilyMember(name="", health=["x"])]
    )
    assert [m.name for m in facts.family] == ["Leo", "Empty"]
    assert D.parse_facts_section(D.render_facts_section(facts)) == (facts, "")


def test_meal_items_keep_commas_inside_parentheses() -> None:
    meal = D.Meal(type="breakfast", items=["oatmeal (Maya, Leo), coffee (Sam)"])
    assert meal.items == ["oatmeal (Maya, Leo)", "coffee (Sam)"]
    facts = D.DayFacts(
        meals=[meal],
        family=[
            D.FamilyMember(name="Maya"),
            D.FamilyMember(name="Leo"),
            D.FamilyMember(name="Sam"),
        ],
    )
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
        remember=" the  tooth\n",
        activities=[D.Activity(kind="  "), D.Activity(kind="none"), D.Activity(kind="long\nwalk")],
        highlights=["two\n\nlines", "Not mentioned"],
        weather="Not looked up (Austin)",
    )
    assert facts.mood == "tired but fine"
    assert (facts.city, facts.weather) == (None, None)
    assert facts.people == ["Maya"]
    assert facts.meals == [
        D.Meal(type="breakfast", items=["eggs", "toast", "coffee"]),
        D.Meal(type="dinner", items=["soup"]),
        D.Meal(type="snacks", items=["cake", "tea"]),
    ]
    assert facts.remember == "the tooth"
    assert facts.activities == [D.Activity(kind="long walk")]
    assert facts.highlights == ["two lines"]
    section = D.render_facts_section(facts)
    assert D.parse_facts_section(section) == (facts, "")


def test_every_day_file_has_the_same_fact_lines() -> None:
    n = D.NONE_TEXT
    assert D.render_facts_section(D.DayFacts(family=[D.FamilyMember(name="Leo")])) == (
        f"- **Mood:** {n}\n- **City:** {n}\n\n"
        f"### Highlight\n\n- {n}\n- **Remember:** {n}\n\n"
        "### Food\n\n#### Leo\n\n"
        f"- **Morning:** {n}\n- **Lunch:** {n}\n- **Dinner:** {n}\n"
        f"- **Snacks / drinks / other:** {n}\n\n"
        f"### Places visited\n\n- {n}\n\n"
        f"### People we met or visited\n\n- {n}\n\n"
        f"### Health and fitness\n\n#### Leo\n\n- {n}\n\n"
        f"### Feelings\n\n#### Leo\n\n- {n}\n\n"
        f"### Memories\n\n#### Together\n\n- {n}\n\n#### Leo\n\n- {n}\n\n"
        "### Weather\n\n- not looked up\n\n"
        f"### Things we did\n\n- {n}"
    )
    assert D.parse_facts_section(D.render_facts_section(D.DayFacts())) == (D.DayFacts(), "")
    assert D.render_facts_section(D.DayFacts(), include_empty=False) == ""
    compact = D.render_facts_section(
        D.DayFacts(mood="ok", family=[D.FamilyMember(name="Leo")]), include_empty=False
    )
    assert compact == "- **Mood:** ok"
    old_spelling = D.parse_facts_section(
        "### Places visited\n- none\n### Feelings\n#### Leo\n- none"
    )
    assert old_spelling == (D.DayFacts(family=[D.FamilyMember(name="Leo")]), "")


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


def test_fact_keys_in_the_front_matter_of_a_format_3_file_are_kept(
    sample_day_markdown: str,
) -> None:
    md = sample_day_markdown.replace("lumitrace_format: 3", "lumitrace_format: 3\nmood: sleepy")
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
    assert parsed.facts == day.facts
    assert (parsed.title, parsed.journal, parsed.notes) == (day.title, day.journal, day.notes)
    assert [(c.id, c.text, c.audio, c.photos) for c in parsed.captures] == [
        (c.id, c.text, c.audio, c.photos) for c in day.captures
    ]
    assert D.render(parsed) == md
    assert parsed.meta.model_extra == {"tags": ["journal", "family"]}


def test_capture_translation_roundtrip_and_hand_edits() -> None:
    day = D.DayFile(
        meta=D.FrontMatter(date=DAY),
        captures=[
            capture(
                "c1",
                at(21, 30),
                kind="recording",
                text="mana park ki vellam",
                translation="We went to the park.\n\nThen home.",
                audio="2026-10-10-2130.m4a",
            ),
            capture("c2", at(22), kind="recording", translation="Only a translation."),
        ],
    )
    md = D.render(day)
    assert "mana park ki vellam" in md
    assert "English translation" not in md
    assert D.TRANSLATION_MARKER not in md
    parsed = D.parse(md)
    assert parsed.captures[0].translation == ""
    assert parsed.captures[1].translation == ""
    legacy = (
        "---\ndate: 2026-10-10\n---\n\n# T\n\n## Transcript\n\n"
        "<!-- lumitrace:transcript:start -->\n"
        '<!-- lumitrace:capture {"id": "c1", "kind": "recording", '
        '"captured_at": "2026-10-10T21:30:00-05:00"} -->\n'
        "### 21:30 · Log My Day\n\nmana park ki vellam\n\n"
        f"{D.TRANSLATION_MARKER}\n#### English translation\n\nWe went to the park.\n"
        "<!-- lumitrace:transcript:end -->\n"
    )
    assert D.parse(legacy).captures[0].translation == "We went to the park."
    edited = legacy.replace("#### English translation\n\nWe went", "We went").replace(
        D.TRANSLATION_MARKER, "<!-- lumen:translation -->"
    )
    first = D.parse(edited).captures[0]
    assert (first.text, first.translation) == ("mana park ki vellam", "We went to the park.")


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
        md.index("### Highlight"),
        md.index("### Food"),
        md.index("### Places visited"),
        md.index("### People we met or visited"),
        md.index("### Health and fitness"),
        md.index("### Feelings"),
        md.index("### Memories"),
        md.index("### Weather"),
        md.index("### Things we did"),
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
    rewritten = D.parse(rendered)
    assert rewritten.notes == day.notes
    assert rewritten.journal == day.journal


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
        (
            "- **Dinner:** pasta\n- **Snacks / drinks / other:** horchata",
            "- **Dinner:** pasta, salad",
        ),
        ("- the taco truck (Sam, Maya)\n", ""),
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
    written = D.parse(D.render(new))
    assert written.facts == day.facts
    assert (written.title, written.journal, written.notes) == (new.title, new.journal, new.notes)
    assert [c.id for c in written.captures] == [c.id for c in new.captures]
    assert not written.is_user_edited()


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
    source_hash = day.compute_source_hash()
    gen = D.apply_generation(
        day,
        facts=_facts(meals=[D.Meal(type="breakfast", items=["eggs"])]),
        journal="## Summary\n\nEggs.",
        title="Eggs day",
        prompt_version="v1",
        models_used={"extract_facts": "m"},
        generated_at=at(9, 5),
        generated_source_hash=source_hash,
    )
    assert gen.title == "Eggs day"
    assert gen.facts.meals[0].items == ["eggs"]
    assert gen.meta.prompt_version == "v1"
    assert gen.meta.generated_hash == gen.compute_generated_hash()
    assert gen.meta.generated_source_hash == source_hash
    assert not gen.is_user_edited()
    regen = D.apply_generation(gen, facts=_facts(mood="ok"), journal="New.")
    assert regen.title == "Eggs day"
    assert regen.facts.meals == []
    assert regen.meta.prompt_version == "v1"


def test_source_hash_tracks_transcripts_and_notes_not_generated_words() -> None:
    day = D.merge_capture(None, capture("a", at(9), text="eggs"), DAY)
    original = day.compute_source_hash()
    day.journal = "## Summary\n\nGenerated words."
    day.title = "Generated title"
    assert day.compute_source_hash() == original
    day.notes = "Owner detail."
    assert day.compute_source_hash() != original


def test_apply_generation_refuses_user_edits(sample_day_markdown: str) -> None:
    day = D.parse(sample_day_markdown.replace("**Mood:** happy", "**Mood:** great"))
    with pytest.raises(D.UserEditsDetected):
        D.apply_generation(day, facts=_facts(), journal="x")
    forced = D.apply_generation(day, facts=_facts(), journal="x", force=True)
    assert forced.notes == day.notes
    assert not forced.is_user_edited()


def test_section_merge_on_edited_day_keeps_edits(sample_day_markdown: str) -> None:
    day = D.parse(sample_day_markdown.replace("**Mood:** happy", "**Mood:** great"))
    assert day.is_user_edited()
    merged = D.merge_generation_additive(
        day,
        facts=_facts(
            mood="sad",
            remember="a night walk",
            people=["ravi, neighbour - at the river trail (Sam)", "Zoe, friend"],
            places=["The river trail (Sam)", "the night market (Sam)"],
            memories=["star count"],
            family=[
                D.FamilyMember(
                    name="leo",
                    feelings=["sleepy"],
                    meals=[D.Meal(type="Dinner", items=["Pasta", "ice cream"])],
                ),
                D.FamilyMember(name="Maya", health=["headache"]),
                D.FamilyMember(name="Rose", moments=["visited"]),
            ],
            meals=[D.Meal(type="snack", items=["apple"])],
            activities=[
                D.Activity(kind="run (Sam)", minutes=10),
                D.Activity(kind="yoga (Sam)", minutes=20),
            ],
            highlights=["Night walk"],
        ),
        journal_sections={"Evening": ["A late walk."]},
        prompt_version="v2",
        generated_at=at(23),
    )
    assert merged.facts.mood == "great"
    assert merged.facts.remember == day.facts.remember
    assert merged.facts.people == [
        "Ravi, neighbour - at the river trail (Sam)",
        "Zoe, friend",
    ]
    assert merged.facts.places == [
        "the river trail (Sam)",
        "the taco truck (Sam, Maya)",
        "home (Sam, Maya, Leo)",
        "the night market (Sam)",
    ]
    assert merged.facts.memories == ["Leo's first tooth came out at bedtime", "star count"]
    _sam, maya, leo, rose = merged.facts.family
    assert (leo.name, leo.feelings) == ("Leo", ["proud", "sleepy"])
    assert leo.meals == [D.Meal(type="dinner", items=["pasta", "ice cream"])]
    assert leo.moments == ["lost his first tooth"]
    assert (maya.meals, maya.health) == ([D.Meal(type="lunch", items=["fish tacos"])], ["headache"])
    assert rose.moments == ["visited"]
    assert merged.facts.meals == [D.Meal(type="snacks", items=["apple"])]
    assert [a.kind for a in merged.facts.activities] == ["run (Sam)", "reading (Sam)", "yoga (Sam)"]
    assert merged.facts.activities[0].minutes == 40
    assert merged.journal.startswith(day.journal)
    assert merged.journal.endswith(
        "Pasta at home. Leo lost his first tooth and was very proud. "
        "Late at night you finished the book you had been reading."
        "\n\n- A late walk."
    )
    assert "## Later" not in merged.journal
    assert merged.notes == day.notes
    assert merged.meta.prompt_version == "v2"
    assert merged.meta.generated_hash == day.meta.generated_hash
    assert merged.is_user_edited()
    again = D.merge_generation_additive(
        merged, facts=D.DayFacts(), journal_sections={"Evening": ["Stars."]}
    )
    assert again.journal.endswith("- A late walk.\n\n- Stars.")
    assert "## Later" not in again.journal


def test_additive_merge_on_clean_day_refreshes_hash(sample_day_markdown: str) -> None:
    day = D.parse(sample_day_markdown)
    merged = D.merge_generation_additive(day, facts=_facts(people=["Sam"]))
    assert merged.facts.people[-1] == "Sam"
    assert not merged.is_user_edited()


def test_three_way_facts_merge_keeps_owner_additions_changes_and_removals() -> None:
    base = D.DayFacts(
        mood="content",
        people=["Ravi", "Zoe"],
        places=["home"],
        meals=[D.Meal(type="breakfast", items=["eggs", "toast"])],
        activities=[D.Activity(kind="run", minutes=40)],
        family=[
            D.FamilyMember(
                name="Leo",
                meals=[D.Meal(type="breakfast", items=["oatmeal", "banana"])],
                feelings=["happy"],
            )
        ],
    )
    current = base.model_copy(deep=True)
    current.mood = "proud"
    current.people = ["Ravi", "Owner friend"]
    current.meals = [D.Meal(type="breakfast", items=["eggs", "coffee"])]
    current.activities = [D.Activity(kind="run", minutes=50)]
    current.family[0].meals = [D.Meal(type="breakfast", items=["oatmeal", "berries"])]
    current.family[0].feelings = ["proud"]
    incoming = D.DayFacts(
        mood="happy",
        people=["Ravi", "Zoe", "Priya"],
        places=["the park"],
        meals=[
            D.Meal(type="breakfast", items=["eggs", "toast", "pancakes"]),
            D.Meal(type="dinner", items=["rice"]),
        ],
        activities=[
            D.Activity(kind="run", minutes=30),
            D.Activity(kind="yoga", minutes=20),
        ],
        family=[
            D.FamilyMember(
                name="Leo",
                meals=[D.Meal(type="breakfast", items=["oatmeal", "banana", "pancakes"])],
                feelings=["happy", "sleepy"],
            )
        ],
    )

    merged = D.merge_facts_three_way(base, current, incoming)

    assert merged.mood == "proud"
    assert merged.people == ["Ravi", "Priya", "Owner friend"]
    assert merged.places == ["the park"]
    assert merged.meals == [
        D.Meal(type="breakfast", items=["eggs", "pancakes", "coffee"]),
        D.Meal(type="dinner", items=["rice"]),
    ]
    assert merged.activities == [
        D.Activity(kind="run", minutes=50),
        D.Activity(kind="yoga", minutes=20),
    ]
    assert merged.family[0].meals == [
        D.Meal(type="breakfast", items=["oatmeal", "pancakes", "berries"])
    ]
    assert merged.family[0].feelings == ["sleepy", "proud"]


def test_three_way_keeps_one_wording_of_the_same_fact() -> None:
    base = D.DayFacts(highlights=["Sulemani chai", "Walk"])
    current = D.DayFacts(
        highlights=[
            "Sulemani chai",
            "Sulemani chai (spiced black tea)",
            "Walk",
            "A note I added",
        ]
    )
    incoming = D.DayFacts(
        highlights=["Sulemani chai (spiced black tea)", "Movie night"],
        activities=[
            D.Activity(kind="Netflix, two or three episodes [uncertain: count]", minutes=None)
        ],
    )
    current.activities = [D.Activity(kind="Netflix", minutes=90)]
    base.activities = [D.Activity(kind="Netflix", minutes=90)]
    merged = D.merge_facts_three_way(base, current, incoming)
    assert merged.highlights == [
        "Sulemani chai (spiced black tea)",
        "Movie night",
        "A note I added",
    ]
    assert [(item.kind, item.minutes) for item in merged.activities] == [
        ("Netflix, two or three episodes [uncertain: count]", None)
    ]


def test_journal_replacement_corrects_a_model_sentence_and_keeps_an_edit() -> None:
    model = "## Evening\n\n- mushroom masala curry, okayish.\n\n- You went to bed."
    live = "## Evening\n\n- mushroom masala curry, okayish.\n\n- I rewrote the bedtime line."
    replaced = D.apply_journal_replacements(
        live,
        [
            ("mushroom masala curry, okayish.", "meal maker curry."),
            ("I rewrote the bedtime line.", "The model tried to undo the edit."),
        ],
        model_journal=model,
    )
    assert "meal maker curry." in replaced
    assert "mushroom masala" not in replaced
    assert "I rewrote the bedtime line." in replaced
    assert "undo the edit" not in replaced


def test_clean_journal_is_replaced_and_an_edited_one_keeps_its_words() -> None:
    day = D.DayFile.new(DAY)
    day.journal = "## Summary\n\n- Old sentence."
    day.meta.generated_hash = day.compute_generated_hash()
    base = D.DayFacts(highlights=["Old"])
    incoming = D.DayFacts(highlights=["New"])
    rewritten = D.merge_generation_three_way(
        day,
        base_facts=base,
        facts=incoming,
        replacement_journal="## Summary\n\n- New sentence.",
        model_journal=day.journal,
    )
    assert rewritten.journal == "## Summary\n\n- New sentence."
    assert rewritten.facts.highlights == ["New"]
    assert not rewritten.is_user_edited()

    edited = day.model_copy(deep=True)
    edited.journal = "## Summary\n\n- My sentence."
    kept = D.merge_generation_three_way(
        edited,
        base_facts=base,
        facts=incoming,
        replacement_journal="## Summary\n\n- New sentence.",
        model_journal=day.journal,
        journal_sections={"Summary": ["A new bullet.", "My sentence."]},
    )
    assert kept.journal.count("My sentence.") == 1
    assert "A new bullet." in kept.journal
    assert "New sentence." not in kept.journal
    assert kept.facts.highlights == ["New"]
    assert kept.is_user_edited()


def test_section_merge_skips_a_bullet_already_on_the_page() -> None:
    merged = D.merge_journal_sections(
        "## Evening\n\n- Ate dinner.",
        {"Evening": ["Ate dinner.", "A late walk."]},
    )
    assert merged.count("Ate dinner.") == 1
    assert "A late walk." in merged


def test_section_merge_inserts_missing_sections_in_journal_order() -> None:
    journal = "## Summary\n\n- Started the day.\n\n## Evening\n\n- Ate dinner."
    merged = D.merge_journal_sections(
        journal,
        {
            "Afternoon": ["Visited the park."],
            "Thoughts": ["Felt grateful."],
        },
    )
    assert merged == (
        "## Summary\n\n- Started the day.\n\n"
        "## Afternoon\n\n- Visited the park.\n\n"
        "## Evening\n\n- Ate dinner.\n\n"
        "## Thoughts\n\n- Felt grateful."
    )
    assert "## Later" not in merged


def test_section_merge_moves_legacy_later_content_to_evening() -> None:
    journal = "## Summary\n\n- Started the day.\n\n## Later\n\n- Existing late detail."
    merged = D.merge_journal_sections(journal, {"Evening": ["New late detail."]})
    assert "## Later" not in merged
    assert "## Evening\n\n- Existing late detail.\n\n- New late detail." in merged
