from __future__ import annotations

import datetime as dt
import json
import sqlite3

from bookshelf.bookmarks.core import META_RETRY_PATHS, Indexer
from bookshelf.books.dayfile import day_file_path, parse, render, system_path
from bookshelf.books.storage.local import LocalStorage
from bookshelf.index.schema import META_SYNC_TOKEN, get_meta
from tests.bookmarks.conftest import RecordingEmbedder, make_day, write_day

D1 = dt.date(2026, 10, 10)
D2 = dt.date(2026, 10, 11)


def _count(conn: sqlite3.Connection, sql: str, *args: object) -> int:
    return int(conn.execute(sql, args).fetchone()[0])


def _fts_dates(conn: sqlite3.Connection, query: str) -> set[str]:
    rows = conn.execute(
        "SELECT p.date FROM passages_fts f JOIN passages p ON p.id = f.rowid"
        " WHERE passages_fts MATCH ?",
        (query,),
    ).fetchall()
    return {r[0] for r in rows}


def test_first_sync_indexes_day_files(
    indexer: Indexer, storage: LocalStorage, sample_day_markdown: str
) -> None:
    storage.write_text(day_file_path(D1), sample_day_markdown)
    write_day(storage, make_day(D2))

    result = indexer.sync()

    assert result.kind == "full-scan"
    assert (result.indexed, result.failed, result.malformed) == (2, [], [])
    conn = indexer.conn
    day = conn.execute("SELECT * FROM days WHERE date = '2026-10-10'").fetchone()
    assert day["mood"] == "happy" and day["mood_score"] == 4 and day["city"] == "Austin"
    assert json.loads(day["audio_json"]) == ["2026-10-10-2130.m4a"]
    assert day["capture_count"] == 3 and day["user_edited"] == 0
    assert day["prompt_version"] == "journal-v1"
    meals = conn.execute(
        "SELECT meal_type, item FROM meals WHERE date = '2026-10-10' ORDER BY position"
    ).fetchall()
    assert [tuple(m) for m in meals][:2] == [("breakfast", "oatmeal"), ("breakfast", "blueberries")]
    assert _count(conn, "SELECT count(*) FROM people WHERE name = 'maya' COLLATE NOCASE") == 1
    assert _count(conn, "SELECT count(*) FROM activities WHERE date = '2026-10-11'") == 1
    assert _count(conn, "SELECT count(*) FROM highlights") == 3

    passages = _count(conn, "SELECT count(*) FROM passages")
    assert passages > 10
    assert _count(conn, "SELECT count(*) FROM passages_vec") == passages
    assert _fts_dates(conn, "tacos") == {"2026-10-10"}
    assert _fts_dates(conn, "heron") == {"2026-10-11"}
    assert get_meta(conn, META_SYNC_TOKEN)

    file_row = conn.execute("SELECT * FROM files WHERE path = ?", (day_file_path(D1),)).fetchone()
    assert file_row["kind"] == "day" and file_row["date"] == "2026-10-10"
    assert len(file_row["content_hash"]) == 64


def test_non_day_files_are_ignored(
    indexer: Indexer, storage: LocalStorage, embedder: RecordingEmbedder
) -> None:
    write_day(storage, make_day(D1))
    storage.write_bytes("2026/10/2026-10-10/2026-10-10-2130.m4a", b"audio")
    storage.write_bytes("2026/10/2026-10-10/photo-01.jpg", b"jpeg")
    storage.write_text("2026/10/2026-10-10/thoughts.md", "---\ndate: 2026-10-10\n---\nhello\n")
    storage.write_text(system_path("runs", "2026", "10", "run.json"), "{}")
    storage.write_text("Inbox.md", "# scratch\n")

    result = indexer.sync()

    assert result.indexed == 1
    paths = [r[0] for r in indexer.conn.execute("SELECT path FROM files")]
    assert paths == [day_file_path(D1)]
    assert not any("hello" in t or "scratch" in t for t in embedder.texts)


def test_unchanged_files_are_skipped(
    indexer: Indexer, storage: LocalStorage, embedder: RecordingEmbedder
) -> None:
    path = write_day(storage, make_day(D1))
    indexer.sync()
    ids = [r[0] for r in indexer.conn.execute("SELECT id FROM passages ORDER BY id")]
    embedder.calls.clear()

    nothing = indexer.sync()
    assert (nothing.kind, nothing.indexed, nothing.skipped) == ("sync", 0, 0)

    storage.write_text(path, storage.read_text(path))  # same content, new mtime
    touched = indexer.sync()
    assert (touched.indexed, touched.skipped) == (0, 1)
    assert [r[0] for r in indexer.conn.execute("SELECT id FROM passages ORDER BY id")] == ids
    assert embedder.calls == []

    again = indexer.sync()
    assert (again.indexed, again.skipped) == (0, 0)


def test_incremental_sync_reembeds_only_changed_passages(
    indexer: Indexer, storage: LocalStorage, embedder: RecordingEmbedder
) -> None:
    write_day(storage, make_day(D1))
    write_day(storage, make_day(D2))
    indexer.sync()
    embedder.calls.clear()

    path = day_file_path(D1)
    day = parse(storage.read_text(path))
    day.notes = "Bought a kite for the weekend."
    storage.write_text(path, render(day))

    result = indexer.sync()

    assert (result.indexed, result.skipped) == (1, 0)
    assert embedder.texts == ["Bought a kite for the weekend."]
    assert _fts_dates(indexer.conn, "kite") == {"2026-10-10"}
    passages = _count(indexer.conn, "SELECT count(*) FROM passages")
    assert _count(indexer.conn, "SELECT count(*) FROM passages_vec") == passages


def test_deleted_day_file_is_removed(indexer: Indexer, storage: LocalStorage) -> None:
    write_day(storage, make_day(D1))
    write_day(storage, make_day(D2, title="Kite day", journal="Flew a kite."))
    indexer.sync()
    feedback_sql = "INSERT INTO feedback(created_at, rating) VALUES ('now', 'good')"
    indexer.conn.execute(feedback_sql)
    indexer.conn.commit()

    storage.delete(day_file_path(D2))
    result = indexer.sync()

    assert result.deleted == 1
    conn = indexer.conn
    assert _count(conn, "SELECT count(*) FROM days WHERE date = '2026-10-11'") == 0
    assert _count(conn, "SELECT count(*) FROM passages WHERE date = '2026-10-11'") == 0
    assert _count(conn, "SELECT count(*) FROM files WHERE date = '2026-10-11'") == 0
    assert _fts_dates(conn, "kite") == set()
    passages = _count(conn, "SELECT count(*) FROM passages")
    assert _count(conn, "SELECT count(*) FROM passages_vec") == passages
    assert _count(conn, "SELECT count(*) FROM days") == 1
    assert _count(conn, "SELECT count(*) FROM feedback") == 1


def test_full_scan_drops_days_whose_files_vanished(indexer: Indexer, storage: LocalStorage) -> None:
    write_day(storage, make_day(D1))
    indexer.sync()
    (storage.root / day_file_path(D1)).unlink()  # a deletion the change feed never reported

    result = indexer.sync(full=True)

    assert result.kind == "full-scan" and result.deleted == 1
    assert _count(indexer.conn, "SELECT count(*) FROM days") == 0


def test_malformed_file_is_logged_and_skipped(
    indexer: Indexer, storage: LocalStorage, caplog
) -> None:
    write_day(storage, make_day(D1))
    bad = day_file_path(D2)
    storage.write_text(bad, "no front matter here, just a secret thought\n")

    result = indexer.sync()

    assert result.indexed == 1
    assert result.malformed == [bad]
    assert result.failed == []
    assert "secret thought" not in caplog.text
    assert bad in caplog.text
    assert _count(indexer.conn, "SELECT count(*) FROM days") == 1
    assert _count(indexer.conn, "SELECT count(*) FROM files WHERE path = ?", bad) == 1

    again = indexer.sync()
    assert again.malformed == [] and again.indexed == 0

    write_day(storage, make_day(D2))
    fixed = indexer.sync()
    assert fixed.indexed == 1
    assert _count(indexer.conn, "SELECT count(*) FROM days") == 2


def test_broken_edit_keeps_last_good_index(indexer: Indexer, storage: LocalStorage) -> None:
    path = write_day(storage, make_day(D1, journal="Picnic by the lake."))
    indexer.sync()
    storage.write_text(path, "---\ndate: [unclosed\n---\n")

    result = indexer.sync()

    assert result.malformed == [path]
    assert _fts_dates(indexer.conn, "picnic") == {"2026-10-10"}


def test_front_matter_date_mismatch_uses_folder_date(
    indexer: Indexer, storage: LocalStorage
) -> None:
    copied = render(make_day(D1))
    storage.write_text(day_file_path(D2), copied)

    result = indexer.sync()

    assert result.indexed == 1
    assert [r[0] for r in indexer.conn.execute("SELECT date FROM days")] == ["2026-10-11"]


def test_transient_failure_is_retried(
    indexer: Indexer, storage: LocalStorage, embedder: RecordingEmbedder
) -> None:
    path = write_day(storage, make_day(D1))
    embedder.fail_next = 1

    failed = indexer.sync()
    assert failed.failed == [path]
    assert json.loads(get_meta(indexer.conn, META_RETRY_PATHS) or "[]") == [path]

    retried = indexer.sync()  # storage reports nothing new; the retry list brings it back
    assert retried.indexed == 1 and retried.failed == []
    assert json.loads(get_meta(indexer.conn, META_RETRY_PATHS) or "[]") == []


def test_index_paths_handles_nudged_paths(indexer: Indexer, storage: LocalStorage) -> None:
    path = write_day(storage, make_day(D1))

    result = indexer.index_paths([path, "../etc/passwd", "2026/10/2026-10-10/photo-01.jpg"])
    assert result.indexed == 1
    assert _count(indexer.conn, "SELECT count(*) FROM days") == 1

    again = indexer.index_paths([path])
    assert again.indexed == 0 and again.skipped == 1

    storage.delete(path)
    gone = indexer.index_paths([path])
    assert gone.deleted == 1
    assert _count(indexer.conn, "SELECT count(*) FROM days") == 0


def test_bad_sync_token_falls_back_to_full_scan(indexer: Indexer, storage: LocalStorage) -> None:
    write_day(storage, make_day(D1))
    from bookshelf.index.schema import set_meta

    with indexer.conn:
        set_meta(indexer.conn, META_SYNC_TOKEN, "gdrive-token-from-another-backend")

    result = indexer.sync()

    assert result.kind == "full-scan" and result.indexed == 1
