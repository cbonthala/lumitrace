"""Regenerate past days through the same path as the Flash Generate button.

``lumitrace-prism regenerate`` walks stored day files and calls
:meth:`lumitrace.prism.pipeline.processor.CaptureProcessor.generate_day`. The first generation
fills the day. Later generations use the safe journal update and the three-way facts merge,
including days the owner edited. Notes, transcripts, audio and photos are never touched.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from lumitrace.config import Settings
from lumitrace.frames.dayfile import parse_day_file_path
from lumitrace.frames.storage import Storage
from lumitrace.prism.pipeline.generate import Generator
from lumitrace.prism.pipeline.processor import CaptureProcessor

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DayOutcome:
    """What happened to one day. ``status`` is ``full``, ``update``, ``unchanged``, ``skipped``
    or ``failed``. A dry run uses ``would full`` or ``would update`` and writes nothing."""

    date: dt.date
    status: str
    detail: str = ""


def regenerate_days(
    settings: Settings,
    storage: Storage,
    generator: Generator,
    *,
    start: dt.date | None = None,
    end: dt.date | None = None,
    dry_run: bool = False,
    nudge: bool = False,
    on_outcome: Callable[[DayOutcome], None] | None = None,
) -> list[DayOutcome]:
    """Regenerate every day file in ``[start, end]`` (inclusive; omit either end for no limit).

    This is the Flash Generate button, applied to a date range. ``nudge`` asks Spectrum to
    index each written day, the same way a button click does.
    """
    processor = CaptureProcessor(settings, storage, llm=generator.llm)
    outcomes: list[DayOutcome] = []

    def done(outcome: DayOutcome) -> None:
        outcomes.append(outcome)
        if on_outcome is not None:
            on_outcome(outcome)

    for day in _days(storage, start, end):
        mode = processor.generation_mode(day)
        if dry_run:
            status = mode if mode in ("skipped", "unchanged") else f"would {mode}"
            done(DayOutcome(day, status))
            continue
        try:
            status = processor.generate_day(day, nudge=nudge)
        except Exception as exc:
            log.warning("regenerate %s failed: %s", day, type(exc).__name__)
            done(DayOutcome(day, "failed", type(exc).__name__))
            continue
        done(DayOutcome(day, status))
    return outcomes


def _days(storage: Storage, start: dt.date | None, end: dt.date | None) -> Iterator[dt.date]:
    found: list[dt.date] = []
    for info in storage.list(""):
        day = parse_day_file_path(info.path)
        if day is None:
            continue
        if (start is not None and day < start) or (end is not None and day > end):
            continue
        found.append(day)
    yield from sorted(found)
