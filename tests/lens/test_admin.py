"""The Lens's private admin API (connected AI apps), wired as ``lumitrace-lens`` serves it."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
import httpx
import pytest

from lumitrace.config import Settings
from lumitrace.lens import oauth as O
from lumitrace.lens.__main__ import http_apps
from lumitrace.lens.oauth import oauth_state_path
from tests.lens.test_auth import (
    BASE,
    CALLBACK,
    PASSWORD,
    TOKEN,
    _initialize,
    _login,
    _pkce,
    _register,
    _settings,
    _token,
)

ADMIN = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def admin_settings(settings: Settings) -> Settings:
    return _settings(
        settings,
        api_token=TOKEN,
        mcp_auth_mode="oauth",
        mcp_owner_password=PASSWORD,
        mcp_public_url=BASE,
    )


@asynccontextmanager
async def clients(settings: Settings) -> AsyncIterator[tuple[httpx.AsyncClient, httpx.AsyncClient]]:
    """(MCP client, admin client) for the two apps ``lumitrace-lens`` serves."""
    (mcp_app, _, _), (admin_app, _, _) = http_apps(settings)
    async with (
        mcp_app.router.lifespan_context(mcp_app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=mcp_app), base_url=BASE) as mcp,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=admin_app), base_url="http://lens:8003"
        ) as admin,
    ):
        yield mcp, admin


async def _sign_in(mcp: httpx.AsyncClient) -> tuple[dict, dict]:
    reg = await _register(mcp)
    verifier, challenge = _pkce()
    code = await _login(mcp, reg, challenge)
    resp = await _token(
        mcp,
        reg,
        grant_type="authorization_code",
        code=code,
        redirect_uri=CALLBACK,
        code_verifier=verifier,
    )
    assert resp.status_code == 200, resp.text
    return reg, resp.json()


def test_lens_serves_the_admin_api_only_with_oauth(
    settings: Settings, admin_settings: Settings
) -> None:
    apps = http_apps(admin_settings)
    assert [(host, port) for _, host, port in apps] == [("0.0.0.0", 8002), ("127.0.0.1", 8003)]
    assert len(http_apps(_settings(admin_settings, mcp_admin_port=0))) == 1
    assert len(http_apps(settings)) == 1  # auth mode none: nothing to manage


def test_admin_api_needs_the_api_token(admin_settings: Settings) -> None:
    async def run() -> None:
        async with clients(admin_settings) as (mcp, admin):
            assert (await admin.get("/admin/apps")).status_code == 401
            wrong = {"Authorization": "Bearer " + "x" * 40}
            assert (await admin.get("/admin/apps", headers=wrong)).status_code == 401
            assert (await admin.post("/admin/apps/sign-out-all")).status_code == 401
            assert (await admin.get("/admin/apps", headers=ADMIN)).status_code == 200
            assert (await mcp.get("/admin/apps", headers=ADMIN)).status_code == 404

        async with clients(_settings(admin_settings, api_token="change-me")) as (_, admin):
            resp = await admin.get("/admin/apps", headers={"Authorization": "Bearer change-me"})
            assert resp.status_code == 503

    anyio.run(run)


def test_admin_lists_and_disconnects_an_app(admin_settings: Settings) -> None:
    async def run() -> None:
        async with clients(admin_settings) as (mcp, admin):
            body = (await admin.get("/admin/apps", headers=ADMIN)).json()
            assert body == {"apps": [], "session_days": 7}

            reg, tokens = await _sign_in(mcp)
            assert (await _initialize(mcp, tokens["access_token"])).status_code == 200

            [app] = (await admin.get("/admin/apps", headers=ADMIN)).json()["apps"]
            assert app["id"] == reg["client_id"]
            assert app["name"] == "Test AI <app>"
            assert app["hosts"] == ["ai-app.example"]
            assert app["signed_in"] is True
            signed_in = dt.datetime.fromisoformat(app["signed_in_at"])
            ends = dt.datetime.fromisoformat(app["session_ends_at"])
            assert ends - signed_in == dt.timedelta(days=7)
            assert app["last_used_at"] is not None

            resp = await admin.post(f"/admin/apps/{reg['client_id']}/sign-out", headers=ADMIN)
            assert resp.status_code == 200
            assert (await _initialize(mcp, tokens["access_token"])).status_code == 401
            refresh = await _token(
                mcp, reg, grant_type="refresh_token", refresh_token=tokens["refresh_token"]
            )
            assert refresh.status_code == 400
            [app] = (await admin.get("/admin/apps", headers=ADMIN)).json()["apps"]
            assert app["signed_in"] is False and app["session_ends_at"] is None
            assert (await admin.post("/admin/apps/nope/sign-out", headers=ADMIN)).status_code == 404

            state = json.loads(oauth_state_path(admin_settings).read_text())
            assert reg["client_id"] in state["clients"]
            assert not any(
                t["client_id"] == reg["client_id"] for t in state["access_tokens"].values()
            )

            verifier, challenge = _pkce()
            code = await _login(mcp, reg, challenge)
            again = await _token(
                mcp,
                reg,
                grant_type="authorization_code",
                code=code,
                redirect_uri=CALLBACK,
                code_verifier=verifier,
            )
            assert (await _initialize(mcp, again.json()["access_token"])).status_code == 200

    anyio.run(run)


def test_admin_signs_out_every_app(admin_settings: Settings) -> None:
    async def run() -> None:
        async with clients(admin_settings) as (mcp, admin):
            first_reg, first = await _sign_in(mcp)
            _, second = await _sign_in(mcp)
            resp = await admin.post("/admin/apps/sign-out-all", headers=ADMIN)
            assert resp.json() == {"signed_out": 2}
            for tokens in (first, second):
                assert (await _initialize(mcp, tokens["access_token"])).status_code == 401
            refresh = await _token(
                mcp, first_reg, grant_type="refresh_token", refresh_token=first["refresh_token"]
            )
            assert refresh.status_code == 400
            apps = (await admin.get("/admin/apps", headers=ADMIN)).json()["apps"]
            assert len(apps) == 2 and not any(a["signed_in"] for a in apps)

    anyio.run(run)


def test_last_used_is_saved_at_most_once_a_minute(
    admin_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [1_800_000_000.0]
    monkeypatch.setattr(O, "_now", lambda: clock[0])

    async def run() -> None:
        async with clients(admin_settings) as (mcp, _):
            reg, tokens = await _sign_in(mcp)
            path = oauth_state_path(admin_settings)

            def saved() -> float | None:
                return json.loads(path.read_text())["last_used"].get(reg["client_id"])

            await _initialize(mcp, tokens["access_token"])
            assert saved() == clock[0]
            first = clock[0]
            clock[0] += 30
            await _initialize(mcp, tokens["access_token"])
            assert saved() == first
            clock[0] += 31
            await _initialize(mcp, tokens["access_token"])
            assert saved() == clock[0]

    anyio.run(run)
