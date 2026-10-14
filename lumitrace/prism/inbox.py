"""Durable inbox and capture status, both kept in storage under ``_system/``.

* ``_system/inbox/<capture id>/``: the raw upload (``audio.<ext>``, ``photo-NN.<ext>``) and
  ``manifest.json`` (a :class:`~lumitrace.prism.pipeline.processor.CaptureRequest`). The
  manifest is written last, so a folder without one is an interrupted upload and is ignored. The
  folder is deleted once the capture is processed; failed captures stay until retried.
* ``_system/captures/<capture id>.json``: a :class:`CaptureStatus`, kept after processing so
  ``GET /captures/{id}`` and idempotent retries keep working. No journal content.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import threading
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from lumitrace.frames.dayfile import CaptureKind, system_path
from lumitrace.prism.pipeline.processor import CaptureRequest

if TYPE_CHECKING:
    from lumitrace.frames.storage import Storage

log = logging.getLogger(__name__)

INBOX_DIR = "inbox"
STATUS_DIR = "captures"
MANIFEST = "manifest.json"
CAPTURE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

State = Literal["queued", "processing", "done", "failed"]


def inbox_dir(capture_id: str) -> str:
    return system_path(INBOX_DIR, capture_id)


def status_path(capture_id: str) -> str:
    return system_path(STATUS_DIR, f"{capture_id}.json")


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class CaptureStatus(BaseModel):
    capture_id: str
    kind: CaptureKind
    status: State
    entry_date: dt.date
    captured_at: dt.datetime
    received_at: dt.datetime
    updated_at: dt.datetime = Field(default_factory=now_utc)
    attempts: int = 0
    retry_at: dt.datetime | None = None
    """Set while an automatic retry is scheduled (status stays ``queued``)."""
    day_file: str | None = None
    audio: str | None = None
    photos: list[str] = Field(default_factory=list)
    generation: str | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Inbox:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self._cache: dict[str, CaptureStatus] = {}
        self._lock = threading.Lock()
        self._id_locks: dict[str, threading.Lock] = {}

    def id_lock(self, capture_id: str) -> threading.Lock:
        """Serialises accept/retry decisions for one capture id."""
        with self._lock:
            return self._id_locks.setdefault(capture_id, threading.Lock())

    # --- payload ------------------------------------------------------------------------

    def save(self, req: CaptureRequest, files: dict[str, bytes]) -> None:
        """Write the payload files (keys are paths from ``req``), then the manifest."""
        for path, data in files.items():
            self.storage.write_bytes(path, data)
        self.storage.write_text(
            f"{inbox_dir(req.id)}/{MANIFEST}", req.model_dump_json(indent=2) + "\n"
        )

    def load(self, capture_id: str) -> CaptureRequest:
        """The manifest. Raises ``FileNotFoundError`` if the capture is not in the inbox."""
        raw = self.storage.read_text(f"{inbox_dir(capture_id)}/{MANIFEST}")
        return CaptureRequest.model_validate_json(raw)

    def has_payload(self, capture_id: str) -> bool:
        return self.storage.exists(f"{inbox_dir(capture_id)}/{MANIFEST}")

    def pending_ids(self) -> list[str]:
        """Ids of complete uploads still in the inbox, oldest first by manifest time."""
        prefix = system_path(INBOX_DIR) + "/"
        manifests = [
            f
            for f in self.storage.list(system_path(INBOX_DIR))
            if f.path.endswith("/" + MANIFEST) and f.path.count("/") == prefix.count("/") + 1
        ]
        manifests.sort(key=lambda f: f.modified)
        return [f.path[len(prefix) :].split("/", 1)[0] for f in manifests]

    def remove(self, capture_id: str) -> None:
        for info in self.storage.list(inbox_dir(capture_id)):
            if info.path.endswith("/" + MANIFEST):
                continue
            self.storage.delete(info.path, missing_ok=True)
        self.storage.delete(f"{inbox_dir(capture_id)}/{MANIFEST}", missing_ok=True)

    # --- status -------------------------------------------------------------------------

    def get_status(self, capture_id: str) -> CaptureStatus | None:
        with self._lock:
            cached = self._cache.get(capture_id)
        if cached is not None:
            return cached.model_copy(deep=True)
        try:
            raw = self.storage.read_text(status_path(capture_id))
        except FileNotFoundError:
            return None
        status = CaptureStatus.model_validate_json(raw)
        with self._lock:
            self._cache[capture_id] = status
        return status.model_copy(deep=True)

    def recent_statuses(self, since: dt.datetime, limit: int) -> list[CaptureStatus]:
        """Statuses changed since ``since`` (by file time), newest capture first."""
        found: list[CaptureStatus] = []
        for info in self.storage.list(system_path(STATUS_DIR)):
            name = info.path.rsplit("/", 1)[-1]
            if info.modified < since or not name.endswith(".json"):
                continue
            try:
                status = self.get_status(name.removesuffix(".json"))
            except ValueError:
                log.warning("unreadable capture status %s", info.path)
                continue
            if status is not None:
                found.append(status)
        found.sort(key=lambda s: s.captured_at, reverse=True)
        return found[:limit]

    def put_status(self, status: CaptureStatus) -> None:
        status.updated_at = now_utc()
        self.storage.write_text(
            status_path(status.capture_id), status.model_dump_json(indent=2) + "\n"
        )
        with self._lock:
            self._cache[status.capture_id] = status.model_copy(deep=True)
