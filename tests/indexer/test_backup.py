from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from lifelog.index.schema import load_sqlite_vec
from lifelog.indexer.backup import BACKUP_PATH
from lifelog.indexer.core import Indexer
from lifelog.indexer.service import IndexerService
from lifelog.storage.local import LocalStorage
from tests.indexer.conftest import make_day, write_day

D1 = dt.date(2026, 10, 10)


def test_backup_writes_a_consistent_copy_to_storage(
    indexer: Indexer, storage: LocalStorage, tmp_path: Path
) -> None:
    write_day(storage, make_day(D1))
    indexer.sync()

    info = indexer.backup()

    assert info.path == BACKUP_PATH == "_system/index-backup/lifelog.sqlite"
    copy = tmp_path / "restored.sqlite"
    copy.write_bytes(storage.read_bytes(BACKUP_PATH))
    conn = sqlite3.connect(copy)
    load_sqlite_vec(conn)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert conn.execute("SELECT date FROM days").fetchall() == [("2026-10-10",)]
    passages = conn.execute("SELECT count(*) FROM passages").fetchone()[0]
    assert conn.execute("SELECT count(*) FROM passages_vec").fetchone()[0] == passages > 0
    conn.close()


def test_backup_is_due_by_interval(indexer: Indexer) -> None:
    assert indexer.backup_due()
    indexer.backup()
    now = dt.datetime.now(dt.UTC)
    assert not indexer.backup_due(now)
    assert indexer.backup_due(now + dt.timedelta(hours=25))

    indexer.settings = indexer.settings.model_copy(update={"indexer_backup_interval_hours": 0})
    assert not indexer.backup_due(now + dt.timedelta(days=30))


def test_backup_is_not_indexed(indexer: Indexer, storage: LocalStorage) -> None:
    write_day(storage, make_day(D1))
    indexer.sync()
    indexer.backup()
    result = indexer.sync()
    assert (result.indexed, result.skipped, result.failed) == (0, 0, [])


def test_service_cycle_backs_up_when_due(indexer: Indexer, storage: LocalStorage) -> None:
    service = IndexerService(indexer, poll_interval=3600, debounce=0)
    service.run_once()
    assert storage.exists(BACKUP_PATH)
    first = storage.stat(BACKUP_PATH).modified

    service.run_once()
    assert storage.stat(BACKUP_PATH).modified == first
