from __future__ import annotations

import datetime as dt
import json
import sqlite3

from lumitrace.frames import daycontent as C
from lumitrace.frames.dayfile import (
    Capture,
    DayFile,
    apply_content_generation,
    day_file_path,
    generated_snapshot_path,
    merge_capture,
    parse,
    render,
)
from lumitrace.frames.storage.local import LocalStorage
from lumitrace.index.schema import reset_derived
from lumitrace.spectrum.core import Indexer
from lumitrace.spectrum.edits import compare_day, text_diff
from tests.spectrum.conftest import TZ, make_day, write_day

D1 = dt.date(2026, 10, 10)


def _signals(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM edit_signals ORDER BY section, field, id").fetchall()


def _edit(storage: LocalStorage, day_date: dt.date, change) -> DayFile:
    path = day_file_path(day_date)
    day = parse(storage.read_text(path))
    change(day)
    storage.write_text(path, render(day))
    return day


def _owner_edits(day: DayFile) -> None:
    day.journal = day.journal.replace("Soup.", "Lentil soup, very good.")
    day.title = "Heron day"
    day.notes = "Slept 8 hours."
    day.captures[0].text = day.captures[0].text.replace("Robin", "Robyn")


def test_no_signals_when_file_matches_snapshot(indexer: Indexer, storage: LocalStorage) -> None:
    write_day(storage, make_day(D1))
    result = indexer.sync()
    assert result.edit_signals == 0
    assert _signals(indexer.conn) == []


def test_owner_edits_become_signals(indexer: Indexer, storage: LocalStorage) -> None:
    write_day(storage, make_day(D1))
    indexer.sync()
    _edit(storage, D1, _owner_edits)

    result = indexer.sync()

    rows = _signals(indexer.conn)
    keys = {(r["section"], r["field"]) for r in rows}
    capture_id = parse(storage.read_text(day_file_path(D1))).captures[0].id
    assert keys == {
        ("journal", None),
        ("notes", None),
        ("title", None),
        ("transcript", capture_id),
    }
    assert result.edit_signals == 4
    by_key = {(r["section"], r["field"]): r for r in rows}
    journal = by_key[("journal", None)]
    assert "-Soup." in journal["diff"] and "+Lentil soup, very good." in journal["diff"]
    assert journal["prompt_version"] == "journal-v1"
    assert json.loads(journal["models_used_json"]) == {"write_journal": "fake/model"}
    assert journal["path"] == day_file_path(D1)
    assert by_key[("notes", None)]["after"] == "Slept 8 hours."
    day = indexer.conn.execute("SELECT user_edited FROM days").fetchone()
    assert day["user_edited"] == 1


def test_owner_fact_edits_become_field_signals(indexer: Indexer, storage: LocalStorage) -> None:
    write_day(storage, make_day(D1))
    indexer.sync()

    def edit_facts(day: DayFile) -> None:
        day.facts.mood = "excited"
        day.facts.places.append("the library")

    _edit(storage, D1, edit_facts)
    result = indexer.sync()

    rows = _signals(indexer.conn)
    assert {(row["section"], row["field"]) for row in rows} == {
        ("facts", "mood"),
        ("facts", "places"),
    }
    by_field = {row["field"]: row for row in rows}
    assert json.loads(by_field["mood"]["before"]) == "calm"
    assert json.loads(by_field["mood"]["after"]) == "excited"
    assert json.loads(by_field["places"]["after"]) == ["the park", "the library"]
    assert by_field["places"]["diff"] is None
    assert result.edit_signals == 2


def test_format6_owner_edits_become_content_signals(
    indexer: Indexer, storage: LocalStorage
) -> None:
    base = make_day(D1)
    generated = apply_content_generation(
        base,
        content=C.DayContent(
            timeline=C.Timeline(morning=["Ate oatmeal"]),
            pregnancy_baby=C.PregnancyBaby(baby_movement=["one kick"]),
            tags=["weekday"],
        ),
        generated_at=base.meta.generated_at,
        force=True,
    )
    write_day(storage, generated)
    indexer.sync()

    def edit_content(day: DayFile) -> None:
        assert day.content is not None
        day.content.timeline.morning.append("Owner-added walk")
        day.content.pregnancy_baby.baby_movement = ["three kicks"]

    _edit(storage, D1, edit_content)
    result = indexer.sync()

    rows = _signals(indexer.conn)
    assert {(row["section"], row["field"]) for row in rows} == {
        ("content", "timeline"),
        ("content", "pregnancy_baby"),
    }
    timeline = next(row for row in rows if row["field"] == "timeline")
    assert "Owner-added walk" in json.loads(timeline["after"])["morning"]
    assert timeline["diff"] is None
    assert result.edit_signals == 2


def test_signals_are_deduplicated_and_superseded(indexer: Indexer, storage: LocalStorage) -> None:
    write_day(storage, make_day(D1))
    indexer.sync()

    def first(day: DayFile) -> None:
        day.journal = day.journal.replace("Soup.", "Soup and")

    def second(day: DayFile) -> None:
        day.journal = day.journal.replace("Soup and", "Soup and bread.")

    _edit(storage, D1, first)
    indexer.sync()
    path = day_file_path(D1)
    storage.write_text(path, storage.read_text(path))  # same content again
    indexer.sync()
    assert len(_signals(indexer.conn)) == 1

    _edit(storage, D1, second)
    indexer.sync()
    rows = _signals(indexer.conn)
    assert len(rows) == 1
    assert rows[0]["after"].endswith("Soup and bread.")

    def revert(day: DayFile) -> None:
        day.journal = day.journal.replace("Soup and bread.", "Soup.")

    _edit(storage, D1, revert)
    indexer.sync()
    assert _signals(indexer.conn) == []


def test_new_capture_is_not_an_edit(indexer: Indexer, storage: LocalStorage) -> None:
    write_day(storage, make_day(D1))
    indexer.sync()
    at = dt.datetime(2026, 10, 10, 22, 15, tzinfo=TZ)
    note = Capture(id=Capture.make_id("note", at), kind="note", captured_at=at, text="Tea.")
    live = merge_capture(parse(storage.read_text(day_file_path(D1))), note, D1)
    storage.write_text(day_file_path(D1), render(live))  # snapshot not written yet

    indexer.sync()

    assert _signals(indexer.conn) == []


def test_stale_snapshot_is_not_compared(indexer: Indexer, storage: LocalStorage) -> None:
    old = make_day(D1, journal="Old journal.", generated_at=dt.datetime(2026, 10, 10, tzinfo=TZ))
    new = make_day(D1, journal="New journal.")
    storage.write_text(day_file_path(D1), render(new))
    storage.write_text(generated_snapshot_path(D1), render(old))

    indexer.sync()

    assert _signals(indexer.conn) == []


def test_snapshot_change_alone_refreshes_signals(indexer: Indexer, storage: LocalStorage) -> None:
    system = make_day(D1)
    edited = system.model_copy(deep=True)
    edited.notes = "Owner note."
    storage.write_text(day_file_path(D1), render(edited))
    indexer.sync()
    assert _signals(indexer.conn) == []

    storage.write_text(generated_snapshot_path(D1), render(system))
    result = indexer.sync()

    assert result.indexed == 0
    assert result.edit_signals == 1
    assert [r["section"] for r in _signals(indexer.conn)] == ["notes"]


def test_rebuild_keeps_signals_without_duplicates(indexer: Indexer, storage: LocalStorage) -> None:
    write_day(storage, make_day(D1))
    indexer.sync()
    _edit(storage, D1, _owner_edits)
    indexer.sync()
    before = [tuple(r) for r in _signals(indexer.conn)]

    result = indexer.rebuild()

    assert result.edit_signals == 0
    assert [tuple(r) for r in _signals(indexer.conn)] == before
    reset_derived(indexer.conn)
    assert len(_signals(indexer.conn)) == len(before)


def test_deleted_capture_text_is_an_edit() -> None:
    snapshot = make_day(D1)
    live = snapshot.model_copy(deep=True)
    live.captures = []
    changed = [c for c in compare_day(live, snapshot) if c.changed]
    assert [(c.section, c.after) for c in changed] == [("transcript", "")]


def test_text_diff_is_unified() -> None:
    diff = text_diff("a\nb\nc", "a\nB\nc")
    assert diff.splitlines()[:2] == ["--- generated", "+++ edited"]
    assert "-b" in diff and "+B" in diff
