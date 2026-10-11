from __future__ import annotations

import datetime as dt
import json

from pydantic import BaseModel, ValidationError

from bookshelf.books.storage.local import LocalStorage
from bookshelf.config import Settings
from bookshelf.typewriter.pipeline.activity import (
    ActivityLog,
    ActivityRecord,
    activity_path,
    safe_error,
)
from bookshelf.typewriter.pipeline.processor import CaptureProcessor, CaptureRequest, UploadedFile

SECRET_WORDS = "Maya said the secret password is pineapple"


def test_one_line_per_capture_without_content(
    processor: CaptureProcessor, api_settings: Settings, api_storage: LocalStorage
) -> None:
    at = dt.datetime(2026, 10, 10, 21, 30, tzinfo=api_settings.tz)
    api_storage.write_bytes("_system/inbox/r/audio.m4a", SECRET_WORDS.encode())
    processor.process(
        CaptureRequest(
            id="r",
            kind="recording",
            received_at=at,
            captured_at=at,
            location="Austin",
            audio=UploadedFile(path="_system/inbox/r/audio.m4a", filename="a.m4a"),
        )
    )
    processor.process(
        CaptureRequest(
            id="n", kind="note", received_at=at, captured_at=at, text="Tacos with Priya at noon."
        )
    )
    raw = api_storage.read_text("_system/activity/2026/10.jsonl")
    lines = raw.splitlines()
    assert len(lines) == 2
    for forbidden in ("pineapple", "Maya", "Priya", "Tacos", "Austin", "Summary", "fish tacos"):
        assert forbidden not in raw, forbidden

    record = json.loads(lines[0])
    assert record["capture_id"] == "r"
    assert record["status"] == "done"
    assert record["entry_date"] == "2026-10-10"
    assert record["generation"] == "full"
    assert record["models"] == {
        "stt": "fake",
        "extract_facts": "test/extract",
        "write_journal": "test/journal",
    }
    assert record["prompt_versions"] == {"extract_facts": "v1", "write_journal": "v1"}
    names = [s["name"] for s in record["steps"]]
    assert names == [
        "compress_audio",
        "transcribe",
        "write_day",
        "extract_facts",
        "write_journal",
        "write_day",
        "nudge",
    ]
    assert all(isinstance(s["ms"], int) for s in record["steps"])
    transcribe = record["steps"][1]
    assert transcribe["detail"] == {"audio_bytes": len(SECRET_WORDS), "chars": len(SECRET_WORDS)}
    assert "errors" in record and record["errors"] == []

    note = json.loads(lines[1])
    assert "stt" not in note["models"]
    assert note["steps"][0]["name"] == "write_day"


def test_cost_is_summed_when_known() -> None:
    record = ActivityRecord(capture_id="x", kind="note")
    with record.step("extract_facts") as step:
        step.cost_usd = 0.0012
    with record.step("write_journal") as step:
        step.cost_usd = 0.003
    with record.step("nudge"):
        pass
    record.finish("done")
    assert record.cost_usd == 0.0042


def test_failed_step_is_recorded_and_reraised() -> None:
    record = ActivityRecord(capture_id="x", kind="note")
    try:
        with record.step("transcribe"):
            raise ConnectionError("no route to host")
    except ConnectionError:
        pass
    assert record.steps[0].ok is False
    assert record.errors == ["transcribe: ConnectionError: no route to host"]


def test_append_keeps_existing_lines(api_storage: LocalStorage) -> None:
    log = ActivityLog(api_storage)
    when = dt.datetime(2026, 12, 31, 23, 0, tzinfo=dt.UTC)
    path = activity_path(when)
    assert path == "_system/activity/2026/12.jsonl"
    api_storage.write_text(path, '{"capture_id": "old"}')
    record = ActivityRecord(capture_id="new", kind="note", started_at=when)
    assert log.append(record) == path
    assert [
        json.loads(line)["capture_id"] for line in api_storage.read_text(path).splitlines()
    ] == [
        "old",
        "new",
    ]


def test_append_never_raises() -> None:
    class Broken:
        def read_text(self, path: str) -> str:
            raise RuntimeError("drive down")

    assert ActivityLog(Broken()).append(ActivityRecord(capture_id="x", kind="note")) is None  # type: ignore[arg-type]


def test_safe_error_hides_model_output() -> None:
    class Facts(BaseModel):
        mood_score: int

    try:
        Facts.model_validate({"mood_score": "Maya was sad because of the secret"})
    except ValidationError as exc:
        text = safe_error(exc)
    assert "Maya" not in text and "1 validation error" in text
    try:
        json.loads("Maya says hi")
    except json.JSONDecodeError as exc:
        assert "Maya" not in safe_error(exc)
    assert len(safe_error(RuntimeError("x" * 1000))) < 250
