"""Background worker: processes inbox captures one at a time, in arrival order.

One thread is enough for one person's journal, and processing sequentially means two captures
for the same day never race on the day file. Failed captures are retried automatically after
``retry_delays`` (then left as ``failed`` in the inbox for a manual ``POST
/captures/{id}/retry``). On start-up :meth:`CaptureWorker.resume` re-queues everything left in
the inbox by a restart or crash.
"""

from __future__ import annotations

import datetime as dt
import logging
import queue
import threading
from collections.abc import Sequence

from lumitrace.prism.inbox import CaptureStatus, Inbox, now_utc
from lumitrace.prism.pipeline.activity import safe_error
from lumitrace.prism.pipeline.processor import CaptureProcessor

log = logging.getLogger(__name__)

DEFAULT_RETRY_DELAYS: tuple[float, ...] = (60.0, 600.0)


class CaptureWorker:
    def __init__(
        self,
        processor: CaptureProcessor,
        inbox: Inbox,
        *,
        retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS,
    ) -> None:
        self.processor = processor
        self.inbox = inbox
        self.retry_delays = tuple(retry_delays)
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._timers: set[threading.Timer] = set()
        self._pending = 0
        self._cond = threading.Condition()
        self._stopping = False

    @property
    def max_attempts(self) -> int:
        return len(self.retry_delays) + 1

    # --- lifecycle ----------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stopping = False
        self._thread = threading.Thread(target=self._run, name="prism-capture-worker")
        self._thread.daemon = True
        self._thread.start()

    def stop(self, timeout: float = 30.0) -> None:
        """Finish the capture in progress, then stop. Queued ones resume on next start."""
        self._stopping = True
        with self._cond:
            for timer in self._timers:
                timer.cancel()
            self._timers.clear()
        if self._thread is not None:
            self._queue.put(None)
            self._thread.join(timeout)
            self._thread = None

    def submit(self, capture_id: str) -> None:
        with self._cond:
            self._pending += 1
        self._queue.put(capture_id)

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Block until nothing is queued or running (scheduled retries don't count)."""
        with self._cond:
            return self._cond.wait_for(lambda: self._pending == 0, timeout)

    def resume(self) -> int:
        """Queue every unfinished capture found in the inbox. Returns how many."""
        count = 0
        for capture_id in self.inbox.pending_ids():
            try:
                status = self.inbox.get_status(capture_id)
                if status is None:
                    req = self.inbox.load(capture_id)
                    status = CaptureStatus(
                        capture_id=req.id,
                        kind=req.kind,
                        status="queued",
                        entry_date=self.processor.entry_date_of(req),
                        captured_at=req.captured_at,
                        received_at=req.received_at,
                    )
                    self.inbox.put_status(status)
                if status.status == "done":
                    self.inbox.remove(capture_id)
                    continue
                if status.status == "failed":
                    continue
                if status.status == "processing" or status.retry_at is not None:
                    status.status = "queued"
                    status.retry_at = None
                    self.inbox.put_status(status)
                self.submit(capture_id)
                count += 1
            except Exception as exc:
                log.error("could not resume capture %s: %s", capture_id, safe_error(exc))
        if count:
            log.info("resumed %d capture(s) from the inbox", count)
        return count

    # --- processing ---------------------------------------------------------------------

    def _run(self) -> None:
        while True:
            capture_id = self._queue.get()
            if capture_id is None:
                return
            try:
                self._handle(capture_id)
            except Exception:
                log.exception("unexpected error handling capture %s", capture_id)
            finally:
                with self._cond:
                    self._pending -= 1
                    self._cond.notify_all()

    def _handle(self, capture_id: str) -> None:
        status = self.inbox.get_status(capture_id)
        if status is None or status.status in ("done", "processing"):
            return
        try:
            req = self.inbox.load(capture_id)
        except FileNotFoundError:
            status.status = "failed"
            status.errors = ["the upload is no longer in the inbox; send the capture again"]
            self.inbox.put_status(status)
            return
        status.status = "processing"
        status.attempts += 1
        status.retry_at = None
        self.inbox.put_status(status)
        try:
            result = self.processor.process(req, attempt=status.attempts)
        except Exception as exc:
            log.warning("capture %s failed (attempt %d)", capture_id, status.attempts)
            status.errors = [safe_error(exc)]
            self._fail_or_retry(status)
            return
        status.status = "done"
        status.entry_date = result.entry_date
        status.day_file = result.day_file
        status.audio = result.audio
        status.photos = result.photos
        status.generation = result.generation
        status.errors = result.errors
        status.warnings = result.warnings
        self.inbox.put_status(status)
        try:
            self.inbox.remove(capture_id)
        except Exception as exc:
            log.warning("could not clean inbox for %s: %s", capture_id, safe_error(exc))

    def _fail_or_retry(self, status: CaptureStatus) -> None:
        if self._stopping or status.attempts >= self.max_attempts:
            status.status = "queued" if self._stopping else "failed"
            self.inbox.put_status(status)
            return
        delay = self.retry_delays[status.attempts - 1]
        status.status = "queued"
        status.retry_at = now_utc() + dt.timedelta(seconds=delay)
        self.inbox.put_status(status)

        def fire(timer_ref: list[threading.Timer]) -> None:
            with self._cond:
                self._timers.discard(timer_ref[0])
            if not self._stopping:
                self.submit(status.capture_id)

        ref: list[threading.Timer] = []
        timer = threading.Timer(delay, fire, args=(ref,))
        timer.daemon = True
        ref.append(timer)
        with self._cond:
            self._timers.add(timer)
        timer.start()
