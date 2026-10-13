from __future__ import annotations

import datetime as dt
import time

from fastapi.testclient import TestClient

from lumitrace.config import Settings
from lumitrace.frames.storage.local import LocalStorage
from lumitrace.index.schema import connect
from lumitrace.spectrum.core import Indexer
from lumitrace.spectrum.service import IndexerService, create_app
from tests.spectrum.conftest import make_day, write_day

D1 = dt.date(2026, 10, 10)


def _wait_for(predicate, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_health_and_nudge_queue(indexer: Indexer) -> None:
    service = IndexerService(indexer, poll_interval=3600, debounce=0)
    client = TestClient(create_app(service, manage_worker=False))

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["service"] == "indexer"
    assert health.json()["status"] == "ok"

    resp = client.post("/nudge", json={"paths": ["2026/10/2026-10-10/2026-10-10.md"]})
    assert resp.status_code == 202
    assert resp.json() == {"accepted": True, "paths": 1}
    assert client.post("/nudge", json={"paths": []}).status_code == 202
    assert client.post("/nudge").status_code == 202
    assert service.pending == 1
    assert client.get("/health").json()["pending_paths"] == 1

    assert client.post("/nudge", json={"paths": "not-a-list"}).status_code == 422


def test_run_once_indexes_nudged_paths(indexer: Indexer, storage: LocalStorage) -> None:
    service = IndexerService(indexer, poll_interval=3600, debounce=0)
    path = write_day(storage, make_day(D1))
    service.nudge([path])

    result = service.run_once()

    assert service.pending == 0
    assert indexer.conn.execute("SELECT count(*) FROM days").fetchone()[0] == 1
    assert result.skipped == 1  # the sync after the nudge finds it already indexed


def test_worker_indexes_promptly_after_nudge(
    settings: Settings, indexer: Indexer, storage: LocalStorage
) -> None:
    service = IndexerService(indexer, poll_interval=3600, debounce=0)
    reader = connect(settings.index_path, settings.embedding_dimension)

    def indexed() -> bool:
        return reader.execute("SELECT count(*) FROM days").fetchone()[0] == 1

    with TestClient(create_app(service)) as client:
        assert _wait_for(lambda: service.cycles >= 1)
        assert not indexed()
        path = write_day(storage, make_day(D1))

        assert client.post("/nudge", json={"paths": [path]}).status_code == 202

        assert _wait_for(indexed)
        body = client.get("/health").json()
        assert body["worker_running"] is True
        assert body["last_error"] is None
    assert not service.running
    reader.close()
