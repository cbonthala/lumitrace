from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

import pytest

from lumitrace.config import Settings
from lumitrace.frames import daycontent as C
from lumitrace.frames.dayfile import DayFile, apply_content_generation, day_file_path, render
from lumitrace.frames.storage.local import LocalStorage
from lumitrace.index.schema import connect, reset_derived
from lumitrace.lens import dates as D
from lumitrace.lens import tools as T
from lumitrace.lens.dates import DateArgumentError
from lumitrace.lens.index import INDEX_MISSING_NOTE
from lumitrace.lens.tools import LensTools, ToolInputError
from lumitrace.spectrum.core import _insert_day


def _format6_day() -> DayFile:
    content = C.DayContent(
        timeline=C.Timeline(
            highlight="A full day",
            context=C.DayContext(
                weather="warm",
                places_visited=[C.PlaceContext(name="River Park", family_members=["Maya"])],
                people_met=[
                    C.PersonContext(
                        name="Dr. Rao",
                        relationship="pediatrician",
                        context="annual visit",
                        family_members=["Maya"],
                    )
                ],
            ),
            morning=["Packed lunch"],
            night=["Watched fireflies"],
            remember="Maya rode by herself",
        ),
        family=[
            C.FamilyTracker(
                name="Maya",
                food=C.FoodTracker(
                    breakfast=C.Meal(status="consumed", items=["cardamom pancakes"]),
                    lunch=C.Meal(status="skipped"),
                ),
                health_fitness=C.HealthFitness(
                    exercise_movement=[C.ExerciseMovement(activity="bicycle ride", minutes=25)],
                    energy=C.Rating(score=4, description="steady"),
                ),
                growth_learning=C.GrowthLearning(
                    new_skill_behavior=["rode without training wheels"]
                ),
            )
        ],
        pregnancy_baby=C.PregnancyBaby(
            pregnant_person="Sam",
            gestational_age="18 weeks",
            baby_movement=["two strong kicks"],
        ),
        tags=["family-adventure"],
    )
    return apply_content_generation(
        DayFile.new(dt.date(2026, 10, 12)),
        content=content,
        title="Monday, October 12, 2026 · Bicycle day",
        force=True,
    )


# --- dates ---------------------------------------------------------------------------------


def test_parse_date_formats(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    assert D.parse_date("2026-10-10", settings) == dt.date(2026, 10, 10)
    assert D.parse_date(" 2026-10-10 ", settings) == dt.date(2026, 10, 10)
    monkeypatch.setattr(D, "today", lambda s: dt.date(2026, 3, 1))
    assert D.parse_date("Today", settings) == dt.date(2026, 3, 1)
    assert D.parse_date("yesterday", settings) == dt.date(2026, 2, 28)
    for bad in ["10/10/2026", "2026-13-01", "last tuesday", "20261010", ""]:
        with pytest.raises(DateArgumentError):
            D.parse_date(bad, settings)


def test_parse_month_day() -> None:
    assert D.parse_month_day("10-10") == (10, 10)
    assert D.parse_month_day("--02-29") == (2, 29)
    assert D.parse_month_day("2026-10-10") is None
    with pytest.raises(DateArgumentError):
        D.parse_month_day("13-01")


# --- get_day -------------------------------------------------------------------------------


def test_get_day_returns_everything(tools: LensTools, populated: Path) -> None:
    out = tools.get_day("2026-10-10")
    assert out["found"] is True
    assert out["path"] == "2026/10/2026-10-10/2026-10-10.md"
    assert out["title"].endswith("First tooth")
    sam = out["facts"]["family"][0]
    assert {"type": "snacks", "items": ["horchata"]} in sam["meals"]
    assert out["facts"]["mood_score"] == 4
    assert "## Morning" in out["journal"]
    assert "tooth under the pillow" in out["notes"]
    assert [t["kind"] for t in out["transcript"]] == ["note", "recording", "note"]
    assert out["transcript"][1]["time"] == "2026-10-10T21:30:00-05:00"
    assert "Leo lost his first tooth" in out["transcript"][1]["text"]
    assert out["transcript"][1]["translation"] is None

    [audio] = out["audio"]
    assert audio["name"] == "2026-10-10-2130.m4a"
    assert audio["link"].startswith("file://") and audio["link"].endswith("2026-10-10-2130.m4a")
    photos = {p["name"]: p for p in out["photos"]}
    assert photos["photo-01.jpg"]["link"].startswith("file://")
    assert photos["photo-02.jpg"]["link"] is None  # not in storage
    assert photos["photo-02.jpg"]["error"] == "file not found in storage"


def test_get_day_missing_day(tools: LensTools, populated: Path) -> None:
    out = tools.get_day("2026-01-01")
    assert out["found"] is False
    assert "no journal entry" in out["note"]


def test_get_day_works_without_index(tools: LensTools, storage: LocalStorage, days) -> None:
    from lumitrace.frames.dayfile import day_file_path, render

    storage.write_text(day_file_path(days[0].date), render(days[0]))
    assert tools.get_day("2024-10-10")["found"] is True


def test_get_day_bad_date(tools: LensTools) -> None:
    with pytest.raises(DateArgumentError):
        tools.get_day("October 10")


def test_get_day_returns_canonical_format6_content(tools: LensTools, storage: LocalStorage) -> None:
    day = _format6_day()
    storage.write_text(day_file_path(day.date), render(day))

    out = tools.get_day(day.date.isoformat())

    assert out["format_version"] == 6
    assert out["content"] == day.content.model_dump(mode="json")
    assert out["content"]["family"][0]["health_fitness"]["energy"]["score"] == 4
    assert out["content"]["pregnancy_baby"]["baby_movement"] == ["two strong kicks"]
    assert out["content"]["tags"] == ["family-adventure"]
    assert out["facts"]["highlights"] == ["A full day"]
    assert out["facts"]["family"][0]["meals"][0] == {
        "type": "breakfast",
        "items": ["cardamom pancakes"],
    }


# --- query_facts ---------------------------------------------------------------------------


def test_query_facts_meals(tools: LensTools, populated: Path) -> None:
    out = tools.query_facts("meals", contains="PASTA")
    assert [r["date"] for r in out["rows"]] == [
        "2026-10-10",
        "2026-10-10",
        "2026-09-15",
        "2025-10-10",
    ]
    assert out["rows"][0] == {
        "date": "2026-10-10",
        "person": "Sam",
        "meal_type": "dinner",
        "item": "pasta",
    }
    assert out["counts"] == {
        "rows": 4,
        "days": 3,
        "first_date": "2025-10-10",
        "last_date": "2026-10-10",
    }
    assert out["aggregates"]["top_items"] == [{"item": "pasta", "times": 4, "days": 3}]
    assert out["truncated"] is False


def test_query_facts_meals_match_meal_type_and_aggregate(tools: LensTools, populated: Path) -> None:
    out = tools.query_facts("meals", contains="breakfast")
    assert {r["item"] for r in out["rows"]} == {"pancakes", "oatmeal", "blueberries"}
    everything = tools.query_facts("meals")
    by_type = {r["meal_type"]: r for r in everything["aggregates"]["by_meal_type"]}
    assert by_type["dinner"] == {"meal_type": "dinner", "items": 4, "days": 3}


def test_query_facts_activities(tools: LensTools, populated: Path) -> None:
    out = tools.query_facts("activities", contains="run")
    assert out["counts"]["rows"] == 3
    by_kind = {r["kind"]: r for r in out["aggregates"]["by_kind"]}
    assert by_kind["run (sam)"]["total_minutes"] == 40
    assert by_kind["run"] == {
        "kind": "run",
        "times": 2,
        "days": 2,
        "total_minutes": 75,
        "avg_minutes": 37.5,
    }
    assert out["aggregates"]["total_minutes"] == 115


def test_query_facts_date_filter(tools: LensTools, populated: Path) -> None:
    out = tools.query_facts("activities", contains="run", from_date="2026-01-01")
    assert out["aggregates"]["total_minutes"] == 85
    out = tools.query_facts("activities", from_date="2024-10-10", to_date="2024-10-10")
    assert out["rows"] == [{"date": "2024-10-10", "kind": "hike", "minutes": 90}]


def test_query_facts_people(tools: LensTools, populated: Path) -> None:
    out = tools.query_facts("people")
    by_person = {r["name"]: r for r in out["aggregates"]["by_person"]}
    assert by_person["Maya"]["days"] == 2
    assert by_person["Leo"]["first_date"] == "2024-10-10"
    assert by_person["Leo"]["last_date"] == "2026-09-15"
    assert by_person["Ravi, neighbour - at the river trail (Sam)"]["days"] == 1
    assert tools.query_facts("people", contains="rose")["counts"]["days"] == 1


def test_query_facts_places(tools: LensTools, populated: Path) -> None:
    out = tools.query_facts("places")
    assert out["rows"][:3] == [
        {"date": "2026-10-10", "name": "the river trail (Sam)"},
        {"date": "2026-10-10", "name": "the taco truck (Sam, Maya)"},
        {"date": "2026-10-10", "name": "home (Sam, Maya, Leo)"},
    ]
    by_place = {r["name"].lower(): r for r in out["aggregates"]["by_place"]}
    assert by_place["home"]["days"] == 1
    assert by_place["home"]["first_date"] == "2026-09-15"
    assert tools.query_facts("places", contains="farm")["counts"]["days"] == 2


def test_query_facts_mood(tools: LensTools, populated: Path) -> None:
    out = tools.query_facts("mood", from_date="2025-01-01")
    assert [r["date"] for r in out["rows"]] == ["2026-10-10", "2026-09-15", "2025-10-10"]
    agg = out["aggregates"]
    assert agg["average_score"] == pytest.approx((4 + 5 + 2) / 3, abs=0.01)
    assert (agg["min_score"], agg["max_score"], agg["days_with_score"]) == (2, 5, 3)
    assert {m["mood"] for m in agg["by_mood"]} == {"happy", "tired"}


def test_query_facts_meals_for_one_person(tools: LensTools, populated: Path) -> None:
    leo = tools.query_facts("meals", person="leo")
    assert leo["person"] == "leo"
    assert [(r["date"], r["meal_type"], r["item"]) for r in leo["rows"]] == [
        ("2026-10-10", "dinner", "pasta"),
        ("2026-09-15", "dinner", "pasta"),
        ("2026-09-15", "snacks", "lemonade"),
        ("2024-10-10", "snacks", "pumpkin pie"),
    ]
    assert {r["person"] for r in leo["rows"]} == {"Leo"}
    top = leo["aggregates"]["top_items"][0]
    assert (top["item"], top["times"], top["days"]) == ("pasta", 2, 2)
    sam = tools.query_facts("meals", person="Sam", contains="breakfast")
    assert [r["item"] for r in sam["rows"]] == ["oatmeal", "blueberries"]


def test_query_facts_family(tools: LensTools, populated: Path) -> None:
    leo = tools.query_facts("family", person="leo", contains="moments")
    assert [(r["date"], r["text"]) for r in leo["rows"]] == [
        ("2026-10-10", "lost his first tooth"),
        ("2026-09-15", "passed the spelling test"),
        ("2024-10-10", "picked the biggest pumpkin"),
    ]
    everyone = tools.query_facts("family")
    by = {(r["person"], r["category"]): r for r in everyone["aggregates"]["by_person_and_category"]}
    assert by[("Leo", "moments")]["days"] == 3
    assert by[("Leo", "feelings")]["days"] == 2
    assert by[("Maya", "moments")]["days"] == 1
    assert by[("Together", "moments")]["days"] == 1
    assert tools.query_facts("family", contains="dentist")["rows"] == []
    health = tools.query_facts("family", contains="runny")["rows"]
    assert health == [
        {
            "date": "2026-09-15",
            "person": "Leo",
            "category": "health",
            "text": "a runny nose",
            "minutes": None,
        }
    ]
    with pytest.raises(ToolInputError):
        tools.query_facts("people", person="Leo")


def test_query_facts_highlights(tools: LensTools, populated: Path) -> None:
    highlights = tools.query_facts("highlights", contains="tooth")
    assert highlights["rows"] == [{"date": "2026-10-10", "text": "Leo lost his first tooth"}]


def test_query_facts_limit_and_truncation(tools: LensTools, populated: Path) -> None:
    out = tools.query_facts("meals", limit=2)
    assert len(out["rows"]) == 2
    assert out["truncated"] is True
    assert out["counts"]["rows"] > 2


def test_query_facts_like_wildcards_are_literal(tools: LensTools, populated: Path) -> None:
    assert tools.query_facts("meals", contains="%")["rows"] == []
    assert tools.query_facts("meals", contains="_")["rows"] == []
    assert tools.query_facts("meals", contains="nothing")["note"] == "No matching facts found."


def test_query_facts_bad_kind(tools: LensTools, populated: Path) -> None:
    with pytest.raises(ToolInputError):
        tools.query_facts("drinks")


def test_query_facts_missing_index(tools: LensTools) -> None:
    out = tools.query_facts("meals")
    assert out["rows"] == [] and out["note"] == INDEX_MISSING_NOTE


def test_query_format6_content_scopes(
    tools: LensTools, settings: Settings, populated: Path
) -> None:
    day = _format6_day()
    conn = connect(populated, settings.embedding_dimension)
    with conn:
        _insert_day(conn, day_file_path(day.date), day)
    conn.close()

    met = tools.query_facts("timeline", contains="annual visit")
    assert met["rows"][0]["field"] == "people_met"
    assert met["rows"][0]["text"] == "Dr. Rao"
    assert met["rows"][0]["details"]["relationship"] == "pediatrician"

    growth = tools.query_facts("trackers", person="maya", contains="training wheels")
    assert growth["rows"][0] == {
        "date": "2026-10-12",
        "scope": "family",
        "person": "Maya",
        "category": "growth_learning",
        "field": "new_skill_behavior",
        "text": "rode without training wheels",
        "number": None,
        "status": None,
    }
    skipped = tools.query_facts("trackers", person="Maya", contains="skipped")
    assert skipped["rows"][0]["field"] == "lunch"
    assert skipped["rows"][0]["status"] == "skipped"
    assert skipped["rows"][0]["details"] == {"items": [], "status": "skipped"}

    pregnancy = tools.query_facts("pregnancy", contains="strong kicks")
    assert pregnancy["rows"][0]["field"] == "baby_movement"
    assert pregnancy["rows"][0]["text"] == "two strong kicks"
    tags = tools.query_facts("tags", contains="family-adventure")
    assert tags["rows"][0]["text"] == "family-adventure"
    assert tools.query_facts("content", person="Maya")["counts"]["rows"] > 0


# --- on_this_day ---------------------------------------------------------------------------


def test_on_this_day_with_full_date(tools: LensTools, populated: Path) -> None:
    out = tools.on_this_day("2026-10-10")
    assert [d["date"] for d in out["days"]] == ["2025-10-10", "2024-10-10"]
    first = out["days"][0]
    assert first["years_ago"] == 1
    assert first["title"].endswith("Rainy day")
    assert first["people"] == ["Maya"]
    assert first["highlights"] == ["Finished the quarterly report"]
    assert "rainy Friday" in first["summary"]
    assert out["days"][1]["family"][0] == {
        "person": "Leo",
        "category": "moments",
        "text": "picked the biggest pumpkin",
        "minutes": None,
    }
    assert first["family"] == []
    assert out["days"][1]["places"] == ["Pumpkin patch", "the farm trail"]
    assert first["places"] == []


def test_on_this_day_month_day_uses_current_year(
    tools: LensTools, populated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(T, "today", lambda s: dt.date(2027, 1, 5))
    out = tools.on_this_day("10-10")
    assert out["reference_year"] == 2027
    assert [d["date"] for d in out["days"]] == ["2026-10-10", "2025-10-10", "2024-10-10"]
    assert [d["years_ago"] for d in out["days"]] == [1, 2, 3]


def test_on_this_day_defaults_to_today(
    tools: LensTools, populated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(T, "today", lambda s: dt.date(2027, 9, 15))
    out = tools.on_this_day()
    assert [d["date"] for d in out["days"]] == ["2026-09-15"]


def test_on_this_day_years_back(tools: LensTools, populated: Path) -> None:
    out = tools.on_this_day("2026-10-10", years_back=1)
    assert [d["date"] for d in out["days"]] == ["2025-10-10"]


def test_on_this_day_nothing(tools: LensTools, populated: Path) -> None:
    out = tools.on_this_day("2026-02-02")
    assert out["days"] == [] and "No entries on 02-02" in out["note"]


def test_on_this_day_missing_index(tools: LensTools) -> None:
    assert tools.on_this_day("10-10")["note"] == INDEX_MISSING_NOTE


# --- feedback ------------------------------------------------------------------------------


def _feedback_rows(settings: Settings) -> list[sqlite3.Row]:
    conn = connect(settings.index_path, settings.embedding_dimension, read_only=True)
    rows = conn.execute("SELECT * FROM feedback ORDER BY id").fetchall()
    conn.close()
    return rows


def test_feedback_writes_row_and_storage_copy(
    tools: LensTools, settings: Settings, storage: LocalStorage, populated: Path
) -> None:
    out = tools.feedback(
        question="What did I eat on 2026-10-10?",
        answer="On 2026-10-10 you had pasta; on 2025-10-10 ramen.",
        comment="You forgot the fish tacos.",
        rating="incomplete",
        tool="get_day",
        client="Test App",
    )
    assert out["saved"] is True and out["rating"] == "incomplete"
    assert out["dates"] == ["2025-10-10", "2026-10-10"]
    [row] = _feedback_rows(settings)
    assert row["id"] == out["id"]
    assert row["rating"] == "incomplete"
    assert row["comment"] == "You forgot the fish tacos."
    assert json.loads(row["dates_json"]) == ["2025-10-10", "2026-10-10"]
    assert (row["tool"], row["client"]) == ("get_day", "Test App")
    assert row["storage_path"] == out["storage_path"]
    assert out["storage_path"].startswith("_system/feedback/")
    copy = json.loads(storage.read_text(out["storage_path"]))
    assert copy["comment"] == "You forgot the fish tacos." and copy["rating"] == "incomplete"


def test_feedback_survives_index_rebuild(
    tools: LensTools, settings: Settings, populated: Path
) -> None:
    tools.feedback("q", "a", "wrong date")
    conn = connect(settings.index_path, settings.embedding_dimension)
    reset_derived(conn)
    conn.close()
    assert len(_feedback_rows(settings)) == 1


def test_feedback_creates_index_when_missing(tools: LensTools, settings: Settings) -> None:
    out = tools.feedback("q", "a", "c", rating="good", dates=["2026-10-10"])
    assert out["id"] == 1 and out["dates"] == ["2026-10-10"]
    assert _feedback_rows(settings)[0]["rating"] == "good"


def test_feedback_validation(tools: LensTools) -> None:
    with pytest.raises(ToolInputError):
        tools.feedback("q", "a", "c", rating="terrible")
    with pytest.raises(ToolInputError):
        tools.feedback("q", "a", "c", dates=["yesterday-ish"])
    with pytest.raises(ToolInputError):
        tools.feedback("", "", "")


def test_feedback_still_saved_when_storage_fails(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    class BrokenStorage(LocalStorage):
        def write_text(self, *args: object, **kwargs: object):  # type: ignore[override]
            raise OSError("disk full")

    tools = LensTools(settings, BrokenStorage(settings.local_root))
    out = tools.feedback("q", "a", "c")
    assert out["saved"] is True and out["storage_path"] is None
    assert _feedback_rows(settings)[0]["storage_path"] is None
