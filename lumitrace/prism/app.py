"""Recording API: receive recordings and notes from the iPhone Shortcuts.

Endpoints (details and examples: ``docs/prism.md``):

* ``POST /recordings``: multipart; ``audio`` file, optional ``photos``/``photos[]``, ``lat``,
  ``lon``, ``place``, ``captured_at``, ``date``, ``capture_id``.
* ``POST /notes``: multipart, urlencoded or JSON; ``text`` and/or an ``audio`` clip, same
  optional fields.
* ``GET /captures/{id}``, ``POST /captures/{id}/retry``, ``DELETE /captures/{id}``: status of a
  capture, retry a failed one, or discard one the journal has not used.
* ``GET /health``: unauthenticated liveness check.
* The Flash web app and its sign-in, recent-captures and summary endpoints:
  :mod:`lumitrace.prism.flash`.

Uploads are saved to the inbox in storage first and answered with ``202 Accepted``; a background
worker does the slow work (``lumitrace.prism.worker``).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import secrets
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import anyio
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from starlette.datastructures import UploadFile

from lumitrace import __version__
from lumitrace.config import Settings, get_settings
from lumitrace.frames.dayfile import Capture, CaptureKind
from lumitrace.frames.storage import Storage, get_storage
from lumitrace.prism.auth import login_problem, require_auth, token_problem
from lumitrace.prism.flash import in_journal, register_flash
from lumitrace.prism.inbox import CAPTURE_ID_RE, CaptureStatus, Inbox, inbox_dir, now_utc
from lumitrace.prism.journal_schedule import JournalScheduler
from lumitrace.prism.pipeline.processor import CaptureProcessor, CaptureRequest, UploadedFile
from lumitrace.prism.worker import DEFAULT_RETRY_DELAYS, CaptureWorker

log = logging.getLogger(__name__)

MAX_PHOTOS = 60
MAX_TEXT_CHARS = 50_000
MAX_PLACE_CHARS = 200


@dataclass
class Services:
    settings: Settings
    storage: Storage
    inbox: Inbox
    processor: CaptureProcessor
    worker: CaptureWorker
    scheduler: JournalScheduler


class AcceptedResponse(BaseModel):
    capture_id: str
    kind: CaptureKind
    status: str
    entry_date: dt.date
    duplicate: bool
    status_url: str
    message: str


class Upload(BaseModel):
    filename: str
    data: bytes


class ParsedCapture(BaseModel):
    """Validated request fields, before anything is stored."""

    capture_id: str | None = None
    captured_at: dt.datetime
    entry_date: dt.date | None = None
    text: str = ""
    location: str | None = None
    audio: Upload | None = None
    photos: list[Upload] = []


# --- request parsing ------------------------------------------------------------------------


def _bad(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def parse_captured_at(value: Any, settings: Settings) -> dt.datetime:
    """ISO-8601 (with or without offset; naive = local time) or Unix seconds. Default: now."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return dt.datetime.now(settings.tz)
    if isinstance(value, int | float) or (isinstance(value, str) and _is_number(value)):
        return dt.datetime.fromtimestamp(float(value), tz=settings.tz)
    if not isinstance(value, str):
        raise _bad("captured_at must be an ISO-8601 date-time")
    try:
        parsed = dt.datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise _bad("captured_at must be an ISO-8601 date-time") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=settings.tz)
    return parsed.astimezone(settings.tz)


def parse_entry_date(value: str | None, settings: Settings) -> dt.date | None:
    """The ``date`` field (``YYYY-MM-DD``). None when empty: the day then follows
    ``captured_at`` (default now) in ``LUMITRACE_TIMEZONE``, with the day rollover hour."""
    if value is None or not value.strip():
        return None
    try:
        day = dt.date.fromisoformat(value.strip())
    except ValueError as exc:
        raise _bad("date must be YYYY-MM-DD") from exc
    if day > dt.datetime.now(settings.tz).date():
        raise _bad("date is in the future")
    return day


def _is_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def _coord(value: Any, name: str, limit: float) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(str(value).strip().replace(",", "."))
    except ValueError as exc:
        raise _bad(f"{name} must be a number") from exc
    if not -limit <= number <= limit:
        raise _bad(f"{name} is out of range")
    return number


def format_location(place: str | None, lat: float | None, lon: float | None) -> str | None:
    """``"Austin (30.26720, -97.74310)"``, ``"Austin"``, ``"30.26720, -97.74310"`` or None."""
    place = " ".join((place or "").split())[:MAX_PLACE_CHARS] or None
    coords = f"{lat:.5f}, {lon:.5f}" if lat is not None and lon is not None else None
    if place and coords:
        return f"{place} ({coords})"
    return place or coords


def _text_field(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, UploadFile):
        raise _bad("expected a text field, got a file")
    return str(value)


async def _read_upload(value: Any, name: str) -> Upload | None:
    if not isinstance(value, UploadFile):
        if value is None or (isinstance(value, str) and not value):
            return None
        raise _bad(f"{name} must be a file upload")
    data = await value.read()
    if not data:
        return None
    return Upload(filename=value.filename or name, data=data)


async def parse_request(request: Request, settings: Settings) -> ParsedCapture:
    """Read multipart/urlencoded form data or a JSON body into a :class:`ParsedCapture`."""
    limit = settings.api_max_upload_mb * 1024 * 1024
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > limit:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "upload too large")

    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    fields: dict[str, Any] = {}
    audio: Upload | None = None
    photos: list[Upload] = []
    if content_type == "application/json":
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise _bad("invalid JSON body") from exc
        if not isinstance(body, dict):
            raise _bad("JSON body must be an object")
        fields = body
    elif content_type in ("multipart/form-data", "application/x-www-form-urlencoded"):
        form = await request.form(max_files=MAX_PHOTOS + 2, max_fields=100)
        for key in form:
            if key in ("photos", "photos[]", "photo"):
                for item in form.getlist(key):
                    upload = await _read_upload(item, "photo")
                    if upload is not None:
                        photos.append(upload)
            elif key == "audio":
                audio = await _read_upload(form.get(key), "audio")
            else:
                fields[key] = _text_field(form.get(key))
    else:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "send multipart/form-data (or JSON for text-only notes)",
        )

    if len(photos) > MAX_PHOTOS:
        raise _bad(f"at most {MAX_PHOTOS} photos per capture")
    total = sum(len(u.data) for u in [*photos, *([audio] if audio else [])])
    if total > limit:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "upload too large")

    capture_id = (_text_field(fields.get("capture_id")) or "").strip() or None
    if capture_id is not None and not CAPTURE_ID_RE.match(capture_id):
        raise _bad("capture_id may only contain letters, digits, '.', '_' and '-' (max 128)")
    text = (_text_field(fields.get("text")) or "").strip()
    if len(text) > MAX_TEXT_CHARS:
        raise _bad(f"text is longer than {MAX_TEXT_CHARS} characters")
    lat = _coord(fields.get("lat"), "lat", 90)
    lon = _coord(fields.get("lon"), "lon", 180)
    place = _text_field(fields.get("place"))
    return ParsedCapture(
        capture_id=capture_id,
        captured_at=parse_captured_at(fields.get("captured_at"), settings),
        entry_date=parse_entry_date(_text_field(fields.get("date")), settings),
        text=text,
        location=format_location(place, lat, lon),
        audio=audio,
        photos=photos,
    )


def _safe_suffix(filename: str, default: str) -> str:
    suffix = Path(filename).suffix.lower()
    return suffix if suffix[1:].isalnum() and 1 < len(suffix) <= 6 else default


# --- accepting ------------------------------------------------------------------------------


def accept_capture(
    services: Services, kind: CaptureKind, parsed: ParsedCapture
) -> tuple[CaptureStatus, bool]:
    """Store the upload in the inbox and queue it. Returns (status, duplicate).

    A ``capture_id`` that was already accepted is not stored again (safe retries from the
    offline inbox); one whose earlier attempt failed is replaced and queued again.
    """
    inbox = services.inbox
    capture_id = parsed.capture_id or (
        f"{Capture.make_id(kind, parsed.captured_at)}-{secrets.token_hex(3)}"
    )
    with inbox.id_lock(capture_id):
        existing = inbox.get_status(capture_id)
        if existing is not None and existing.status != "failed":
            return existing, True

        folder = inbox_dir(capture_id)
        files: dict[str, bytes] = {}
        audio_ref: UploadedFile | None = None
        if parsed.audio is not None:
            path = f"{folder}/audio{_safe_suffix(parsed.audio.filename, '.audio')}"
            files[path] = parsed.audio.data
            audio_ref = UploadedFile(
                path=path, filename=parsed.audio.filename, size=len(parsed.audio.data)
            )
        photo_refs: list[UploadedFile] = []
        for n, photo in enumerate(parsed.photos, start=1):
            path = f"{folder}/photo-{n:02d}{_safe_suffix(photo.filename, '.img')}"
            files[path] = photo.data
            photo_refs.append(
                UploadedFile(path=path, filename=photo.filename, size=len(photo.data))
            )

        received = now_utc()
        req = CaptureRequest(
            id=capture_id,
            kind=kind,
            received_at=received,
            captured_at=parsed.captured_at,
            entry_date=parsed.entry_date,
            text=parsed.text,
            location=parsed.location,
            audio=audio_ref,
            photos=photo_refs,
        )
        if existing is not None:
            inbox.remove(capture_id)
        inbox.save(req, files)
        capture_status = CaptureStatus(
            capture_id=capture_id,
            kind=kind,
            status="queued",
            entry_date=services.processor.entry_date_of(req),
            captured_at=parsed.captured_at,
            received_at=received,
            attempts=existing.attempts if existing else 0,
        )
        inbox.put_status(capture_status)
    services.worker.submit(capture_id)
    return capture_status, False


def _accepted(capture: CaptureStatus, duplicate: bool) -> JSONResponse:
    day = f"{capture.entry_date:%A, %B} {capture.entry_date.day}"
    if duplicate:
        message = f"Already received ({capture.status}). Nothing to resend."
    else:
        label = "Recording" if capture.kind == "recording" else "Note"
        message = f"{label} saved for {day}. Your journal updates in a minute."
    body = AcceptedResponse(
        capture_id=capture.capture_id,
        kind=capture.kind,
        status=capture.status,
        entry_date=capture.entry_date,
        duplicate=duplicate,
        status_url=f"/captures/{capture.capture_id}",
        message=message,
    )
    code = status.HTTP_200_OK if duplicate else status.HTTP_202_ACCEPTED
    return JSONResponse(body.model_dump(mode="json"), status_code=code)


# --- app ------------------------------------------------------------------------------------


def create_app(
    settings: Settings | None = None,
    *,
    storage: Storage | None = None,
    processor: CaptureProcessor | None = None,
    retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
) -> FastAPI:
    """Build the app. ``storage`` and ``processor`` can be injected (tests); otherwise they are
    created from ``settings`` on start-up, so importing this module never touches storage."""
    settings = settings or get_settings()
    lock = threading.Lock()

    def services() -> Services:
        with lock:
            existing: Services | None = getattr(app.state, "services", None)
            if existing is not None:
                return existing
            store = storage or (processor.storage if processor else get_storage(settings))
            proc = processor or CaptureProcessor(settings, store)
            inbox = Inbox(store)
            worker = CaptureWorker(proc, inbox, retry_delays=retry_delays)
            scheduler = JournalScheduler(proc, worker)
            built = Services(settings, store, inbox, proc, worker, scheduler)
            app.state.services = built
            worker.start()
            scheduler.start()
            return built

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        problem = token_problem(settings.api_token.get_secret_value())
        if problem:
            log.error(
                "%s; every request will be refused with 503 until it is set "
                "(generate one with `openssl rand -hex 32`)",
                problem,
            )
        sign_in = login_problem(settings)
        if sign_in:
            log.info("Flash web app sign-in is off: %s", sign_in)
        built = await anyio.to_thread.run_sync(services)
        await anyio.to_thread.run_sync(built.worker.resume)
        try:
            yield
        finally:
            await anyio.to_thread.run_sync(built.scheduler.stop)
            await anyio.to_thread.run_sync(built.worker.stop)
            app.state.services = None

    app = FastAPI(title="Lumitrace Prism (recording API)", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.services = None
    app.state.get_services = services
    auth = [Depends(require_auth)]

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "api", "version": __version__}

    @app.post("/recordings", dependencies=auth, status_code=202, response_model=AcceptedResponse)
    async def post_recording(request: Request) -> JSONResponse:
        parsed = await parse_request(request, settings)
        if parsed.audio is None:
            raise _bad("a recording needs an 'audio' file")
        built = await anyio.to_thread.run_sync(services)
        result = await anyio.to_thread.run_sync(partial(accept_capture, built, "recording", parsed))
        return _accepted(*result)

    @app.post("/notes", dependencies=auth, status_code=202, response_model=AcceptedResponse)
    async def post_note(request: Request) -> JSONResponse:
        parsed = await parse_request(request, settings)
        if not parsed.text and parsed.audio is None and not parsed.photos:
            raise _bad("a note needs 'text', an 'audio' clip or photos")
        built = await anyio.to_thread.run_sync(services)
        result = await anyio.to_thread.run_sync(partial(accept_capture, built, "note", parsed))
        return _accepted(*result)

    def _status_or_404(built: Services, capture_id: str) -> CaptureStatus:
        found = None
        if CAPTURE_ID_RE.match(capture_id):
            found = built.inbox.get_status(capture_id)
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown capture id")
        return found

    @app.get("/captures/{capture_id}", dependencies=auth, response_model=CaptureStatus)
    def get_capture(capture_id: str) -> CaptureStatus:
        return _status_or_404(services(), capture_id)

    @app.post("/captures/{capture_id}/retry", dependencies=auth, response_model=CaptureStatus)
    def retry_capture(capture_id: str) -> CaptureStatus:
        built = services()
        with built.inbox.id_lock(capture_id):
            found = _status_or_404(built, capture_id)
            if found.status != "failed":
                raise HTTPException(status.HTTP_409_CONFLICT, f"capture is {found.status}")
            if not built.inbox.has_payload(capture_id):
                raise HTTPException(
                    status.HTTP_410_GONE, "the upload is no longer in the inbox; send it again"
                )
            found.status = "queued"
            found.retry_at = None
            built.inbox.put_status(found)
        built.worker.submit(capture_id)
        return found

    @app.delete("/captures/{capture_id}", dependencies=auth, status_code=204)
    def delete_capture(capture_id: str) -> Response:
        built = services()
        with built.inbox.id_lock(capture_id):
            found = _status_or_404(built, capture_id)
            if found.status != "done":
                raise HTTPException(status.HTTP_409_CONFLICT, f"capture is {found.status}")
            day = built.processor._read_day(found.entry_date)
            if in_journal(found, day):
                raise HTTPException(
                    status.HTTP_409_CONFLICT, "this capture is already in the journal"
                )
            built.processor.drop_capture(found.entry_date, found.capture_id)
            built.inbox.remove(capture_id)
            built.inbox.delete_status(capture_id)
        return Response(status_code=204)

    register_flash(app, settings, services, auth)
    return app


app = create_app()
