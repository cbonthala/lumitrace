"""The Flash web app (``/flash/``) and the endpoints only it uses (ADR 0019).

* ``POST /login``, ``POST /logout``, ``GET /session``: username/password sign-in that sets a
  signed session cookie (:mod:`lumitrace.prism.auth`).
* ``GET /captures``: recent capture statuses (no journal content).
* ``GET /summary``: days logged, captures and streak, read from the day files.
* ``/lens/apps``: the AI apps connected to the Lens (:mod:`lumitrace.prism.lens_apps`).
* ``/flash/``: the static app in ``lumitrace/prism/web/``.
"""

from __future__ import annotations

import datetime as dt
import logging
import mimetypes
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import anyio
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from lumitrace import __version__
from lumitrace.config import Settings
from lumitrace.frames.dayfile import (
    DayFileParseError,
    day_file_path,
    entry_date,
    parse,
    parse_day_file_path,
)
from lumitrace.frames.storage import Storage
from lumitrace.prism.auth import (
    FAILURE_DELAY,
    SESSION_COOKIE,
    LoginGuard,
    check_credentials,
    is_cross_site,
    login_problem,
    make_session,
    session_valid,
)
from lumitrace.prism.inbox import CaptureStatus
from lumitrace.prism.lens_apps import register_lens_apps

log = logging.getLogger(__name__)

mimetypes.add_type("application/manifest+json", ".webmanifest")

WEB_DIR = Path(__file__).parent / "web"
SUMMARY_DAYS = 7
STREAK_MAX_MONTHS = 24
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; "
    "style-src 'self'; script-src 'self'; connect-src 'self'; manifest-src 'self'; "
    "worker-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


class LoginRequest(BaseModel):
    username: str = ""
    password: str = ""


class SessionInfo(BaseModel):
    signed_in: bool
    username: str | None
    sign_in_available: bool
    version: str


class WeekSummary(BaseModel):
    today: dt.date
    days: int
    days_logged: int
    logged_dates: list[dt.date]
    captures: int
    streak: int


# --- summary --------------------------------------------------------------------------------


def _months_back(day: dt.date) -> Iterator[tuple[int, int]]:
    year, month = day.year, day.month
    for _ in range(STREAK_MAX_MONTHS):
        yield year, month
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)


def _days_in_month(storage: Storage, year: int, month: int) -> set[dt.date]:
    days = set()
    for info in storage.list(f"{year:04d}/{month:02d}"):
        day = parse_day_file_path(info.path)
        if day is not None:
            days.add(day)
    return days


def week_summary(storage: Storage, today: dt.date) -> WeekSummary:
    """Days with a day file in the last :data:`SUMMARY_DAYS` days (today included), the
    captures in them, and the streak of consecutive days up to today (or up to yesterday while
    today is still empty). Lists storage one month at a time."""
    logged: set[dt.date] = set()
    seen_months: set[tuple[int, int]] = set()
    streak = 0
    day = today
    for year, month in _months_back(today):
        logged |= _days_in_month(storage, year, month)
        seen_months.add((year, month))
        if day == today and day not in logged:
            day -= dt.timedelta(days=1)
        while day in logged:
            streak += 1
            day -= dt.timedelta(days=1)
        if (day.year, day.month) == (year, month):
            break

    window = [today - dt.timedelta(days=n) for n in range(SUMMARY_DAYS)]
    for year, month in {(d.year, d.month) for d in window} - seen_months:
        logged |= _days_in_month(storage, year, month)
    logged_dates = sorted(d for d in window if d in logged)
    captures = 0
    for d in logged_dates:
        try:
            captures += len(parse(storage.read_text(day_file_path(d)), fallback_date=d).captures)
        except (FileNotFoundError, DayFileParseError):
            log.warning("summary: could not read the day file for %s", d)
    return WeekSummary(
        today=today,
        days=SUMMARY_DAYS,
        days_logged=len(logged_dates),
        logged_dates=logged_dates,
        captures=captures,
        streak=streak,
    )


# --- routes ---------------------------------------------------------------------------------


def _secure_cookie(request: Request) -> bool:
    """Secure everywhere except plain-HTTP development on this machine."""
    return request.url.scheme == "https" or request.url.hostname not in LOCAL_HOSTS


def _clear_session(response: Response, request: Request) -> None:
    response.delete_cookie(
        SESSION_COOKIE, path="/", httponly=True, samesite="strict", secure=_secure_cookie(request)
    )


def register_flash(
    app: FastAPI,
    settings: Settings,
    services: Callable[[], Any],
    auth: list[Any],
) -> None:
    """Add the Flash routes and the static app to ``app``. Call after the API routes."""
    guard = LoginGuard()
    app.state.login_guard = guard

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable[..., Any]) -> Response:
        response: Response = await call_next(request)
        if request.url.path.startswith("/flash"):
            response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.post("/login", response_model=SessionInfo)
    async def login(body: LoginRequest, request: Request) -> JSONResponse:
        if is_cross_site(request):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "cross-site request refused")
        problem = login_problem(settings)
        if problem:
            log.error("Flash sign-in attempted but it is off: %s", problem)
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "sign-in is not set up on the server (LUMITRACE_FLASH_USERNAME and "
                "LUMITRACE_FLASH_PASSWORD)",
            )
        if guard.locked():
            log.warning("Flash sign-in locked after repeated wrong passwords")
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "too many wrong passwords; wait 15 minutes and try again",
            )
        if not check_credentials(settings, body.username, body.password):
            guard.record_failure()
            log.warning("Flash sign-in: wrong username or password")
            await anyio.sleep(FAILURE_DELAY)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong username or password")
        value, expires = make_session(settings)
        info = SessionInfo(
            signed_in=True,
            username=settings.flash_username.strip(),
            sign_in_available=True,
            version=__version__,
        )
        response = JSONResponse(info.model_dump())
        response.set_cookie(
            SESSION_COOKIE,
            value,
            max_age=settings.flash_session_days * 86400,
            expires=expires,
            path="/",
            httponly=True,
            samesite="strict",
            secure=_secure_cookie(request),
        )
        return response

    @app.post("/logout", status_code=204)
    def logout(request: Request) -> Response:
        response = Response(status_code=204)
        _clear_session(response, request)
        return response

    @app.get("/session", response_model=SessionInfo)
    def session(request: Request) -> SessionInfo:
        signed_in = session_valid(settings, request.cookies.get(SESSION_COOKIE))
        return SessionInfo(
            signed_in=signed_in,
            username=settings.flash_username.strip() if signed_in else None,
            sign_in_available=login_problem(settings) is None,
            version=__version__,
        )

    @app.get("/captures", dependencies=auth, response_model=list[CaptureStatus])
    def recent_captures(
        days: int = Query(default=7, ge=1, le=60), limit: int = Query(default=30, ge=1, le=200)
    ) -> list[CaptureStatus]:
        since = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
        return services().inbox.recent_statuses(since, limit)

    @app.get("/summary", dependencies=auth, response_model=WeekSummary)
    def summary() -> WeekSummary:
        today = entry_date(dt.datetime.now(settings.tz), settings.tz, settings.day_rollover_hour)
        return week_summary(services().storage, today)

    register_lens_apps(app, settings, auth)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/flash/")

    @app.get("/flash", include_in_schema=False)
    def flash_no_slash() -> RedirectResponse:
        return RedirectResponse("/flash/")

    app.mount("/flash", StaticFiles(directory=WEB_DIR, html=True), name="flash")
