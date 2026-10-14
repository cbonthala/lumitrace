"""Authentication for the recording API.

Two ways in, both checked by :func:`require_auth`:

* ``Authorization: Bearer <LUMITRACE_API_TOKEN>``: the iPhone Shortcuts and scripts.
* The Flash web app's session cookie (:data:`SESSION_COOKIE`), set by ``POST /login`` after the
  owner types ``LUMITRACE_FLASH_USERNAME`` and ``LUMITRACE_FLASH_PASSWORD`` (ADR 0019).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import threading
import time
from collections import deque

from fastapi import HTTPException, Request, status

from lumitrace.config import Settings

log = logging.getLogger(__name__)

PLACEHOLDER_TOKENS = {"", "change-me"}
MIN_TOKEN_LENGTH = 16
MIN_PASSWORD_LENGTH = 10

SESSION_COOKIE = "lumitrace_flash"
SESSION_VERSION = "v1"
MAX_FAILURES = 5
FAILURE_WINDOW = 15 * 60
FAILURE_DELAY = 0.5
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def token_problem(token: str) -> str | None:
    """Why a configured token is unsafe, or None if it looks fine."""
    if token in PLACEHOLDER_TOKENS:
        return "LUMITRACE_API_TOKEN is not set (or still 'change-me')"
    if len(token) < MIN_TOKEN_LENGTH:
        return f"LUMITRACE_API_TOKEN is shorter than {MIN_TOKEN_LENGTH} characters"
    return None


def login_problem(settings: Settings) -> str | None:
    """Why the Flash web app sign-in is off, or None if it can be used."""
    if not settings.flash_username.strip():
        return "LUMITRACE_FLASH_USERNAME is not set"
    password = settings.flash_password.get_secret_value()
    if password in PLACEHOLDER_TOKENS:
        return "LUMITRACE_FLASH_PASSWORD is not set (or still 'change-me')"
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"LUMITRACE_FLASH_PASSWORD is shorter than {MIN_PASSWORD_LENGTH} characters"
    return token_problem(settings.api_token.get_secret_value())


def check_credentials(settings: Settings, username: str, password: str) -> bool:
    """Constant-time comparison of both fields (both are always compared)."""
    user_ok = hmac.compare_digest(
        username.strip().encode(), settings.flash_username.strip().encode()
    )
    password_ok = hmac.compare_digest(
        password.encode(), settings.flash_password.get_secret_value().encode()
    )
    return user_ok and password_ok


def _session_key(settings: Settings) -> bytes:
    """Derived from the API token, username and password, so changing any of them ends every
    session."""
    material = "\0".join(
        (
            "lumitrace-flash-session",
            settings.api_token.get_secret_value(),
            settings.flash_username.strip(),
            settings.flash_password.get_secret_value(),
        )
    )
    return hashlib.sha256(material.encode()).digest()


def make_session(settings: Settings, now: float | None = None) -> tuple[str, int]:
    """A signed cookie value ``v1.<expires>.<signature>`` and its expiry (Unix seconds)."""
    expires = int((now if now is not None else time.time()) + settings.flash_session_days * 86400)
    payload = f"{SESSION_VERSION}.{expires}"
    signature = hmac.new(_session_key(settings), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}", expires


def session_valid(settings: Settings, value: str | None, now: float | None = None) -> bool:
    if not value or login_problem(settings):
        return False
    version, _, rest = value.partition(".")
    expires, _, signature = rest.partition(".")
    if version != SESSION_VERSION or not expires.isdigit():
        return False
    payload = f"{version}.{expires}"
    expected = hmac.new(_session_key(settings), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature.encode(), expected.encode()):
        return False
    return int(expires) > (now if now is not None else time.time())


def is_cross_site(request: Request) -> bool:
    """True when the browser says the request comes from another site (``Sec-Fetch-Site``)."""
    return request.headers.get("sec-fetch-site", "").lower() == "cross-site"


class LoginGuard:
    """Locks sign-in for :data:`FAILURE_WINDOW` after :data:`MAX_FAILURES` wrong passwords."""

    def __init__(self) -> None:
        self._failures: deque[float] = deque()
        self._lock = threading.Lock()

    def locked(self, now: float | None = None) -> bool:
        now = now if now is not None else time.monotonic()
        with self._lock:
            while self._failures and self._failures[0] < now - FAILURE_WINDOW:
                self._failures.popleft()
            return len(self._failures) >= MAX_FAILURES

    def record_failure(self, now: float | None = None) -> None:
        with self._lock:
            self._failures.append(now if now is not None else time.monotonic())


def require_auth(request: Request) -> None:
    """FastAPI dependency: a valid bearer token or Flash session cookie.

    Fails closed: with no token, a placeholder or a short token configured, every request is
    refused. A cookie-authenticated request that changes something and comes from another site
    is refused, so another web page cannot post into the journal in the owner's browser.
    """
    settings: Settings = request.app.state.settings
    expected = settings.api_token.get_secret_value()
    if token_problem(expected):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "the API token is not configured on the server (missing, placeholder or too short)",
        )
    header = request.headers.get("authorization", "")
    if header:
        scheme, _, supplied = header.partition(" ")
        if scheme.lower() == "bearer" and hmac.compare_digest(
            supplied.strip().encode(), expected.encode()
        ):
            return
    elif session_valid(settings, request.cookies.get(SESSION_COOKIE)):
        if request.method not in SAFE_METHODS and is_cross_site(request):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "cross-site request refused")
        return
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "missing or invalid bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )
