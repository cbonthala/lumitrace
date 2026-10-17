from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from lumitrace.index import schema as S


def _add_file(conn: sqlite3.Connection, path: str = "2026/10/2026-10-10/2026-10-10.md") -> None:
    conn.execute(
        "INSERT INTO files(path, kind, date, content_hash, indexed_at)"
        " VALUES (?, 'day', ?, 'h', 'now')",
        (path, "2026-10-10"),
    )


def _add_passage(
    conn: sqlite3.Connection, text: str, path: str = "2026/10/2026-10-10/2026-10-10.md"
) -> int:
    cur = conn.execute(
        "INSERT INTO passages(path, date, section, text, text_hash)"
        " VALUES (?, '2026-10-10', 'journal', ?, 'x')",
        (path, text),
    )
    return int(cur.lastrowid)


def test_sqlite_vec_loads_on_this_machine() -> None:
    conn = S.connect(":memory:", 4)
    version = conn.execute("SELECT vec_version()").fetchone()[0]
    assert version.startswith("v")


def test_schema_tables_exist(tmp_path: Path) -> None:
    conn = S.connect(tmp_path / "sub" / "index.sqlite", 8, embedding_model="fake")
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    for table in [*S.DERIVED_TABLES, *S.PRESERVED_TABLES, "meta"]:
        assert table in names
    assert S.get_meta(conn, S.META_SCHEMA_VERSION) == str(S.SCHEMA_VERSION)
    assert S.get_meta(conn, S.META_EMBEDDING_DIMENSION) == "8"
    assert S.get_meta(conn, S.META_EMBEDDING_MODEL) == "fake"
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_connect_is_idempotent_and_checks_dimension(tmp_path: Path) -> None:
    path = tmp_path / "index.sqlite"
    S.connect(path, 8).close()
    S.connect(path, 8).close()
    with pytest.raises(S.EmbeddingDimensionMismatch):
        S.connect(path, 16)
    ro = S.connect(path, 8, read_only=True)
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("INSERT INTO meta(key, value) VALUES ('x', 'y')")


def test_fts_and_vector_search_and_cascade() -> None:
    conn = S.connect(":memory:", 4)
    _add_file(conn)
    pid = _add_passage(conn, "We ate pancakes with Maya by the river")
    other = _add_passage(conn, "Quiet evening reading")
    conn.execute(
        "INSERT INTO passages_vec(rowid, embedding) VALUES (?, ?), (?, ?)",
        (pid, S.serialize_embedding([1, 0, 0, 0]), other, S.serialize_embedding([0, 1, 0, 0])),
    )
    hits = conn.execute(
        "SELECT rowid FROM passages_fts WHERE passages_fts MATCH ?", ("pancake",)
    ).fetchall()
    assert [h[0] for h in hits] == [pid]

    near = conn.execute(
        "SELECT rowid, distance FROM passages_vec"
        " WHERE embedding MATCH ? AND k = 2 ORDER BY distance",
        (S.serialize_embedding([0.9, 0.1, 0, 0]),),
    ).fetchall()
    assert near[0][0] == pid
    assert near[0][1] < near[1][1]

    conn.execute("UPDATE passages SET text = 'waffles instead' WHERE id = ?", (pid,))
    assert not conn.execute(
        "SELECT 1 FROM passages_fts WHERE passages_fts MATCH 'pancake'"
    ).fetchall()
    assert conn.execute("SELECT 1 FROM passages_fts WHERE passages_fts MATCH 'waffle'").fetchall()

    conn.execute("DELETE FROM files")
    assert conn.execute("SELECT count(*) FROM passages").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM passages_vec").fetchone()[0] == 0
    assert not conn.execute(
        "SELECT 1 FROM passages_fts WHERE passages_fts MATCH 'reading'"
    ).fetchall()


def test_fact_tables_cascade_from_days() -> None:
    conn = S.connect(":memory:", 4)
    conn.execute("INSERT INTO days(date, path) VALUES ('2026-10-10', 'p')")
    conn.execute("INSERT INTO meals(date, meal_type, item) VALUES ('2026-10-10', 'lunch', 'tacos')")
    conn.execute("INSERT INTO activities(date, kind, minutes) VALUES ('2026-10-10', 'run', 40)")
    conn.execute("INSERT INTO people(date, name) VALUES ('2026-10-10', 'Maya')")
    conn.execute("INSERT INTO places(date, name) VALUES ('2026-10-10', 'the lake')")
    conn.execute(
        "INSERT INTO family_facts(date, person, category, text)"
        " VALUES ('2026-10-10', 'Leo', 'moments', 'tooth')"
    )
    conn.execute("INSERT INTO highlights(date, text) VALUES ('2026-10-10', 'book')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO meals(date, meal_type, item) VALUES ('1999-01-01', 'x', 'y')")
    conn.execute("DELETE FROM days")
    for table in ["meals", "activities", "people", "places", "family_facts", "highlights"]:
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_edit_signals_dedupe_by_hash() -> None:
    conn = S.connect(":memory:", 4)
    sql = (
        "INSERT OR IGNORE INTO edit_signals(date, path, detected_at, section, field, before, after,"
        " signal_hash) VALUES ('2026-10-10', 'p', 'now', 'facts', 'mood', 'happy', 'great', 'h1')"
    )
    conn.execute(sql)
    conn.execute(sql)
    assert conn.execute("SELECT count(*) FROM edit_signals").fetchone()[0] == 1


def test_reset_derived_keeps_signals_and_feedback() -> None:
    conn = S.connect(":memory:", 4)
    _add_file(conn)
    pid = _add_passage(conn, "pancakes")
    conn.execute(
        "INSERT INTO passages_vec(rowid, embedding) VALUES (?, ?)",
        (pid, S.serialize_embedding([1, 0, 0, 0])),
    )
    conn.execute("INSERT INTO days(date, path) VALUES ('2026-10-10', 'p')")
    conn.execute("INSERT INTO feedback(created_at, rating, question) VALUES ('now', 'wrong', 'q')")
    conn.execute(
        "INSERT INTO edit_signals(date, path, detected_at, section, signal_hash)"
        " VALUES ('2026-10-10', 'p', 'now', 'journal', 'h')"
    )
    S.set_meta(conn, S.META_SYNC_TOKEN, "tok")

    S.reset_derived(conn, embedding_dimension=8, embedding_model="new-model")

    for table in ["files", "passages", "passages_vec", "days"]:
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert not conn.execute(
        "SELECT 1 FROM passages_fts WHERE passages_fts MATCH 'pancakes'"
    ).fetchall()
    assert conn.execute("SELECT count(*) FROM feedback").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM edit_signals").fetchone()[0] == 1
    assert S.get_meta(conn, S.META_SYNC_TOKEN) is None
    assert S.get_meta(conn, S.META_EMBEDDING_DIMENSION) == "8"
    assert S.get_meta(conn, S.META_EMBEDDING_MODEL) == "new-model"
    conn.execute(
        "INSERT INTO passages_vec(rowid, embedding) VALUES (1, ?)",
        (S.serialize_embedding([0.0] * 8),),
    )


def test_invalid_dimension() -> None:
    with pytest.raises(ValueError):
        S.connect(":memory:", 0)


def test_reset_derived_gives_old_fact_tables_the_current_columns(tmp_path: Path) -> None:
    path = tmp_path / "index.sqlite"
    conn = S.connect(path, 4)
    with conn:  # an index made by schema version 2: no meals.person, no days.remember
        conn.execute("DROP TABLE meals")
        conn.execute(
            "CREATE TABLE meals (id INTEGER PRIMARY KEY, date TEXT NOT NULL REFERENCES"
            " days(date) ON DELETE CASCADE, meal_type TEXT NOT NULL, item TEXT NOT NULL,"
            " position INTEGER NOT NULL DEFAULT 0)"
        )
    columns = {r[1] for r in conn.execute("PRAGMA table_info(meals)")}
    assert "person" not in columns
    S.reset_derived(conn)
    assert "person" in {r[1] for r in conn.execute("PRAGMA table_info(meals)")}
    assert "remember" in {r[1] for r in conn.execute("PRAGMA table_info(days)")}
    with conn:
        conn.execute("INSERT INTO days(date, path) VALUES ('2026-10-10', 'p')")
        conn.execute(
            "INSERT INTO meals(date, person, meal_type, item) VALUES"
            " ('2026-10-10', 'Leo', 'dinner', 'pasta')"
        )
