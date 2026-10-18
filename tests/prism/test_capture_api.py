from __future__ import annotations

import datetime as dt

from fastapi import FastAPI
from fastapi.testclient import TestClient

from lumitrace.config import Settings
from lumitrace.frames.dayfile import day_file_path, generated_snapshot_path, parse
from lumitrace.frames.storage.local import LocalStorage
from lumitrace.prism.app import create_app, format_location
from lumitrace.prism.inbox import CaptureStatus, Inbox, status_path
from lumitrace.prism.pipeline.processor import CaptureProcessor, CaptureRequest, UploadedFile
from tests.prism.conftest import AUTH, NudgeRecorder, image_bytes, poll_status, wait_idle

OCT10 = dt.date(2026, 10, 10)
EVENING = "2026-10-10T21:30:00-05:00"


def post_recording(client: TestClient, audio: bytes = b"Lunch with Maya. We had tacos.", **form):
    files = [("audio", ("Recording.m4a", audio, "audio/mp4"))]
    for i, photo in enumerate(form.pop("photos", [])):
        files.append(("photos[]", (f"IMG_{i}.png", photo, "image/png")))
    data = {"captured_at": EVENING, **form}
    return client.post("/recordings", data=data, files=files, headers=AUTH)


def read_day(storage: LocalStorage, day: dt.date = OCT10):
    return parse(storage.read_text(day_file_path(day)))


def test_recording_end_to_end(
    app: FastAPI, client: TestClient, api_storage: LocalStorage, nudges: NudgeRecorder
) -> None:
    resp = post_recording(
        client,
        photos=[image_bytes(), image_bytes()],
        lat="30.2672",
        lon="-97.7431",
        place="Austin",
        capture_id="phone-001",
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["capture_id"] == "phone-001"
    assert body["status"] == "queued"
    assert body["entry_date"] == "2026-10-10"
    assert body["duplicate"] is False
    assert body["status_url"] == "/captures/phone-001"
    assert "Saturday, October 10" in body["message"]

    wait_idle(app)
    status = client.get("/captures/phone-001", headers=AUTH).json()
    assert status["status"] == "done"
    assert status["day_file"] == "2026/10/2026-10-10/2026-10-10.md"
    assert status["audio"] == "2026-10-10-2130.m4a"
    assert status["photos"] == ["photo-01.jpg", "photo-02.jpg"]
    assert status["generation"] == "full"
    assert status["attempts"] == 1

    day = read_day(api_storage)
    assert day.title == "Saturday, October 10, 2026 · Taco day"
    assert day.journal == "## Summary\n\nA day with 1 entries."
    assert day.facts.people == ["Maya"]
    assert day.facts.meals[0].items == ["fish tacos"]
    assert "## At a glance" in api_storage.read_text(day_file_path(OCT10))
    assert day.meta.audio == ["2026-10-10-2130.m4a"]
    assert day.meta.photos == ["photo-01.jpg", "photo-02.jpg"]
    assert day.meta.prompt_version == "fill_day"
    assert day.meta.models_used == {"stt": "fake", "fill_day": "test/journal"}
    assert not day.is_user_edited()
    [capture] = day.captures
    assert capture.id == "phone-001"
    assert capture.text == "Lunch with Maya. We had tacos."
    assert capture.location == "Austin (30.26720, -97.74310)"
    assert capture.captured_at.isoformat() == "2026-10-10T21:30:00-05:00"

    folder = "2026/10/2026-10-10"
    assert (
        api_storage.read_bytes(f"{folder}/2026-10-10-2130.m4a") == b"Lunch with Maya. We had tacos."
    )
    assert api_storage.exists(f"{folder}/photo-02.jpg")
    assert api_storage.read_text(generated_snapshot_path(OCT10)) == api_storage.read_text(
        day_file_path(OCT10)
    )
    assert api_storage.list("_system/inbox") == []
    assert api_storage.exists(status_path("phone-001"))
    assert nudges.calls == [
        [day_file_path(OCT10), f"{folder}/2026-10-10-2130.m4a", f"{folder}/photo-01.jpg",
         f"{folder}/photo-02.jpg"]
    ]  # fmt: skip


def test_same_capture_id_is_stored_once(
    app: FastAPI, client: TestClient, api_storage: LocalStorage
) -> None:
    first = post_recording(client, capture_id="retry-me")
    assert first.status_code == 202
    second = post_recording(client, capture_id="retry-me")
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    wait_idle(app)
    third = post_recording(client, capture_id="retry-me")
    assert third.status_code == 200
    assert third.json()["status"] == "done"
    wait_idle(app)
    day = read_day(api_storage)
    assert [c.id for c in day.captures] == ["retry-me"]
    audio = [f for f in api_storage.list("2026/10/2026-10-10") if f.path.endswith(".m4a")]
    assert len(audio) == 1


def test_without_capture_id_each_post_is_new(app: FastAPI, client: TestClient, api_storage) -> None:
    a = post_recording(client).json()["capture_id"]
    b = post_recording(client).json()["capture_id"]
    assert a != b and a.startswith("20261010T213000-recording-")
    wait_idle(app)
    day = read_day(api_storage)
    assert len(day.captures) == 2
    assert day.meta.audio == ["2026-10-10-2130.m4a", "2026-10-10-2130-2.m4a"]


def test_rollover_before_4am_counts_as_previous_day(
    app: FastAPI, client: TestClient, api_storage: LocalStorage
) -> None:
    resp = post_recording(client, captured_at="2026-10-11T01:30:00-05:00")
    assert resp.json()["entry_date"] == "2026-10-10"
    wait_idle(app)
    day = read_day(api_storage)
    assert day.meta.audio == ["2026-10-10-0130.m4a"]
    late = post_recording(client, captured_at="2026-10-11T04:00:00-05:00")
    assert late.json()["entry_date"] == "2026-10-11"


def test_date_field_chooses_the_day(
    app: FastAPI, client: TestClient, api_storage: LocalStorage
) -> None:
    resp = post_recording(client, audio=b"Pancakes with Leo.", date="2026-10-08")
    assert resp.status_code == 202, resp.text
    assert resp.json()["entry_date"] == "2026-10-08"
    assert "Thursday, October 8" in resp.json()["message"]
    wait_idle(app)
    day = read_day(api_storage, dt.date(2026, 10, 8))
    assert day.meta.audio == ["2026-10-08-2130.m4a"]
    assert day.captures[0].captured_at.isoformat() == "2026-10-10T21:30:00-05:00"
    assert not api_storage.exists(day_file_path(OCT10))

    form = {"text": "Tea.", "captured_at": EVENING, "date": "2026-10-09"}
    assert client.post("/notes", data=form, headers=AUTH).json()["entry_date"] == "2026-10-09"
    note = {"text": "Tea.", "captured_at": EVENING, "date": "2026-10-09"}
    assert client.post("/notes", json=note, headers=AUTH).json()["entry_date"] == "2026-10-09"
    note["date"] = ""
    assert client.post("/notes", json=note, headers=AUTH).json()["entry_date"] == "2026-10-10"


def test_date_field_validation(client: TestClient, api_settings: Settings) -> None:
    note = {"text": "x", "captured_at": EVENING}
    for bad in ("10/08/2026", "2026-02-30", "yesterday"):
        resp = client.post("/notes", json={**note, "date": bad}, headers=AUTH)
        assert resp.status_code == 422
        assert "YYYY-MM-DD" in resp.text
    tomorrow = dt.datetime.now(api_settings.tz).date() + dt.timedelta(days=1)
    resp = client.post("/notes", json={**note, "date": tomorrow.isoformat()}, headers=AUTH)
    assert resp.status_code == 422
    assert "future" in resp.text


def test_captured_at_formats(client: TestClient, api_settings: Settings) -> None:
    naive = post_recording(client, captured_at="2026-10-10T23:00:00").json()
    assert naive["entry_date"] == "2026-10-10"
    utc = post_recording(client, captured_at="2026-10-11T08:30:00Z").json()  # 03:30 Chicago
    assert utc["entry_date"] == "2026-10-10"
    epoch = int(dt.datetime(2026, 10, 10, 12, tzinfo=api_settings.tz).timestamp())
    assert post_recording(client, captured_at=str(epoch)).json()["entry_date"] == "2026-10-10"
    now = post_recording(client, captured_at="").json()
    assert now["status"] == "queued"


def test_note_merges_into_the_same_day(
    app: FastAPI, client: TestClient, api_storage: LocalStorage, fake_llm
) -> None:
    post_recording(client, audio=b"Morning run along the river.", captured_at=EVENING)
    wait_idle(app)
    resp = client.post(
        "/notes",
        json={"text": "Tacos with Priya.", "captured_at": "2026-10-10T13:05:00-05:00"},
        headers=AUTH,
    )
    assert resp.status_code == 202
    wait_idle(app)
    day = read_day(api_storage)
    assert [c.kind for c in day.captures] == ["note", "recording"]  # sorted by time
    assert day.journal.startswith("## Summary\n\nA day with 1 entries.")
    assert day.journal.endswith("## Evening\n\n- You added another detail to the day.")
    assert "## Later" not in day.journal
    assert day.facts.people == ["Priya"]
    assert [activity.kind for activity in day.facts.activities] == ["run"]
    assert day.meta.models_used["stt"] == "fake"
    assert [c[0] for c in fake_llm.calls] == ["fill_day", "update_day"]
    fill, update = fake_llm.calls
    assert "Morning run" in fill[2][1]["content"]
    update_input = update[2][1]["content"]
    assert "Tacos with Priya." in update_input
    assert "Morning run" in update_input


def test_note_as_form_and_as_audio_clip(app: FastAPI, client: TestClient, api_storage) -> None:
    form = client.post(
        "/notes", data={"text": "Leo lost a tooth.", "captured_at": EVENING}, headers=AUTH
    )
    assert form.status_code == 202
    clip = client.post(
        "/notes",
        data={"captured_at": "2026-10-10T21:45:00-05:00"},
        files={"audio": ("clip.m4a", b"Spoken note about Maya.", "audio/mp4")},
        headers=AUTH,
    )
    assert clip.status_code == 202
    wait_idle(app)
    day = read_day(api_storage)
    assert [c.text for c in day.captures] == ["Leo lost a tooth.", "Spoken note about Maya."]
    assert day.captures[1].audio == "2026-10-10-2145.m4a"


def test_photo_only_note(app: FastAPI, client: TestClient, api_storage) -> None:
    resp = client.post(
        "/notes",
        data={"captured_at": EVENING},
        files=[("photos", ("IMG_1.heic", image_bytes(), "image/heic"))],
        headers=AUTH,
    )
    assert resp.status_code == 202
    wait_idle(app)
    status = client.get(f"/captures/{resp.json()['capture_id']}", headers=AUTH).json()
    assert (status["photos"], status["generation"]) == (["photo-01.jpg"], "skipped")
    assert read_day(api_storage).meta.photos == ["photo-01.jpg"]


def test_validation_errors(client: TestClient) -> None:
    no_audio = client.post("/recordings", data={"captured_at": EVENING}, headers=AUTH)
    assert no_audio.status_code == 422
    assert client.post("/notes", json={"captured_at": EVENING}, headers=AUTH).status_code == 422
    assert (
        client.post("/notes", json={"text": "x", "capture_id": "../etc"}, headers=AUTH).status_code
        == 422
    )
    assert (
        client.post("/notes", json={"text": "x", "lat": "north"}, headers=AUTH).status_code == 422
    )
    assert client.post("/notes", json={"text": "x", "lat": 91}, headers=AUTH).status_code == 422
    assert (
        client.post(
            "/notes", json={"text": "x", "captured_at": "yesterday"}, headers=AUTH
        ).status_code
        == 422
    )
    assert client.post("/notes", json=["x"], headers=AUTH).status_code == 422
    plain = client.post("/notes", content=b"hello", headers={**AUTH, "Content-Type": "text/plain"})
    assert plain.status_code == 415
    assert client.get("/captures/nope", headers=AUTH).status_code == 404
    assert client.get("/captures/..%2F..%2Fx", headers=AUTH).status_code == 404  # fmt: skip


def test_upload_size_limit(api_settings: Settings, processor: CaptureProcessor) -> None:
    settings = api_settings.model_copy(update={"api_max_upload_mb": 1})
    with TestClient(create_app(settings, processor=processor)) as client:
        resp = post_recording(client, audio=b"x" * (1024 * 1024 + 1))
        assert resp.status_code == 413


def test_failed_capture_is_retried_automatically(
    app: FastAPI, client: TestClient, processor: CaptureProcessor, api_storage
) -> None:
    real = processor.transcriber
    calls = {"n": 0}

    class Flaky:
        def transcribe(self, data: bytes, filename: str):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("speech service unreachable")
            return real.transcribe(data, filename)

    processor.transcriber = Flaky()
    post_recording(client, capture_id="flaky")
    status = poll_status(client, "flaky", "done")
    assert status["attempts"] == 2
    assert status["errors"] == []
    assert len(read_day(api_storage).captures) == 1


def test_exhausted_capture_can_be_resent_or_retried(
    app: FastAPI, client: TestClient, processor: CaptureProcessor, api_storage
) -> None:
    real = processor.transcriber

    class Down:
        def transcribe(self, data: bytes, filename: str):
            raise ConnectionError("speech service unreachable")

    processor.transcriber = Down()
    post_recording(client, capture_id="down")
    failed = poll_status(client, "down", "failed")
    assert failed["attempts"] == 2
    assert failed["errors"] == ["ConnectionError: speech service unreachable"]
    assert not api_storage.exists(day_file_path(OCT10))
    assert client.post("/captures/down/retry", headers=AUTH).status_code == 200
    poll_status(client, "down", "failed")

    processor.transcriber = real
    resent = post_recording(client, capture_id="down")
    assert resent.status_code == 202 and resent.json()["duplicate"] is False
    poll_status(client, "down", "done")
    assert client.post("/captures/down/retry", headers=AUTH).status_code == 409
    assert len(read_day(api_storage).captures) == 1


def test_inbox_is_resumed_on_startup(
    api_settings: Settings, processor: CaptureProcessor, api_storage: LocalStorage
) -> None:
    inbox = Inbox(api_storage)
    captured = dt.datetime(2026, 10, 10, 20, 0, tzinfo=api_settings.tz)

    def leave(capture_id: str, state: str | None) -> None:
        req = CaptureRequest(
            id=capture_id,
            kind="recording",
            received_at=captured,
            captured_at=captured,
            audio=UploadedFile(path=f"_system/inbox/{capture_id}/audio.m4a", filename="a.m4a"),
        )
        inbox.save(req, {req.audio.path: f"Entry {capture_id} with Leo.".encode()})
        if state:
            inbox.put_status(
                CaptureStatus(
                    capture_id=capture_id, kind="recording", status=state, entry_date=OCT10,
                    captured_at=captured, received_at=captured, attempts=1,
                )
            )  # fmt: skip

    leave("crashed-mid-way", "processing")
    leave("never-started", "queued")
    leave("no-status-yet", None)
    api_storage.write_bytes("_system/inbox/half-upload/audio.m4a", b"partial")

    app = create_app(api_settings, processor=processor)
    with TestClient(app) as client:
        wait_idle(app)
        for capture_id in ("crashed-mid-way", "never-started", "no-status-yet"):
            assert client.get(f"/captures/{capture_id}", headers=AUTH).json()["status"] == "done"
    day = read_day(api_storage)
    assert len(day.captures) == 3
    assert [f.path for f in api_storage.list("_system/inbox")] == [
        "_system/inbox/half-upload/audio.m4a"
    ]


def test_format_location() -> None:
    assert format_location("Austin", 30.26720, -97.7431) == "Austin (30.26720, -97.74310)"
    assert format_location(None, 1.0, 2.0) == "1.00000, 2.00000"
    assert format_location("  Austin \n TX ", None, None) == "Austin TX"
    assert format_location("", None, 2.0) is None
