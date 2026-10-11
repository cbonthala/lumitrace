"""``lifelog-indexer run``: a worker thread plus a small HTTP server.

* The worker thread owns the :class:`~lifelog.indexer.core.Indexer` (and its SQLite connection)
  and does all index writes, one at a time. It wakes every ``indexer_poll_interval_seconds`` or
  as soon as a nudge arrives, indexes nudged paths first, then runs an incremental sync (a full
  scan once a day), then a backup if one is due.
* ``POST /nudge`` with ``{"paths": [...]}`` queues the paths and answers ``202`` immediately.
* ``GET /health`` reports the worker state and the last sync summary (counts and paths only).
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lifelog import __version__
from lifelog.indexer.core import Indexer, SyncResult

log = logging.getLogger(__name__)


class NudgeRequest(BaseModel):
    paths: list[str] = Field(default_factory=list)


class IndexerService:
    def __init__(
        self,
        indexer: Indexer,
        *,
        poll_interval: float | None = None,
        debounce: float = 1.0,
    ) -> None:
        self.indexer = indexer
        self.poll_interval = (
            poll_interval
            if poll_interval is not None
            else float(indexer.settings.indexer_poll_interval_seconds)
        )
        self.debounce = debounce
        self._pending: set[str] = set()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.cycles = 0
        self.last_result: SyncResult | None = None
        self.last_cycle_at: dt.datetime | None = None
        self.last_error: str | None = None

    # --- Control ---------------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="lifelog-indexer", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 30.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def nudge(self, paths: Iterable[str] = ()) -> int:
        """Queue paths and wake the worker. Returns the number of paths queued."""
        clean = [p for p in paths if isinstance(p, str) and p.strip()]
        with self._lock:
            self._pending.update(clean)
        self._wake.set()
        return len(clean)

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._pending)

    # --- Work ------------------------------------------------------------------------------

    def run_once(self) -> SyncResult:
        """One cycle: nudged paths, then a sync, then a backup if due."""
        with self._lock:
            paths = sorted(self._pending)
            self._pending.clear()
        if paths:
            self.indexer.index_paths(paths)
        result = self.indexer.sync(full=self.indexer.full_scan_due())
        if self.indexer.backup_due():
            try:
                self.indexer.backup()
            except Exception as exc:
                log.warning("index backup failed (%s); will retry next cycle", type(exc).__name__)
                log.debug("backup error", exc_info=exc)
        self.last_result = result
        return result

    def _loop(self) -> None:
        log.info("indexer worker started (poll every %ss)", self.poll_interval)
        while not self._stop.is_set():
            self._wake.clear()
            try:
                self.run_once()
                self.last_error = None
            except Exception as exc:
                self.last_error = type(exc).__name__
                log.exception("indexer cycle failed; retrying at the next poll or nudge")
            self.cycles += 1
            self.last_cycle_at = dt.datetime.now(dt.UTC)
            self._wake.wait(self.poll_interval)
            if self.debounce and not self._stop.is_set():
                # Let a burst of nudges (day file, snapshot, run record) settle into one cycle.
                self._stop.wait(self.debounce)
        log.info("indexer worker stopped")

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok" if self.running or self._thread is None else "stopped",
            "service": "indexer",
            "version": __version__,
            "worker_running": self.running,
            "cycles": self.cycles,
            "pending_paths": self.pending,
            "last_cycle_at": self.last_cycle_at.isoformat() if self.last_cycle_at else None,
            "last_result": self.last_result.summary() if self.last_result else None,
            "last_error": self.last_error,
        }


def create_app(service: IndexerService, *, manage_worker: bool = True) -> FastAPI:
    """HTTP app for the service. With ``manage_worker`` the worker starts and stops with it."""

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if manage_worker:
            service.start()
        try:
            yield
        finally:
            if manage_worker:
                service.stop()

    app = FastAPI(title="LifeLog Indexer", version=__version__, lifespan=lifespan)
    app.state.service = service

    @app.get("/health")
    def health() -> JSONResponse:
        body = service.health()
        code = status.HTTP_200_OK if body["status"] == "ok" else status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(body, status_code=code)

    @app.post("/nudge", status_code=status.HTTP_202_ACCEPTED)
    def nudge(body: NudgeRequest | None = None) -> dict[str, Any]:
        queued = service.nudge(body.paths if body else [])
        return {"accepted": True, "paths": queued}

    return app


def serve(indexer: Indexer, host: str, port: int, log_level: str = "info") -> None:
    import uvicorn

    service = IndexerService(indexer)
    app = create_app(service)
    uvicorn.run(app, host=host, port=port, log_level=log_level.lower(), log_config=None)
