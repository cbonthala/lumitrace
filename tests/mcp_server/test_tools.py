from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

import pytest

from lifelog.config import Settings
from lifelog.index.schema import connect, reset_derived
from lifelog.mcp_server import dates as D
from lifelog.mcp_server import tools as T
from lifelog.mcp_server.dates import DateArgumentError
from lifelog.mcp_server.index import INDEX_MISSING_NOTE
from lifelog.mcp_server.tools import LifeLogTools, ToolInputError
from lifelog.storage.local import LocalStorage

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


def test_get_day_returns_everything(tools: LifeLogTools, populated: Path) -> None:
    out = tools.get_day("2026-10-10")
    assert out["found"] is True
    assert out["path"] == "2026/10/2026-10-10/2026-10-10.md"
    assert out["title"].endswith("First tooth")
    assert {"type": "drink", "items": ["horchata"]} in out["facts"]["meals"]
    assert out["facts"]["mood_score"] == 4
    assert "## Morning" in out["journal"]
    assert "tooth under the pillow" in out["notes"]
    assert [t["kind"] for t in out["transcript"]] == ["note", "recording", "note"]
    assert out["transcript"][1]["time"] == "2026-10-10T21:30:00-05:00"
    assert "Leo lost his first tooth" in out["transcript"][1]["text"]

    [audio] = out["audio"]
    assert audio["name"] == "2026-10-10-2130.m4a"
    assert audio["link"].startswith("file://") and audio["link"].endswith("2026-10-10-2130.m4a")
    photos = {p["name"]: p for p in out["photos"]}
    assert photos["photo-01.jpg"]["link"].startswith("file://")
    assert photos["photo-02.jpg"]["link"] is None  # not in storage
    assert photos["photo-02.jpg"]["error"] == "file not found in storage"


def test_get_day_missing_day(tools: LifeLogTools, populated: Path) -> None:
    out = tools.get_day("2026-01-01")
    assert out["found"] is False
    assert "no journal entry" in out["note"]


def test_get_day_works_without_index(tools: LifeLogTools, storage: LocalStorage, days) -> None:
    from lifelog.dayfile import day_file_path, render

    storage.write_text(day_file_path(days[0].date), render(days[0]))
    assert tools.get_day("2024-10-10")["found"] is True


def test_get_day_bad_date(tools: LifeLogTools) -> None:
    with pytest.raises(DateArgumentError):
        tools.get_day("October 10")


# --- query_facts ---------------------------------------------------------------------------


def test_query_facts_meals(tools: LifeLogTools, populated: Path) -> None:
    out = tools.query_facts("meals", contains="PASTA")
    assert [r["date"] for r in out["rows"]] == ["2026-10-10", "2026-09-15", "2025-10-10"]
    assert out["rows"][0] == {"date": "2026-10-10", "meal_type": "dinner", "item": "pasta"}
    assert out["counts"] == {
        "rows": 3,
        "days": 3,
        "first_date": "2025-10-10",
        "last_date": "2026-10-10",
    }
    assert out["aggregates"]["top_items"] == [{"item": "pasta", "times": 3, "days": 3}]
    assert out["truncated"] is False


def test_query_facts_meals_match_meal_type_and_aggregate(
    tools: LifeLogTools, populated: Path
) -> None:
    out = tools.query_facts("meals", contains="breakfast")
    assert {r["item"] for r in out["rows"]} == {"pancakes", "oatmeal", "blueberries"}
    everything = tools.query_facts("meals")
    by_type = {r["meal_type"]: r for r in everything["aggregates"]["by_meal_type"]}
    assert by_type["dinner"] == {"meal_type": "dinner", "items": 3, "days": 3}


def test_query_facts_activities(tools: LifeLogTools, populated: Path) -> None:
    out = tools.query_facts("activities", contains="run")
    assert out["counts"]["rows"] == 3
    [run] = out["aggregates"]["by_kind"]
    assert run == {"kind": "run", "times": 3, "days": 3, "total_minutes": 115, "avg_minutes": 38.3}
    assert out["aggregates"]["total_minutes"] == 115


def test_query_facts_date_filter(tools: LifeLogTools, populated: Path) -> None:
    out = tools.query_facts("activities", contains="run", from_date="2026-01-01")
    assert out["aggregates"]["total_minutes"] == 85
    out = tools.query_facts("activities", from_date="2024-10-10", to_date="2024-10-10")
    assert out["rows"] == [{"date": "2024-10-10", "kind": "hike", "minutes": 90}]


def test_query_facts_people(tools: LifeLogTools, populated: Path) -> None:
    out = tools.query_facts("people")
    by_person = {r["name"]: r for r in out["aggregates"]["by_person"]}
    assert by_person["Maya"]["days"] == 3
    assert by_person["Leo"]["first_date"] == "2024-10-10"
    assert by_person["Leo"]["last_date"] == "2026-10-10"
    assert tools.query_facts("people", contains="rose")["counts"]["days"] == 1


def test_query_facts_mood(tools: LifeLogTools, populated: Path) -> None:
    out = tools.query_facts("mood", from_date="2025-01-01")
    assert [r["date"] for r in out["rows"]] == ["2026-10-10", "2026-09-15", "2025-10-10"]
    agg = out["aggregates"]
    assert agg["average_score"] == pytest.approx((4 + 5 + 2) / 3, abs=0.01)
    assert (agg["min_score"], agg["max_score"], agg["days_with_score"]) == (2, 5, 3)
    assert {m["mood"] for m in agg["by_mood"]} == {"happy", "tired"}


def test_query_facts_family_events_and_highlights(tools: LifeLogTools, populated: Path) -> None:
    events = tools.query_facts("family_events")
    assert {r["text"] for r in events["rows"]} == {
        "Pumpkin patch with the kids",
        "Grandma Rose visited",
        "Leo lost his first tooth",
    }
    highlights = tools.query_facts("highlights", contains="tooth")
    assert highlights["rows"] == [{"date": "2026-10-10", "text": "Leo lost his first tooth"}]


def test_query_facts_limit_and_truncation(tools: LifeLogTools, populated: Path) -> None:
    out = tools.query_facts("meals", limit=2)
    assert len(out["rows"]) == 2
    assert out["truncated"] is True
    assert out["counts"]["rows"] > 2


def test_query_facts_like_wildcards_are_literal(tools: LifeLogTools, populated: Path) -> None:
    assert tools.query_facts("meals", contains="%")["rows"] == []
    assert tools.query_facts("meals", contains="_")["rows"] == []
    assert tools.query_facts("meals", contains="nothing")["note"] == "No matching facts found."


def test_query_facts_bad_kind(tools: LifeLogTools, populated: Path) -> None:
    with pytest.raises(ToolInputError):
        tools.query_facts("drinks")


def test_query_facts_missing_index(tools: LifeLogTools) -> None:
    out = tools.query_facts("meals")
    assert out["rows"] == [] and out["note"] == INDEX_MISSING_NOTE


# --- on_this_day ---------------------------------------------------------------------------


def test_on_this_day_with_full_date(tools: LifeLogTools, populated: Path) -> None:
    out = tools.on_this_day("2026-10-10")
    assert [d["date"] for d in out["days"]] == ["2025-10-10", "2024-10-10"]
    first = out["days"][0]
    assert first["years_ago"] == 1
    assert first["title"].endswith("Rainy day")
    assert first["people"] == ["Maya"]
    assert first["highlights"] == ["Finished the quarterly report"]
    assert "rainy Friday" in first["summary"]
    assert out["days"][1]["family_events"] == ["Pumpkin patch with the kids"]


def test_on_this_day_month_day_uses_current_year(
    tools: LifeLogTools, populated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(T, "today", lambda s: dt.date(2027, 1, 5))
    out = tools.on_this_day("10-10")
    assert out["reference_year"] == 2027
    assert [d["date"] for d in out["days"]] == ["2026-10-10", "2025-10-10", "2024-10-10"]
    assert [d["years_ago"] for d in out["days"]] == [1, 2, 3]


def test_on_this_day_defaults_to_today(
    tools: LifeLogTools, populated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(T, "today", lambda s: dt.date(2027, 9, 15))
    out = tools.on_this_day()
    assert [d["date"] for d in out["days"]] == ["2026-09-15"]


def test_on_this_day_years_back(tools: LifeLogTools, populated: Path) -> None:
    out = tools.on_this_day("2026-10-10", years_back=1)
    assert [d["date"] for d in out["days"]] == ["2025-10-10"]


def test_on_this_day_nothing(tools: LifeLogTools, populated: Path) -> None:
    out = tools.on_this_day("2026-02-02")
    assert out["days"] == [] and "No entries on 02-02" in out["note"]


def test_on_this_day_missing_index(tools: LifeLogTools) -> None:
    assert tools.on_this_day("10-10")["note"] == INDEX_MISSING_NOTE


# --- feedback ------------------------------------------------------------------------------


def _feedback_rows(settings: Settings) -> list[sqlite3.Row]:
    conn = connect(settings.index_path, settings.embedding_dimension, read_only=True)
    rows = conn.execute("SELECT * FROM feedback ORDER BY id").fetchall()
    conn.close()
    return rows


def test_feedback_writes_row_and_storage_copy(
    tools: LifeLogTools, settings: Settings, storage: LocalStorage, populated: Path
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
    tools: LifeLogTools, settings: Settings, populated: Path
) -> None:
    tools.feedback("q", "a", "wrong date")
    conn = connect(settings.index_path, settings.embedding_dimension)
    reset_derived(conn)
    conn.close()
    assert len(_feedback_rows(settings)) == 1


def test_feedback_creates_index_when_missing(tools: LifeLogTools, settings: Settings) -> None:
    out = tools.feedback("q", "a", "c", rating="good", dates=["2026-10-10"])
    assert out["id"] == 1 and out["dates"] == ["2026-10-10"]
    assert _feedback_rows(settings)[0]["rating"] == "good"


def test_feedback_validation(tools: LifeLogTools) -> None:
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

    tools = LifeLogTools(settings, BrokenStorage(settings.local_root))
    out = tools.feedback("q", "a", "c")
    assert out["saved"] is True and out["storage_path"] is None
    assert _feedback_rows(settings)[0]["storage_path"] is None
