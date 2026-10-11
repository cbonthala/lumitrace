from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import SecretStr

from lumen.config import Settings
from lumen.prism.app import create_app
from lumen.prism.auth import token_problem
from lumen.prism.pipeline.processor import CaptureProcessor
from tests.prism.conftest import AUTH, TOKEN


def test_health_needs_no_token(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_missing_token_is_rejected(client: TestClient) -> None:
    resp = client.post("/notes", json={"text": "hello"})
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


def test_wrong_token_and_scheme_are_rejected(client: TestClient) -> None:
    for header in (f"Bearer {TOKEN}x", f"Basic {TOKEN}", TOKEN, "Bearer "):
        resp = client.post("/notes", json={"text": "hello"}, headers={"Authorization": header})
        assert resp.status_code == 401, header
    assert (
        client.get("/captures/anything", headers={"Authorization": "Bearer no"}).status_code == 401
    )


def test_right_token_is_accepted(client: TestClient) -> None:
    assert client.post("/notes", json={"text": "hello"}, headers=AUTH).status_code == 202
    lower = {"authorization": f"bearer {TOKEN}"}
    assert client.post("/notes", json={"text": "again"}, headers=lower).status_code == 202


def test_unconfigured_token_fails_closed(
    api_settings: Settings, processor: CaptureProcessor
) -> None:
    settings = api_settings.model_copy(update={"api_token": SecretStr("")})
    with TestClient(create_app(settings, processor=processor)) as client:
        resp = client.post("/notes", json={"text": "hello"}, headers={"Authorization": "Bearer "})
        assert resp.status_code == 503


def test_placeholder_or_short_token_fails_closed(
    api_settings: Settings, processor: CaptureProcessor
) -> None:
    for weak in ("change-me", "short-token"):
        settings = api_settings.model_copy(update={"api_token": SecretStr(weak)})
        with TestClient(create_app(settings, processor=processor)) as client:
            resp = client.post(
                "/notes", json={"text": "hello"}, headers={"Authorization": f"Bearer {weak}"}
            )
            assert resp.status_code == 503, weak
            assert client.get("/health").status_code == 200


def test_token_problem() -> None:
    assert token_problem("") is not None
    assert token_problem("change-me") is not None
    assert token_problem("short") is not None
    assert token_problem("a" * 32) is None
