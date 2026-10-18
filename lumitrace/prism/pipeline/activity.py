"""Activity records: one JSON line per processed capture in ``_system/activity/YYYY/MM.jsonl``.

A record says which models were used, how long and how much each step took,
and what went wrong. It never contains journal content: no transcript, note text, journal, facts
or file contents, and error messages go through :func:`safe_error` first.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, ValidationError

from lumitrace.frames.dayfile import system_path

if TYPE_CHECKING:
    from lumitrace.frames.storage import Storage

log = logging.getLogger(__name__)

ACTIVITY_DIR = "activity"
_MAX_ERROR_CHARS = 200


def safe_error(exc: BaseException) -> str:
    """A short error description that cannot leak journal content.

    Validation and JSON errors echo their input (which would be model output about the owner's
    day), so only their type and size are kept. Other messages are truncated.
    """
    name = type(exc).__name__
    if isinstance(exc, ValidationError):
        return f"{name}: {exc.error_count()} validation error(s)"
    if isinstance(exc, json.JSONDecodeError):
        return f"{name}: invalid JSON at position {exc.pos}"
    message = " ".join(str(exc).split())
    if len(message) > _MAX_ERROR_CHARS:
        message = message[:_MAX_ERROR_CHARS] + "..."
    return f"{name}: {message}" if message else name


def activity_path(when: dt.datetime) -> str:
    """``_system/activity/YYYY/MM.jsonl`` for the month of ``when``."""
    return system_path(ACTIVITY_DIR, f"{when:%Y}", f"{when:%m}.jsonl")


class Step(BaseModel):
    name: str
    """``transcribe``, ``compress_audio``, ``photos``, ``write_day``, ``fill_day``,
    ``update_day``, ``nudge``."""
    ms: int = 0
    ok: bool = True
    model: str | None = None
    cost_usd: float | None = None
    error: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    """Sizes, counts and tool names only; never content."""


class ActivityRecord(BaseModel):
    capture_id: str
    kind: str
    attempt: int = 1
    status: str = "processing"
    """``done`` or ``failed``."""
    entry_date: dt.date | None = None
    received_at: dt.datetime | None = None
    started_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))
    finished_at: dt.datetime | None = None
    generation: str | None = None
    """``deferred`` (saved until the day closes), ``full``, ``additive``, ``skipped`` or
    ``failed``."""
    prompt_version: str | None = None
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    """Unused on new records. Older lines mapped a task to ``v1``, ``v2``, and so on."""
    models: dict[str, str] = Field(default_factory=dict)
    steps: list[Step] = Field(default_factory=list)
    cost_usd: float | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @contextmanager
    def step(self, name: str, *, model: str | None = None) -> Iterator[Step]:
        """Time a step. Exceptions are recorded on the step (and in ``errors``) and re-raised."""
        record = Step(name=name, model=model)
        started = time.monotonic()
        try:
            yield record
        except Exception as exc:
            record.ok = False
            record.error = record.error or safe_error(exc)
            raise
        finally:
            record.ms = int((time.monotonic() - started) * 1000)
            self.steps.append(record)
            if not record.ok and record.error:
                self.errors.append(f"{name}: {record.error}")

    def finish(self, status: str) -> None:
        self.status = status
        self.finished_at = dt.datetime.now(dt.UTC)
        costs = [s.cost_usd for s in self.steps if s.cost_usd is not None]
        self.cost_usd = round(sum(costs), 6) if costs else None


class ActivityLog:
    """Appends records to the monthly JSONL file. Storage has no append, so this is a
    read-modify-write guarded by a lock (the API is the only writer)."""

    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self._lock = threading.Lock()

    def append(self, record: ActivityRecord) -> str | None:
        """Write the record; returns its path, or None if storage failed (never raises)."""
        when = record.finished_at or record.started_at
        path = activity_path(when)
        line = record.model_dump_json(exclude_none=True)
        try:
            with self._lock:
                try:
                    existing = self.storage.read_text(path)
                except FileNotFoundError:
                    existing = ""
                if existing and not existing.endswith("\n"):
                    existing += "\n"
                self.storage.write_text(path, existing + line + "\n")
        except Exception as exc:
            log.error("could not write activity record for %s: %s", record.capture_id, exc)
            return None
        return path
