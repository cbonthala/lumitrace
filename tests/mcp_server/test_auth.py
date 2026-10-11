from __future__ import annotations

import base64
import hashlib
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import anyio
import httpx
import pytest

from lifelog.config import Settings
from lifelog.mcp_server import oauth as O
from lifelog.mcp_server.auth import AuthConfigError, build_auth
from lifelog.mcp_server.oauth import OwnerOAuthProvider, oauth_state_path
from lifelog.mcp_server.server import build_server

TOKEN = "t" * 40
PASSWORD = "correct horse battery staple"
BASE = "http://localhost:8002"
CALLBACK = "https://ai-app.example/oauth/callback"
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def _settings(settings: Settings, **overrides: object) -> Settings:
    return Settings(_env_file=None, **{**settings.model_dump(), **overrides})


@asynccontextmanager
async def http_client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    server = build_server(settings, transport="streamable-http")
    app = server.streamable_http_app(streamable_http_path=settings.mcp_path, host=settings.mcp_host)
    async with (
        server.session_manager.run(),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        yield client


async def _initialize(client: httpx.AsyncClient, token: str | None = None) -> httpx.Response:
    headers = dict(MCP_HEADERS)
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return await client.post("/mcp", json=INIT, headers=headers)


# --- configuration -------------------------------------------------------------------------


def test_token_mode_requires_a_real_token(settings: Settings) -> None:
    for bad in ["", "change-me", "short"]:
        with pytest.raises(AuthConfigError):
            build_auth(_settings(settings, mcp_auth_mode="token", mcp_auth_token=bad))
    setup = build_auth(_settings(settings, mcp_auth_mode="token", mcp_auth_token=TOKEN))
    assert setup.token_verifier is not None and setup.provider is None


def test_oauth_mode_validation(settings: Settings) -> None:
    oauth = {"mcp_auth_mode": "oauth", "mcp_owner_password": PASSWORD}
    with pytest.raises(AuthConfigError):
        build_auth(_settings(settings, mcp_auth_mode="oauth", mcp_owner_password=""))
    with pytest.raises(AuthConfigError, match="https"):
        build_auth(_settings(settings, **oauth, mcp_public_url="http://journal.example.com"))
    with pytest.raises(AuthConfigError, match="without a path"):
        build_auth(_settings(settings, **oauth, mcp_public_url="https://example.com/lifelog"))
    setup = build_auth(_settings(settings, **oauth, mcp_public_url="https://journal.example.com/"))
    assert setup.provider is not None
    assert str(setup.settings.resource_server_url) == "https://journal.example.com/mcp"


def test_none_mode_has_no_auth(settings: Settings) -> None:
    setup = build_auth(settings)
    assert setup.settings is None and setup.token_verifier is None


def test_stdio_ignores_auth_settings(settings: Settings) -> None:
    build_server(_settings(settings, mcp_auth_mode="token", mcp_auth_token=""), transport="stdio")


# --- token mode ----------------------------------------------------------------------------


def test_token_mode_rejects_missing_and_wrong_tokens(settings: Settings) -> None:
    cfg = _settings(settings, mcp_auth_mode="token", mcp_auth_token=TOKEN)

    async def run() -> None:
        async with http_client(cfg) as client:
            missing = await _initialize(client)
            assert missing.status_code == 401
            assert missing.headers["www-authenticate"].startswith("Bearer")
            assert (await _initialize(client, "wrong-token")).status_code == 401
            ok = await _initialize(client, TOKEN)
            assert ok.status_code == 200
            assert "LifeLog" in ok.text
            health = await client.get("/health")
            assert health.status_code == 200 and health.json()["auth_mode"] == "token"

    anyio.run(run)


def test_none_mode_allows_requests(settings: Settings) -> None:
    async def run() -> None:
        async with http_client(settings) as client:
            assert (await _initialize(client)).status_code == 200

    anyio.run(run)


# --- oauth mode ----------------------------------------------------------------------------


@pytest.fixture
def oauth_settings(settings: Settings) -> Settings:
    return _settings(
        settings, mcp_auth_mode="oauth", mcp_owner_password=PASSWORD, mcp_public_url=BASE
    )


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def _register(client: httpx.AsyncClient) -> dict:
    resp = await client.post(
        "/register",
        json={
            "redirect_uris": [CALLBACK],
            "client_name": "Test AI <app>",
            "token_endpoint_auth_method": "client_secret_post",
            "grant_types": ["authorization_code", "refresh_token"],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _start_login(
    client: httpx.AsyncClient, reg: dict, challenge: str, resource: str = f"{BASE}/mcp"
) -> httpx.Response:
    return await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": reg["client_id"],
            "redirect_uri": CALLBACK,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "st4te",
            "scope": "lifelog",
            "resource": resource,
        },
    )


def _query(location: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}


async def _login(client: httpx.AsyncClient, reg: dict, challenge: str) -> str:
    """Run /authorize and the password page; return the authorization code."""
    resp = await _start_login(client, reg, challenge)
    assert resp.status_code == 302
    request_id = _query(resp.headers["location"])["request"]
    resp = await client.post(
        O.LOGIN_PATH, data={"request": request_id, "password": PASSWORD, "action": "approve"}
    )
    assert resp.status_code == 302
    assert resp.headers["location"].startswith(CALLBACK)
    params = _query(resp.headers["location"])
    assert params["state"] == "st4te"
    return params["code"]


async def _token(client: httpx.AsyncClient, reg: dict, **data: str) -> httpx.Response:
    return await client.post(
        "/token",
        data={"client_id": reg["client_id"], "client_secret": reg["client_secret"], **data},
    )


def test_oauth_discovery(oauth_settings: Settings) -> None:
    async def run() -> None:
        async with http_client(oauth_settings) as client:
            unauth = await _initialize(client)
            assert unauth.status_code == 401
            assert "oauth-protected-resource/mcp" in unauth.headers["www-authenticate"]
            prm = (await client.get("/.well-known/oauth-protected-resource/mcp")).json()
            assert prm["resource"] == f"{BASE}/mcp"
            assert prm["authorization_servers"] == [BASE]
            meta = (await client.get("/.well-known/oauth-authorization-server")).json()
            assert meta["issuer"] == BASE
            assert meta["registration_endpoint"] == f"{BASE}/register"
            assert meta["code_challenge_methods_supported"] == ["S256"]

    anyio.run(run)


def test_oauth_full_flow(oauth_settings: Settings) -> None:
    async def run() -> None:
        async with http_client(oauth_settings) as client:
            reg = await _register(client)
            verifier, challenge = _pkce()

            resp = await _start_login(client, reg, challenge)
            assert resp.status_code == 302
            login_url = resp.headers["location"]
            assert login_url.startswith(f"{BASE}{O.LOGIN_PATH}?request=")
            page = await client.get(login_url)
            assert page.status_code == 200
            assert "Test AI &lt;app&gt;" in page.text  # escaped
            assert "ai-app.example" in page.text
            assert page.headers["x-frame-options"] == "DENY"

            request_id = _query(login_url)["request"]
            wrong = await client.post(
                O.LOGIN_PATH, data={"request": request_id, "password": "nope", "action": "approve"}
            )
            assert wrong.status_code == 401 and "Wrong password" in wrong.text

            code = await _login(client, reg, challenge)
            bad_pkce = await _token(
                client,
                reg,
                grant_type="authorization_code",
                code=code,
                redirect_uri=CALLBACK,
                code_verifier="x" * 50,
            )
            assert bad_pkce.status_code == 400

            tokens = await _token(
                client,
                reg,
                grant_type="authorization_code",
                code=code,
                redirect_uri=CALLBACK,
                code_verifier=verifier,
                resource=f"{BASE}/mcp",
            )
            assert tokens.status_code == 200, tokens.text
            body = tokens.json()
            assert body["token_type"] == "Bearer" and body["expires_in"] == O.ACCESS_TOKEN_TTL
            reused = await _token(
                client,
                reg,
                grant_type="authorization_code",
                code=code,
                redirect_uri=CALLBACK,
                code_verifier=verifier,
            )
            assert reused.status_code == 400

            assert (await _initialize(client, body["access_token"])).status_code == 200
            assert (await _initialize(client, "not-a-token")).status_code == 401

            refreshed = await _token(
                client, reg, grant_type="refresh_token", refresh_token=body["refresh_token"]
            )
            assert refreshed.status_code == 200, refreshed.text
            new = refreshed.json()
            assert new["access_token"] != body["access_token"]
            old_refresh = await _token(
                client, reg, grant_type="refresh_token", refresh_token=body["refresh_token"]
            )
            assert old_refresh.status_code == 400
            assert (await _initialize(client, body["access_token"])).status_code == 401
            assert (await _initialize(client, new["access_token"])).status_code == 200

            revoke = await client.post(
                "/revoke",
                data={
                    "token": new["access_token"],
                    "client_id": reg["client_id"],
                    "client_secret": reg["client_secret"],
                },
            )
            assert revoke.status_code == 200
            assert (await _initialize(client, new["access_token"])).status_code == 401
            again = await _token(
                client, reg, grant_type="refresh_token", refresh_token=new["refresh_token"]
            )
            assert again.status_code == 400

    anyio.run(run)


def test_oauth_deny_and_bad_resource(oauth_settings: Settings) -> None:
    async def run() -> None:
        async with http_client(oauth_settings) as client:
            reg = await _register(client)
            _, challenge = _pkce()
            resp = await _start_login(client, reg, challenge)
            request_id = _query(resp.headers["location"])["request"]
            denied = await client.post(O.LOGIN_PATH, data={"request": request_id, "action": "deny"})
            assert denied.status_code == 302
            assert _query(denied.headers["location"])["error"] == "access_denied"
            # the request is used up
            assert (await client.get(resp.headers["location"])).status_code == 400

            other = await _start_login(client, reg, challenge, resource="https://evil.example/mcp")
            assert other.status_code == 302
            assert _query(other.headers["location"])["error"] == "invalid_target"

            assert (await client.get(f"{O.LOGIN_PATH}?request=unknown")).status_code == 400

    anyio.run(run)


def test_oauth_password_lockout(oauth_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(O, "FAILURE_DELAY", 0)

    async def run() -> None:
        async with http_client(oauth_settings) as client:
            reg = await _register(client)
            _, challenge = _pkce()
            resp = await _start_login(client, reg, challenge)
            request_id = _query(resp.headers["location"])["request"]
            form = {"request": request_id, "password": "guess", "action": "approve"}
            for _ in range(O.MAX_FAILURES):
                assert (await client.post(O.LOGIN_PATH, data=form)).status_code == 401
            form["password"] = PASSWORD
            locked = await client.post(O.LOGIN_PATH, data=form)
            assert locked.status_code == 429

    anyio.run(run)


def test_oauth_accepts_static_token_too(oauth_settings: Settings) -> None:
    cfg = _settings(oauth_settings, mcp_auth_token=TOKEN)

    async def run() -> None:
        async with http_client(cfg) as client:
            assert (await _initialize(client, TOKEN)).status_code == 200

    anyio.run(run)


def test_oauth_state_survives_restart_and_stores_only_hashes(oauth_settings: Settings) -> None:
    state_path = oauth_state_path(oauth_settings)

    async def run() -> str:
        async with http_client(oauth_settings) as client:
            reg = await _register(client)
            verifier, challenge = _pkce()
            code = await _login(client, reg, challenge)
            resp = await _token(
                client,
                reg,
                grant_type="authorization_code",
                code=code,
                redirect_uri=CALLBACK,
                code_verifier=verifier,
            )
            return resp.json()["access_token"]

    access = anyio.run(run)
    raw = state_path.read_text()
    assert access not in raw
    assert hashlib.sha256(access.encode()).hexdigest() in raw
    assert oct(state_path.stat().st_mode & 0o777) == "0o600"

    provider = OwnerOAuthProvider(
        issuer_url=BASE,
        resource_url=f"{BASE}/mcp",
        owner_password=PASSWORD,
        state_path=state_path,
    )
    token = anyio.run(provider.load_access_token, access)
    assert token is not None and token.resource == f"{BASE}/mcp" and token.subject == "owner"


def test_oauth_corrupt_state_starts_empty(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{not json")
    provider = OwnerOAuthProvider(
        issuer_url=BASE, resource_url=f"{BASE}/mcp", owner_password=PASSWORD, state_path=path
    )
    assert anyio.run(provider.get_client, "anything") is None
