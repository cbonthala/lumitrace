"""Minimal single-owner OAuth 2.1 authorization server for phone AI apps (Claude, ChatGPT).

Built on the MCP SDK's auth support, which serves the endpoints (``/.well-known/...``,
``/register``, ``/authorize``, ``/token``, ``/revoke``) and checks PKCE, redirect URIs and client
secrets. This module is the storage and the one human step: ``/authorize`` redirects to a
password page (:data:`LOGIN_PATH`); the owner types ``LUMITRACE_MCP_OWNER_PASSWORD`` and is sent
back to the AI app with an authorization code.

Registered clients and tokens are kept in a small JSON file next to the index
(:func:`oauth_state_path`), with tokens stored only as SHA-256 hashes. Authorization codes and
pending sign-ins live in memory (they last minutes).

Every token records when the owner signed in (``signed_in_at``); refreshing keeps that time,
and no token outlives ``signed_in_at + session_days``, so each app has to sign in again after
``LUMITRACE_MCP_SESSION_DAYS``.
See ``docs/decisions/0032-single-owner-oauth.md`` and ``0034-oauth-sessions-end-after-days.md``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import html
import json
import logging
import os
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from lumitrace.config import Settings

logger = logging.getLogger(__name__)

LOGIN_PATH = "/oauth/login"
STATE_FILE_NAME = "mcp-oauth-state.json"

ACCESS_TOKEN_TTL = 60 * 60  # 1 hour
REFRESH_TOKEN_TTL = 90 * 24 * 60 * 60  # 90 days; refreshing rotates it
DEFAULT_SESSION_DAYS = 7
AUTH_CODE_TTL = 5 * 60
LOGIN_TTL = 10 * 60
MAX_CLIENTS = 50
MAX_PENDING = 100
MAX_FAILURES = 5
FAILURE_WINDOW = 15 * 60
FAILURE_DELAY = 0.5
LAST_USED_SAVE_INTERVAL = 60


def oauth_state_path(settings: Settings) -> Path:
    """OAuth clients/tokens file: next to the index, on the server's disk (not in storage)."""
    return Path(settings.index_path).parent / STATE_FILE_NAME


def _now() -> float:
    return time.time()


def _iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return dt.datetime.fromtimestamp(timestamp, dt.UTC).isoformat(timespec="seconds")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _norm_url(url: str) -> str:
    return url.rstrip("/").lower()


@dataclass
class _PendingLogin:
    client_id: str
    client_name: str | None
    params: AuthorizationParams
    expires_at: float


class OwnerOAuthProvider:
    """``OAuthAuthorizationServerProvider`` for one owner who signs in with a password."""

    def __init__(
        self,
        *,
        issuer_url: str,
        resource_url: str,
        owner_password: str,
        state_path: Path,
        scope: str = "lumitrace",
        session_days: int = DEFAULT_SESSION_DAYS,
    ) -> None:
        self.issuer_url = issuer_url.rstrip("/")
        self.resource_url = resource_url
        self.scope = scope
        self.session_days = session_days
        self._session_seconds = session_days * 24 * 60 * 60
        self._password = owner_password.encode()
        self._state_path = Path(state_path)
        self._lock = threading.Lock()
        self._clients: dict[str, dict[str, Any]] = {}
        self._access: dict[str, dict[str, Any]] = {}
        self._refresh: dict[str, dict[str, Any]] = {}
        self._pending: dict[str, _PendingLogin] = {}
        self._codes: dict[str, AuthorizationCode] = {}
        self._last_used: dict[str, float] = {}
        self._last_used_saved_at = 0.0
        self._failures: deque[float] = deque()
        self._load()

    @property
    def login_url(self) -> str:
        return self.issuer_url + LOGIN_PATH

    # --- persistence ------------------------------------------------------------------------

    def _load(self) -> None:
        if not self._state_path.is_file():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            self._clients = dict(data.get("clients", {}))
            self._access = dict(data.get("access_tokens", {}))
            self._refresh = dict(data.get("refresh_tokens", {}))
            self._last_used = dict(data.get("last_used", {}))
        except (OSError, ValueError, AttributeError):
            logger.warning(
                "OAuth state file %s is unreadable; starting empty (AI apps must reconnect)",
                self._state_path,
                exc_info=True,
            )
            return
        if self._limit_sessions():
            self._save()

    def _limit_sessions(self) -> bool:
        """Cap every token at its sign-in time plus the session length. Tokens saved before
        sign-in times were recorded count as signed in now. True if anything changed."""
        now = int(_now())
        changed = False
        for table in (self._access, self._refresh):
            for info in table.values():
                if "signed_in_at" not in info:
                    info["signed_in_at"] = now
                    changed = True
                end = info["signed_in_at"] + self._session_seconds
                if info["expires_at"] > end:
                    info["expires_at"] = end
                    changed = True
        return changed

    def _save(self) -> None:
        now = _now()
        self._access = {k: v for k, v in self._access.items() if v["expires_at"] > now}
        self._refresh = {k: v for k, v in self._refresh.items() if v["expires_at"] > now}
        data = {
            "version": 1,
            "clients": self._clients,
            "access_tokens": self._access,
            "refresh_tokens": self._refresh,
            "last_used": self._last_used,
        }
        with self._lock:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=1, sort_keys=True)
            os.replace(tmp, self._state_path)

    # --- clients ----------------------------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        raw = self._clients.get(client_id)
        return None if raw is None else OAuthClientInformationFull.model_validate(raw)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        scopes = (client_info.scope or "").split()
        if self.scope not in scopes:
            client_info.scope = " ".join([*scopes, self.scope])
        self._clients[client_info.client_id] = client_info.model_dump(mode="json")
        if len(self._clients) > MAX_CLIENTS:
            oldest = sorted(
                self._clients, key=lambda c: self._clients[c].get("client_id_issued_at") or 0
            )
            for client_id in oldest[: len(self._clients) - MAX_CLIENTS]:
                self._forget_client(client_id)
        logger.info("OAuth client registered: %s", client_info.client_name or "(unnamed)")
        self._save()

    def _forget_client(self, client_id: str) -> None:
        self._clients.pop(client_id, None)
        self._last_used.pop(client_id, None)
        self._drop_tokens(client_id)

    def _drop_tokens(self, client_id: str) -> None:
        self._access = {k: v for k, v in self._access.items() if v["client_id"] != client_id}
        self._refresh = {k: v for k, v in self._refresh.items() if v["client_id"] != client_id}
        self._codes = {k: v for k, v in self._codes.items() if v.client_id != client_id}
        self._pending = {k: v for k, v in self._pending.items() if v.client_id != client_id}

    # --- connected apps (the private admin API, decision 0036) ------------------------------

    def list_apps(self) -> list[dict[str, Any]]:
        """Registered apps with their current session, signed-in ones first."""
        now = _now()
        apps = []
        for client_id, raw in self._clients.items():
            sessions = [
                v
                for v in self._refresh.values()
                if v["client_id"] == client_id and v["expires_at"] > now
            ]
            hosts = sorted(
                {AnyUrl(str(uri)).host or "" for uri in raw.get("redirect_uris") or []} - {""}
            )
            apps.append(
                {
                    "id": client_id,
                    "name": raw.get("client_name") or None,
                    "hosts": hosts,
                    "registered_at": _iso(raw.get("client_id_issued_at")),
                    "signed_in": bool(sessions),
                    "signed_in_at": _iso(max((s["signed_in_at"] for s in sessions), default=None)),
                    "session_ends_at": _iso(max((s["expires_at"] for s in sessions), default=None)),
                    "last_used_at": _iso(self._last_used.get(client_id)),
                }
            )
        apps.sort(
            key=lambda a: (a["signed_in"], a["last_used_at"] or "", a["registered_at"] or ""),
            reverse=True,
        )
        return apps

    def sign_out(self, client_id: str) -> bool:
        """Disconnect the app now: its tokens are deleted, so its next request gets 401 and it
        must sign in with the password again. The registration stays. False if unknown."""
        if client_id not in self._clients:
            return False
        self._drop_tokens(client_id)
        self._save()
        logger.info("OAuth app signed out by the owner")
        return True

    def sign_out_all(self) -> int:
        """End every session (registrations stay). Returns how many apps were signed in."""
        now = _now()
        signed_in = {v["client_id"] for v in self._refresh.values() if v["expires_at"] > now}
        self._access, self._refresh, self._codes, self._pending = {}, {}, {}, {}
        self._save()
        logger.info("OAuth: every app signed out by the owner (%d were signed in)", len(signed_in))
        return len(signed_in)

    def _note_use(self, client_id: str) -> None:
        now = _now()
        first_use = client_id not in self._last_used
        self._last_used[client_id] = now
        if first_use or now - self._last_used_saved_at >= LAST_USED_SAVE_INTERVAL:
            self._last_used_saved_at = now
            self._save()

    # --- authorization ----------------------------------------------------------------------

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        if params.resource and _norm_url(params.resource) not in {
            _norm_url(self.resource_url),
            _norm_url(self.issuer_url),
        }:
            raise AuthorizeError("invalid_target", "unknown resource for this server")
        now = _now()
        self._pending = {k: v for k, v in self._pending.items() if v.expires_at > now}
        if len(self._pending) >= MAX_PENDING:
            raise AuthorizeError("temporarily_unavailable", "too many pending sign-ins")
        request_id = secrets.token_urlsafe(32)
        self._pending[request_id] = _PendingLogin(
            client_id=client.client_id,
            client_name=client.client_name,
            params=params,
            expires_at=now + LOGIN_TTL,
        )
        return f"{self.login_url}?request={request_id}"

    async def handle_login(self, request: Request) -> Response:
        """``GET`` shows the password page; ``POST`` checks it and redirects to the AI app."""
        if request.method == "GET":
            request_id = request.query_params.get("request", "")
            pending = self._pending_login(request_id)
            if pending is None:
                return _expired_page()
            return _login_page(request_id, pending, self.session_days)

        form = await request.form()
        request_id = str(form.get("request", ""))
        pending = self._pending_login(request_id)
        if pending is None:
            return _expired_page()
        redirect_uri = str(pending.params.redirect_uri)
        state = pending.params.state

        if form.get("action") == "deny":
            self._pending.pop(request_id, None)
            return _redirect(
                construct_redirect_uri(
                    redirect_uri,
                    error="access_denied",
                    error_description="The owner declined",
                    state=state,
                )
            )

        now = _now()
        while self._failures and self._failures[0] < now - FAILURE_WINDOW:
            self._failures.popleft()
        if len(self._failures) >= MAX_FAILURES:
            logger.warning("OAuth sign-in locked after %d failed attempts", MAX_FAILURES)
            return _login_page(
                request_id,
                pending,
                self.session_days,
                error="Too many wrong passwords. Wait 15 minutes and try again.",
                status_code=429,
            )
        password = str(form.get("password", "")).encode()
        if not hmac.compare_digest(password, self._password):
            self._failures.append(now)
            logger.warning("OAuth sign-in: wrong owner password")
            await anyio.sleep(FAILURE_DELAY)
            return _login_page(
                request_id, pending, self.session_days, error="Wrong password.", status_code=401
            )

        self._pending.pop(request_id, None)
        code = secrets.token_urlsafe(32)
        self._codes = {k: v for k, v in self._codes.items() if v.expires_at > now}
        self._codes[code] = AuthorizationCode(
            code=code,
            scopes=[self.scope],
            expires_at=now + AUTH_CODE_TTL,
            client_id=pending.client_id,
            code_challenge=pending.params.code_challenge,
            redirect_uri=pending.params.redirect_uri,
            redirect_uri_provided_explicitly=pending.params.redirect_uri_provided_explicitly,
            resource=self.resource_url,
            subject="owner",
        )
        logger.info("OAuth sign-in approved for %s", pending.client_name or "(unnamed client)")
        return _redirect(construct_redirect_uri(redirect_uri, code=code, state=state))

    def _pending_login(self, request_id: str) -> _PendingLogin | None:
        pending = self._pending.get(request_id) if request_id else None
        if pending is None or pending.expires_at < _now():
            return None
        return pending

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        code = self._codes.get(authorization_code)
        if code is None or code.client_id != client.client_id:
            return None
        return code

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        if self._codes.pop(authorization_code.code, None) is None:
            raise TokenError("invalid_grant", "authorization code already used")
        return self._issue(client.client_id, authorization_code.scopes, int(_now()))

    # --- tokens -----------------------------------------------------------------------------

    def _issue(self, client_id: str, scopes: list[str], signed_in_at: int) -> OAuthToken:
        now = int(_now())
        session_end = signed_in_at + self._session_seconds
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        access_hash, refresh_hash = _hash(access), _hash(refresh)
        common = {
            "client_id": client_id,
            "scopes": scopes,
            "resource": self.resource_url,
            "signed_in_at": signed_in_at,
        }
        access_expires = min(now + ACCESS_TOKEN_TTL, session_end)
        self._access[access_hash] = {
            **common,
            "expires_at": access_expires,
            "refresh": refresh_hash,
        }
        self._refresh[refresh_hash] = {
            **common,
            "expires_at": min(now + REFRESH_TOKEN_TTL, session_end),
            "access": access_hash,
        }
        self._save()
        return OAuthToken(
            access_token=access,
            expires_in=access_expires - now,
            scope=" ".join(scopes),
            refresh_token=refresh,
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        info = self._access.get(_hash(token))
        if info is None or info["expires_at"] < _now():
            return None
        self._note_use(info["client_id"])
        return AccessToken(
            token=token,
            client_id=info["client_id"],
            scopes=info["scopes"],
            expires_at=info["expires_at"],
            resource=info["resource"],
            subject="owner",
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        info = self._refresh.get(_hash(refresh_token))
        if info is None or info["client_id"] != client.client_id:
            return None
        if info["expires_at"] < _now():
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=info["client_id"],
            scopes=info["scopes"],
            expires_at=info["expires_at"],
            resource=info["resource"],
            subject="owner",
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        info = self._refresh.pop(_hash(refresh_token.token), None)
        if info is None:
            raise TokenError("invalid_grant", "refresh token already used")
        self._access.pop(info.get("access", ""), None)
        return self._issue(client.client_id, scopes or info["scopes"], info["signed_in_at"])

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        token_hash = _hash(token.token)
        access = self._access.pop(token_hash, None)
        refresh = self._refresh.pop(token_hash, None)
        if access:
            self._refresh.pop(access.get("refresh", ""), None)
        if refresh:
            self._access.pop(refresh.get("access", ""), None)
        if access or refresh:
            self._save()


# --- HTML -----------------------------------------------------------------------------------

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lumitrace sign-in</title>
<style>
body{{font-family:-apple-system,system-ui,sans-serif;max-width:26rem;margin:3rem auto;
padding:0 1rem;color:#222}}
h1{{font-size:1.4rem}} .muted{{color:#666;font-size:.9rem}} .error{{color:#b00020}}
input[type=password]{{width:100%;font-size:1.1rem;padding:.6rem;box-sizing:border-box;
margin:.5rem 0 1rem}}
button{{font-size:1rem;padding:.6rem 1.2rem;margin-right:.5rem}}
</style></head><body>
{body}
</body></html>"""

_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",
    # No form-action: browsers apply it to the redirect back to the AI app's callback.
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
    "frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
}


def _redirect(url: str) -> Response:
    return RedirectResponse(url, status_code=302, headers={"Cache-Control": "no-store"})


def _login_page(
    request_id: str,
    pending: _PendingLogin,
    session_days: int,
    *,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    client = html.escape(pending.client_name or "An AI app")
    target = html.escape(AnyUrl(str(pending.params.redirect_uri)).host or "")
    days = "1 day" if session_days == 1 else f"{session_days} days"
    body = f"""<h1>Connect to your Lumitrace</h1>
<p><strong>{client}</strong> wants to read your journal.</p>
<p class="muted">After you sign in you will be sent back to <strong>{target}</strong>.
It stays connected for {days}, then asks for the password again.</p>
{f'<p class="error">{html.escape(error)}</p>' if error else ""}
<form method="post" action="{LOGIN_PATH}">
<input type="hidden" name="request" value="{html.escape(request_id)}">
<label for="password">Owner password</label>
<input id="password" type="password" name="password" autocomplete="current-password" autofocus>
<button type="submit" name="action" value="approve">Allow</button>
<button type="submit" name="action" value="deny">Deny</button>
</form>"""
    return HTMLResponse(_PAGE.format(body=body), status_code=status_code, headers=_SECURITY_HEADERS)


def _expired_page() -> HTMLResponse:
    body = (
        "<h1>Sign-in link expired</h1><p>This sign-in link is no longer valid. "
        "Start connecting again from your AI app.</p>"
    )
    return HTMLResponse(_PAGE.format(body=body), status_code=400, headers=_SECURITY_HEADERS)
