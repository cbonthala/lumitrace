"""Bearer-token authentication for the recording API (``Authorization: Bearer <token>``)."""

from __future__ import annotations

import hmac
import logging

from fastapi import HTTPException, Request, status

log = logging.getLogger(__name__)

PLACEHOLDER_TOKENS = {"", "change-me"}
MIN_TOKEN_LENGTH = 16


def token_problem(token: str) -> str | None:
    """Why a configured token is unsafe, or None if it looks fine."""
    if token in PLACEHOLDER_TOKENS:
        return "LUMITRACE_API_TOKEN is not set (or still 'change-me')"
    if len(token) < MIN_TOKEN_LENGTH:
        return f"LUMITRACE_API_TOKEN is shorter than {MIN_TOKEN_LENGTH} characters"
    return None


def require_token(request: Request) -> None:
    """FastAPI dependency. Fails closed: with no token, a placeholder or a short token
    configured, every request is refused."""
    expected = request.app.state.settings.api_token.get_secret_value()
    if token_problem(expected):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "the API token is not configured on the server (missing, placeholder or too short)",
        )
    header = request.headers.get("authorization", "")
    scheme, _, supplied = header.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        supplied.strip().encode(), expected.encode()
    ):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
