"""The Flash web app: static files, username/password sign-in, session cookies, recent captures
and the weekly summary. All data is fictional."""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from lumitrace.config import Settings
from lumitrace.frames.dayfile import Capture, day_file_path, merge_capture, render
from lumitrace.frames.storage.local import LocalStorage
from lumitrace.prism import flash
from lumitrace.prism.app import create_app
from lumitrace.prism.auth import SESSION_COOKIE, login_problem, make_session, session_valid
from lumitrace.prism.flash import week_summary
from lumitrace.prism.pipeline.processor import CaptureProcessor
from tests.prism.conftest import AUTH, wait_idle

USERNAME = "sam"
PASSWORD = "correct horse battery"
TZ = dt.timezone(dt.timedelta(hours=-5))


@pytest.fixture
def flash_settings(api_settings: Settings) -> Settings:
    return api_settings.model_copy(
        update={"flash_username": USERNAME, "flash_password": SecretStr(PASSWORD)}
    )


@pytest.fixture
def flash_app(flash_settings: Settings, processor: CaptureProcessor) -> FastAPI:
    return create_app(flash_settings, processor=processor, retry_delays=(0.05,))


@pytest.fixture
def flash_client(flash_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(flash_app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def no_login_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flash, "FAILURE_DELAY", 0)


def sign_in(client: TestClient, username: str = USERNAME, password: str = PASSWORD) -> str:
    resp = client.post("/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    value = resp.cookies[SESSION_COOKIE]
    client.cookies.clear()
    return value


def with_session(value: str, **headers: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE}={value}", **headers}


def write_day(storage: LocalStorage, day: dt.date, captures: int = 1) -> None:
    day_file = None
    for n in range(captures):
        at = dt.datetime.combine(day, dt.time(9 + n), TZ)
        capture = Capture(id=f"c-{day}-{n}", kind="note", captured_at=at, text="A quiet walk.")
        day_file = merge_capture(day_file, capture, day)
    assert day_file is not None
    storage.write_text(day_file_path(day), render(day_file))


def test_web_app_is_served_without_a_login(client: TestClient) -> None:
    page = client.get("/flash/")
    assert page.status_code == 200
    assert "Lumitrace Flash" in page.text
    assert 'rel="manifest"' in page.text and 'rel="apple-touch-icon"' in page.text
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    for path in ("/flash", "/"):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 307
        assert resp.headers["location"] == "/flash/"
    manifest = client.get("/flash/manifest.webmanifest")
    assert manifest.headers["content-type"].startswith("application/manifest+json")
    assert manifest.json()["start_url"] == "/flash/"
    for asset in ("app.js", "app.css", "sw.js", "icon-180.png", "icon-512.png"):
        assert client.get(f"/flash/{asset}").status_code == 200, asset


def test_sign_in_is_off_until_configured(client: TestClient) -> None:
    resp = client.post("/login", json={"username": USERNAME, "password": PASSWORD})
    assert resp.status_code == 503
    assert "LUMITRACE_FLASH_USERNAME" in resp.json()["detail"]
    session = client.get("/session").json()
    assert session["signed_in"] is False
    assert session["sign_in_available"] is False


def test_sign_in_sets_a_session_cookie_that_works_like_the_token(
    flash_app: FastAPI, flash_client: TestClient
) -> None:
    resp = flash_client.post("/login", json={"username": USERNAME, "password": PASSWORD})
    assert resp.status_code == 200
    assert resp.json()["username"] == USERNAME
    cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "secure" in cookie
    assert f"max-age={90 * 86400}" in cookie
    value = resp.cookies[SESSION_COOKIE]
    flash_client.cookies.clear()

    session = flash_client.get("/session", headers=with_session(value)).json()
    assert session["signed_in"] is True and session["username"] == USERNAME

    note = flash_client.post(
        "/notes", json={"text": "Walked to the lake."}, headers=with_session(value)
    )
    assert note.status_code == 202, note.text
    capture_id = note.json()["capture_id"]
    wait_idle(flash_app)
    status = flash_client.get(f"/captures/{capture_id}", headers=with_session(value))
    assert status.json()["status"] == "done"
    assert flash_client.get("/summary", headers=with_session(value)).status_code == 200
    assert flash_client.get("/captures", headers=with_session(value)).status_code == 200


def test_wrong_password_and_lockout(flash_client: TestClient) -> None:
    resp = flash_client.post("/login", json={"username": "maya", "password": PASSWORD})
    assert resp.status_code == 401
    assert SESSION_COOKIE not in resp.cookies
    for _ in range(4):
        resp = flash_client.post("/login", json={"username": USERNAME, "password": "guess-1234"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "wrong username or password"
    locked = flash_client.post("/login", json={"username": USERNAME, "password": PASSWORD})
    assert locked.status_code == 429


def test_bad_or_old_sessions_are_refused(
    flash_settings: Settings, flash_client: TestClient, processor: CaptureProcessor
) -> None:
    good = sign_in(flash_client)
    expired, _ = make_session(flash_settings, now=time.time() - 91 * 86400)
    tampered = good[:-1] + ("0" if good[-1] != "0" else "1")
    for value in (expired, tampered, "v1.9999999999.abc", "nonsense", ""):
        resp = flash_client.post("/notes", json={"text": "hi"}, headers=with_session(value))
        assert resp.status_code == 401, value
        session = flash_client.get("/session", headers=with_session(value)).json()
        assert session["signed_in"] is False

    changed = flash_settings.model_copy(update={"flash_password": SecretStr("a new password 42")})
    assert session_valid(flash_settings, good)
    assert not session_valid(changed, good)
    with TestClient(create_app(changed, processor=processor)) as client:
        resp = client.post("/notes", json={"text": "hi"}, headers=with_session(good))
        assert resp.status_code == 401


def test_cross_site_requests_with_a_session_are_refused(flash_client: TestClient) -> None:
    value = sign_in(flash_client)
    cross = with_session(value, **{"Sec-Fetch-Site": "cross-site"})
    assert flash_client.post("/notes", json={"text": "hi"}, headers=cross).status_code == 403
    assert flash_client.get("/captures", headers=cross).status_code == 200
    same = with_session(value, **{"Sec-Fetch-Site": "same-origin"})
    assert flash_client.post("/notes", json={"text": "hi"}, headers=same).status_code == 202
    bearer = {**AUTH, "Sec-Fetch-Site": "cross-site"}
    assert flash_client.post("/notes", json={"text": "hi"}, headers=bearer).status_code == 202
    login = flash_client.post(
        "/login",
        json={"username": USERNAME, "password": PASSWORD},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert login.status_code == 403


def test_logout_clears_the_cookie(flash_client: TestClient) -> None:
    resp = flash_client.post("/logout")
    assert resp.status_code == 204
    cookie = resp.headers["set-cookie"].lower()
    assert cookie.startswith(f"{SESSION_COOKIE}=") and "max-age=0" in cookie


def test_login_problem(flash_settings: Settings) -> None:
    assert login_problem(flash_settings) is None
    for update in (
        {"flash_username": " "},
        {"flash_password": SecretStr("change-me")},
        {"flash_password": SecretStr("short")},
        {"api_token": SecretStr("short")},
    ):
        assert login_problem(flash_settings.model_copy(update=update)) is not None, update
    off = flash_settings.model_copy(update={"flash_username": ""})
    assert not session_valid(off, make_session(off)[0])


def test_recent_captures_newest_first(app: FastAPI, client: TestClient) -> None:
    assert client.get("/captures").status_code == 401
    for text, at in (("Morning tea.", "08:00"), ("Evening run.", "19:30"), ("Lunch.", "12:15")):
        resp = client.post(
            "/notes",
            json={"text": text, "captured_at": f"2026-10-12T{at}:00-05:00"},
            headers=AUTH,
        )
        assert resp.status_code == 202
    wait_idle(app)
    listed = client.get("/captures", headers=AUTH).json()
    assert [c["captured_at"][11:16] for c in listed] == ["19:30", "12:15", "08:00"]
    assert {c["status"] for c in listed} == {"done"}
    assert "text" not in listed[0]
    assert len(client.get("/captures?limit=2", headers=AUTH).json()) == 2
    assert client.get("/captures?days=0", headers=AUTH).status_code == 422


def test_week_summary_counts_days_captures_and_streak(storage: LocalStorage) -> None:
    today = dt.date(2026, 10, 13)
    for back, captures in ((0, 1), (1, 2), (2, 1), (4, 1), (10, 1)):
        write_day(storage, today - dt.timedelta(days=back), captures)
    summary = week_summary(storage, today)
    assert summary.days == 7
    assert summary.days_logged == 4
    assert summary.captures == 5
    assert summary.streak == 3
    assert summary.logged_dates[0] == dt.date(2026, 10, 9)


def test_streak_waits_for_today_and_crosses_months(storage: LocalStorage) -> None:
    for day in (dt.date(2026, 10, 30), dt.date(2026, 10, 31), dt.date(2026, 11, 1)):
        write_day(storage, day)
    summary = week_summary(storage, dt.date(2026, 11, 2))
    assert summary.streak == 3
    assert summary.days_logged == 3
    assert week_summary(storage, dt.date(2026, 11, 3)).streak == 0
    empty = week_summary(LocalStorage(storage.root / "empty"), dt.date(2026, 11, 2))
    assert (empty.days_logged, empty.captures, empty.streak) == (0, 0, 0)
