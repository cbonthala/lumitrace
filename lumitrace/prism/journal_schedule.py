"""Write the day's journal once, five minutes after the day rollover.

The Prism starts this with the capture worker (ADR 0046). On start, and again at each
rollover-plus-five-minutes (4:05 a.m. when ``LUMITRACE_DAY_ROLLOVER_HOUR`` is 4), it writes every
closed day that still has transcripts waiting. It waits until the capture worker is idle first,
so a recording from just before the rollover is included.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lumitrace.prism.pipeline.processor import CaptureProcessor
    from lumitrace.prism.worker import CaptureWorker

log = logging.getLogger(__name__)

JOURNAL_DELAY = dt.timedelta(minutes=5)
"""How long after the rollover hour the journal is written. Five minutes lets a 3:50 a.m.
recording finish uploading before the day is closed and written."""


def next_journal_at(
    now: dt.datetime,
    tz: dt.tzinfo,
    rollover_hour: int,
    delay: dt.timedelta = JOURNAL_DELAY,
) -> dt.datetime:
    """The next local time the journal should be written, strictly after ``now`` when ``now``
    is already on a run time."""
    local = now.astimezone(tz)
    run = local.replace(hour=rollover_hour, minute=0, second=0, microsecond=0) + delay
    if local >= run:
        run += dt.timedelta(days=1)
    return run


class JournalScheduler:
    def __init__(
        self,
        processor: CaptureProcessor,
        worker: CaptureWorker,
        *,
        idle_timeout: float = 600.0,
    ) -> None:
        self.processor = processor
        self.worker = worker
        self.idle_timeout = idle_timeout
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="prism-journal", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 30.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def run_due(self) -> list[tuple[dt.date, str]]:
        """Write journals for closed days. Waits until no capture is being processed."""
        self.worker.wait_idle(self.idle_timeout)
        if self._stop.is_set():
            return []
        outcomes = self.processor.generate_pending()
        if outcomes:
            log.info("journal: %s", ", ".join(f"{day} {status}" for day, status in outcomes))
        return outcomes

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_due()
            except Exception:
                log.exception("journal run failed")
            if self._stop.is_set():
                return
            settings = self.processor.settings
            nxt = next_journal_at(self.processor._now(), settings.tz, settings.day_rollover_hour)
            wait = (nxt - self.processor._now()).total_seconds()
            if self._stop.wait(max(wait, 0.0)):
                return
