"""The Flash web app: static files, username/password sign-in, session cookies, recent captures
and the weekly summary. All data is fictional."""

from __future__ import annotations

import datetime as dt
import re
import time
from collections.abc import Iterator
from types import NoneType, UnionType
from typing import Annotated, Union, get_args, get_origin

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, SecretStr

from lumitrace.config import Settings
from lumitrace.frames import daycontent as dc
from lumitrace.frames.dayfile import (
    Capture,
    DayFile,
    FrontMatter,
    day_file_path,
    merge_capture,
    parse,
    render,
)
from lumitrace.frames.storage.local import LocalStorage
from lumitrace.prism import flash
from lumitrace.prism.app import create_app
from lumitrace.prism.auth import SESSION_COOKIE, login_problem, make_session, session_valid
from lumitrace.prism.flash import generation_for_display, week_summary
from lumitrace.prism.inbox import CaptureStatus
from lumitrace.prism.pipeline.processor import CaptureProcessor
from tests.prism.conftest import AUTH, wait_idle

USERNAME = "sam"
PASSWORD = "correct horse battery"
TZ = dt.timezone(dt.timedelta(hours=-5))

# Speakable Format 6 fields. Tags are derived; pregnant_person comes from the family file.
_PROMPT_SKIP = frozenset({"tags", "pregnancy_baby.pregnant_person"})
_PROMPT_ATOMIC = {dc.Meal, dc.Rating, dc.PlaceContext, dc.PersonContext, dc.ExerciseMovement}


def _unwrap_annotation(annotation: object) -> object:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Annotated:
        return _unwrap_annotation(args[0])
    if origin in (Union, UnionType):
        useful = [item for item in args if item is not NoneType]
        return _unwrap_annotation(useful[0]) if len(useful) == 1 else annotation
    if origin is list and args:
        return _unwrap_annotation(args[0])
    return annotation


def day_file_prompt_fields() -> set[str]:
    """Every DayContent path the record sheet should prompt for, except derived skips."""

    def paths(model: type[BaseModel], prefix: str = "") -> list[str]:
        found: list[str] = []
        for name, info in model.model_fields.items():
            path = f"{prefix}.{name}" if prefix else name
            inner = _unwrap_annotation(info.annotation)
            nested = (
                isinstance(inner, type)
                and issubclass(inner, BaseModel)
                and inner not in _PROMPT_ATOMIC
            )
            if nested:
                found.extend(paths(inner, path))
            else:
                found.append(path)
        return found

    return {path for path in paths(dc.DayContent) if path not in _PROMPT_SKIP}


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


def test_how_it_works_diagram_and_design_page(client: TestClient) -> None:
    page = client.get("/flash/").text
    assert 'data-go="design"' in page and 'data-tab="design"' in page
    assert page.count('src="flow.svg"') == 1
    diagram = client.get("/flash/flow.svg")
    assert diagram.status_code == 200
    assert diagram.headers["content-type"].startswith("image/svg+xml")
    for name in ("Flash", "Prism", "Frames", "Spectrum", "Lens"):
        assert f">{name}</text>" in diagram.text
    assert "<script" not in diagram.text


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


def test_capture_status_chip_matches_the_journal(client: TestClient) -> None:
    script = client.get("/flash/app.js").text
    assert "function statusChip" in script
    assert "Transcribing…" in script and "Not in journal" in script and "In journal" in script
    assert "Writing journal" not in script
    assert 'IN_JOURNAL = new Set(["full", "update", "unchanged"])' in script


def test_capture_list_follows_the_journal(flash_app: FastAPI, flash_client: TestClient) -> None:
    headers = with_session(sign_in(flash_client))
    sent = flash_client.post(
        "/notes",
        json={"text": "Tea with Maya.", "captured_at": "2026-10-17T10:00:00-05:00"},
        headers=headers,
    )
    assert sent.status_code == 202, sent.text
    capture_id = sent.json()["capture_id"]
    wait_idle(flash_app)
    listed = flash_client.get("/captures", headers=headers).json()
    saved = next(row for row in listed if row["capture_id"] == capture_id)
    assert saved["status"] == "done" and saved["generation"] == "deferred"

    written = flash_client.post("/journal", json={"date": "2026-10-17"}, headers=headers)
    assert written.status_code == 200 and written.json()["status"] == "full"
    listed = flash_client.get("/captures", headers=headers).json()
    included = next(row for row in listed if row["capture_id"] == capture_id)
    assert included["generation"] == "unchanged"

    written_at = dt.datetime(2026, 10, 17, 20, tzinfo=dt.UTC)
    day = DayFile(
        meta=FrontMatter(
            date=dt.date(2026, 10, 17),
            generated_at=written_at,
            generated_source_hash="not-the-current-source",
        )
    )
    base = dict(
        capture_id="later",
        kind="note",
        status="done",
        entry_date=dt.date(2026, 10, 17),
        captured_at=written_at,
        received_at=written_at,
        generation="deferred",
    )
    before = CaptureStatus(**base, updated_at=written_at - dt.timedelta(minutes=5))
    after = CaptureStatus(**base, updated_at=written_at + dt.timedelta(minutes=5))
    assert generation_for_display(before, day) == "unchanged"
    assert generation_for_display(after, day) == "deferred"


def test_home_button_and_history_grouped_by_day(client: TestClient) -> None:
    page = client.get("/flash/").text
    script = client.get("/flash/app.js").text
    assert 'id="home"' in page and 'aria-label="Home"' in page and 'data-go="capture"' in page
    assert "day-group" in script and "generateJournal" in script
    assert "Generate journal for" in script


def test_generate_journal_writes_the_day_from_saved_recordings(
    flash_app: FastAPI, flash_client: TestClient, api_storage: LocalStorage, fake_llm
) -> None:
    assert flash_client.post("/journal", json={}).status_code == 401
    headers = with_session(sign_in(flash_client))
    for text, at in (("Run with Maya.", "10:00"), ("Tacos with Leo.", "12:15")):
        resp = flash_client.post(
            "/notes",
            json={"text": text, "captured_at": f"2026-10-17T{at}:00-05:00"},
            headers=headers,
        )
        assert resp.status_code == 202, resp.text
    wait_idle(flash_app)
    saved = parse(api_storage.read_text(day_file_path(dt.date(2026, 10, 17))))
    assert saved.journal == ""
    assert fake_llm.calls == []

    written = flash_client.post("/journal", json={"date": "2026-10-17"}, headers=headers)
    assert written.status_code == 200, written.text
    body = written.json()
    assert body["entry_date"] == "2026-10-17" and body["status"] == "full"
    assert body["message"].startswith("Journal written for")
    assert "Maya" not in body["message"] and "Tacos" not in body["message"]
    day = parse(api_storage.read_text(day_file_path(dt.date(2026, 10, 17))))
    assert day.content.timeline.time_not_stated == ["A day with 2 entries."]
    assert [person.name for person in day.content.timeline.context.people_met] == ["Maya", "Leo"]
    assert "## Day timeline" in api_storage.read_text(day_file_path(dt.date(2026, 10, 17)))
    assert fake_llm.tasks() == ["fill_day"]

    again = flash_client.post("/journal", json={"date": "2026-10-17"}, headers=headers)
    assert again.status_code == 200 and again.json()["status"] == "unchanged"
    assert "already up to date" in again.json()["message"]
    assert fake_llm.tasks() == ["fill_day"]

    future = flash_client.post("/journal", json={"date": "2026-10-18"}, headers=headers)
    assert future.status_code == 422
    empty = flash_client.post("/journal", json={"date": "2026-10-01"}, headers=headers)
    assert empty.status_code == 200 and empty.json()["status"] == "skipped"
    assert "Nothing to write" in empty.json()["message"]


def test_record_prompt_covers_every_day_file_field(client: TestClient) -> None:
    page = client.get("/flash/").text
    script = client.get("/flash/app.js").text
    found = set(re.findall(r'data-field="([^"]+)"', page))
    expected = day_file_prompt_fields()
    missing = sorted(expected - found)
    extra = sorted(found - expected)
    assert not missing, f"prompt sheet missing day-file fields: {missing}"
    assert not extra, f"prompt sheet has unknown fields: {extra}"
    assert 'id="prompt-scrim"' in page and 'id="prompt-talk"' in page
    assert 'id="prompt-stop"' in page and 'id="prompt-live-head"' in page
    assert 'id="prompt-pause"' in page and 'id="prompt-discard"' in page
    assert 'id="prompt-map"' in page
    assert "Skip, just record" not in page
    toggle = script[script.index("function toggleRecording") : script.index("function togglePause")]
    assert "openPromptSheet" in toggle
    start = script[
        script.index("function beginRecordingFromPrompt") : script.index("function toggleRecording")
    ]
    assert "closePromptSheet" not in start
    assert "classList.toggle(\"said\")" in script
    assert "function startRecording" in script


def test_recording_is_reviewed_before_it_is_sent(client: TestClient) -> None:
    page = client.get("/flash/").text
    script = client.get("/flash/app.js").text
    for element_id in (
        "pause-btn",
        "play-btn",
        "card-send",
        "review-discard",
        "discard-btn",
        "crop-start",
        "crop-end",
    ):
        assert f'id="{element_id}"' in page
    assert "openReview" in script and "trimmedBlob" in script and "sendPhotosOnly" in script
    assert "Stop and send" not in script


def test_uploaded_voice_memo_is_sent_like_a_recording(app: FastAPI, client: TestClient) -> None:
    page = client.get("/flash/").text
    assert 'id="rec-upload"' in page and 'accept="audio/*' in page
    assert "uploadAudio" in client.get("/flash/app.js").text
    resp = client.post(
        "/recordings",
        data={"captured_at": "2026-10-08T18:05:00-05:00", "capture_id": "web-memo-1"},
        files=[("audio", ("audio.mp3", b"A walk by the lake with Leo.", "audio/mpeg"))],
        headers=AUTH,
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["entry_date"] == "2026-10-08"
    wait_idle(app)
    status = client.get("/captures/web-memo-1", headers=AUTH).json()
    assert status["status"] == "done"
    assert status["day_file"] == "2026/10/2026-10-08/2026-10-08.md"


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
