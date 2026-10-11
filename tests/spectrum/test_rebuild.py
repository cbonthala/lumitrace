from __future__ import annotations

import datetime as dt

from lumen.config import Settings
from lumen.frames.dayfile import day_file_path
from lumen.frames.storage.local import LocalStorage
from lumen.index.schema import (
    META_EMBEDDING_DIMENSION,
    META_EMBEDDING_MODEL,
    META_LAST_REBUILD_AT,
    META_SCHEMA_VERSION,
    META_SYNC_TOKEN,
    SCHEMA_VERSION,
    connect,
    get_meta,
    serialize_embedding,
    set_meta,
)
from lumen.spectrum.core import Indexer
from tests.spectrum.conftest import make_day, write_day

D1 = dt.date(2026, 10, 10)
D2 = dt.date(2026, 10, 11)


def _count(indexer: Indexer, table: str) -> int:
    return int(indexer.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def test_rebuild_reindexes_everything_and_keeps_signals(
    indexer: Indexer, storage: LocalStorage
) -> None:
    write_day(storage, make_day(D1))
    write_day(storage, make_day(D2))
    indexer.sync()
    passages = _count(indexer, "passages")
    with indexer.conn:
        indexer.conn.execute("INSERT INTO feedback(created_at, rating) VALUES ('now', 'wrong')")
        indexer.conn.execute(
            "INSERT INTO edit_signals(date, path, detected_at, section, signal_hash)"
            " VALUES ('2026-01-01', 'p', 'now', 'journal', 'h')"
        )
        indexer.conn.execute("DELETE FROM passages")  # simulate a damaged index

    result = indexer.rebuild()

    assert result.kind == "rebuild" and result.indexed == 2
    assert _count(indexer, "passages") == passages
    assert _count(indexer, "passages_vec") == passages
    assert _count(indexer, "days") == 2
    assert _count(indexer, "feedback") == 1
    assert _count(indexer, "edit_signals") == 1
    assert get_meta(indexer.conn, META_LAST_REBUILD_AT)
    assert get_meta(indexer.conn, META_SYNC_TOKEN)


def test_dimension_change_triggers_rebuild(settings: Settings, storage: LocalStorage) -> None:
    write_day(storage, make_day(D1))
    first = Indexer(settings, storage)
    first.sync()
    with first.conn:
        first.conn.execute("INSERT INTO feedback(created_at, rating) VALUES ('now', 'good')")
    first.close()

    smaller = settings.model_copy(update={"embedding_dimension": 32})
    second = Indexer(smaller, storage)
    assert second.rebuild_reason and "dimension" in second.rebuild_reason

    result = second.sync()

    assert result.kind == "rebuild" and result.indexed == 1
    assert get_meta(second.conn, META_EMBEDDING_DIMENSION) == "32"
    assert second.rebuild_reason is None
    near = second.conn.execute(
        "SELECT rowid FROM passages_vec WHERE embedding MATCH ? AND k = 1",
        (serialize_embedding([0.1] * 32),),
    ).fetchall()
    assert len(near) == 1
    assert int(second.conn.execute("SELECT count(*) FROM feedback").fetchone()[0]) == 1
    second.close()
    connect(smaller.index_path, 32).close()  # the MCP server can open it with new settings


def test_model_change_triggers_rebuild(settings: Settings, storage: LocalStorage) -> None:
    write_day(storage, make_day(D1))
    first = Indexer(settings, storage)
    first.sync()
    with first.conn:
        set_meta(first.conn, META_EMBEDDING_MODEL, "openai/some-older-model")
    first.close()

    second = Indexer(settings, storage)
    assert second.rebuild_reason and "some-older-model" in second.rebuild_reason
    result = second.sync()
    assert result.kind == "rebuild"
    assert get_meta(second.conn, META_EMBEDDING_MODEL) == "fake"
    second.close()


def test_older_schema_version_triggers_rebuild(
    settings: Settings, storage: LocalStorage, sample_day_v1_markdown: str
) -> None:
    storage.write_text(day_file_path(D1), sample_day_v1_markdown)
    first = Indexer(settings, storage)
    first.sync()
    with first.conn:
        set_meta(first.conn, META_SCHEMA_VERSION, "1")
        first.conn.execute("DELETE FROM people")  # stands in for rows an old version left out
        first.conn.execute("INSERT INTO feedback(created_at, rating) VALUES ('now', 'good')")
    first.close()

    second = Indexer(settings, storage)
    assert second.rebuild_reason and "schema version 1" in second.rebuild_reason
    result = second.sync()

    assert result.kind == "rebuild" and result.indexed == 1
    assert get_meta(second.conn, META_SCHEMA_VERSION) == str(SCHEMA_VERSION)
    assert _count(second, "people") == 2
    assert _count(second, "feedback") == 1
    second.close()
    third = Indexer(settings, storage)
    assert third.rebuild_reason is None
    third.close()


def test_rebuild_on_empty_storage(indexer: Indexer) -> None:
    result = indexer.rebuild()
    assert (result.indexed, result.failed) == (0, [])
    assert get_meta(indexer.conn, META_EMBEDDING_MODEL) == "fake"
