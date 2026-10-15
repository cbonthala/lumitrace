"""Connected AI apps: the Prism forwards ``/lens/apps`` to the Lens's private admin API."""

from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lumitrace.config import Settings
from lumitrace.lens.admin import build_admin_app
from lumitrace.lens.oauth import OwnerOAuthProvider
from tests.prism.conftest import AUTH, TOKEN

APPS = {
    "apps": [
        {
            "id": "app-1",
            "name": "Test AI",
            "hosts": ["ai-app.example"],
            "registered_at": "2026-10-01T09:00:00+00:00",
            "signed_in": True,
            "signed_in_at": "2026-10-10T09:00:00+00:00",
            "session_ends_at": "2026-10-17T09:00:00+00:00",
            "last_used_at": "2026-10-12T18:30:00+00:00",
        }
    ],
    "session_days": 7,
}


class FakeLens:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []
        self.status = 200
        self.down = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        path = request.url.raw_path.decode()
        self.calls.append((request.method, path, request.headers.get("authorization")))
        if self.status != 200:
            return httpx.Response(self.status, json={"detail": "nope"})
        if path == "/admin/apps":
            return httpx.Response(200, json=APPS)
        return httpx.Response(200, json={"ok": True})


def _with_lens(app: FastAPI, handler: object) -> None:
    app.state.lens_admin_transport = (
        handler if isinstance(handler, httpx.AsyncBaseTransport) else httpx.MockTransport(handler)
    )


def test_connected_apps_are_forwarded_to_the_lens(app: FastAPI, client: TestClient) -> None:
    lens = FakeLens()
    _with_lens(app, lens)
    assert client.get("/lens/apps").status_code == 401
    assert client.post("/lens/apps/sign-out-all").status_code == 401
    assert lens.calls == []

    assert client.get("/lens/apps", headers=AUTH).json() == APPS
    assert client.post("/lens/apps/app 1/sign-out", headers=AUTH).json() == {"ok": True}
    assert client.post("/lens/apps/sign-out-all", headers=AUTH).status_code == 200
    assert client.delete("/lens/apps/app-1", headers=AUTH).status_code == 404
    bearer = f"Bearer {TOKEN}"
    assert lens.calls == [
        ("GET", "/admin/apps", bearer),
        ("POST", "/admin/apps/app%201/sign-out", bearer),
        ("POST", "/admin/apps/sign-out-all", bearer),
    ]


def test_lens_failures_never_look_like_a_flash_sign_out(app: FastAPI, client: TestClient) -> None:
    lens = FakeLens()
    _with_lens(app, lens)
    lens.status = 401
    resp = client.get("/lens/apps", headers=AUTH)
    assert resp.status_code == 502 and "refused" in resp.json()["detail"]
    lens.status = 404
    assert client.post("/lens/apps/gone/sign-out", headers=AUTH).status_code == 404
    lens.status, lens.down = 200, True
    resp = client.get("/lens/apps", headers=AUTH)
    assert resp.status_code == 502 and "not reachable" in resp.json()["detail"]


def test_connected_apps_against_the_real_admin_api(
    app: FastAPI, client: TestClient, api_settings: Settings, tmp_path: Path
) -> None:
    provider = OwnerOAuthProvider(
        issuer_url="http://localhost:8002",
        resource_url="http://localhost:8002/mcp",
        owner_password="correct horse battery staple",
        state_path=tmp_path / "oauth.json",
    )
    _with_lens(app, httpx.ASGITransport(app=build_admin_app(api_settings, provider)))
    assert client.get("/lens/apps", headers=AUTH).json() == {"apps": [], "session_days": 7}
    assert client.post("/lens/apps/unknown/sign-out", headers=AUTH).status_code == 404
    assert client.post("/lens/apps/sign-out-all", headers=AUTH).json() == {"signed_out": 0}


def test_settings_tab_has_connected_apps(client: TestClient) -> None:
    page = client.get("/flash/").text
    assert "Connected AI apps" in page
    assert 'id="apps"' in page and 'id="apps-sign-out-all"' in page
    assert "/lens/apps" in client.get("/flash/app.js").text
