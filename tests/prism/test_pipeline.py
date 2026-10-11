"""CaptureProcessor without HTTP: edit protection, fallbacks, failures, re-processing."""

from __future__ import annotations

import datetime as dt
import json

import pytest

from lumen.config import Settings
from lumen.frames.dayfile import day_file_path, generated_snapshot_path, parse, render
from lumen.frames.storage.local import LocalStorage
from lumen.prism.pipeline.processor import CaptureProcessor, CaptureRequest, UploadedFile
from tests.prism.conftest import NudgeRecorder

OCT10 = dt.date(2026, 10, 10)


def make_request(
    settings: Settings,
    storage: LocalStorage,
    capture_id: str,
    *,
    hour: int = 21,
    minute: int = 30,
    spoken: str | None = None,
    text: str = "",
    kind: str = "recording",
) -> CaptureRequest:
    at = dt.datetime(2026, 10, 10, hour, minute, tzinfo=settings.tz)
    audio = None
    if spoken is not None:
        path = f"_system/inbox/{capture_id}/audio.m4a"
        storage.write_bytes(path, spoken.encode())
        audio = UploadedFile(path=path, filename="Recording.m4a", size=len(spoken))
    return CaptureRequest(
        id=capture_id, kind=kind, received_at=at, captured_at=at, text=text, audio=audio
    )


def owner_edits(storage: LocalStorage, change) -> None:
    path = day_file_path(OCT10)
    day = parse(storage.read_text(path))
    change(day)
    storage.write_text(path, render(day))


def test_edited_day_gets_additive_update(
    processor: CaptureProcessor, api_settings: Settings, api_storage: LocalStorage, fake_llm
) -> None:
    first = processor.process(make_request(api_settings, api_storage, "a", spoken="Run with Maya."))
    assert first.generation == "full"

    def edit(day) -> None:
        day.journal = "## Summary\n\nMy own words about the run."
        day.meta.mood = "proud"
        day.notes = "Private thought."

    owner_edits(api_storage, edit)
    second = processor.process(
        make_request(api_settings, api_storage, "b", hour=22, kind="note", text="Tacos with Leo.")
    )
    assert second.generation == "additive"
    day = parse(api_storage.read_text(day_file_path(OCT10)))
    assert day.journal.startswith("## Summary\n\nMy own words about the run.")
    assert day.journal.endswith("### 22:30 · Quick Note\n\nLater you added a quick note.")
    assert day.meta.mood == "proud"
    assert day.meta.people == ["Maya", "Leo"]
    assert day.notes == "Private thought."
    assert day.is_user_edited()
    assert day.meta.prompt_version == "extract_facts-v1+journal_addendum-v1"
    assert day.meta.models_used["journal_addendum"] == "test/journal"
    assert day.meta.models_used["stt"] == "fake"
    addendum_call = next(c for c in fake_llm.calls if c[0] == "journal_addendum")
    assert "My own words about the run." in addendum_call[2][1]["content"]
    facts_call = [c for c in fake_llm.calls if c[0] == "extract_facts"][-1]
    assert "Run with Maya." not in facts_call[2][1]["content"]  # only the new entry


def test_edit_during_generation_is_not_overwritten(
    processor: CaptureProcessor, api_settings: Settings, api_storage: LocalStorage, fake_llm
) -> None:
    processor.process(make_request(api_settings, api_storage, "a", spoken="Run with Maya."))

    def edit_once(task: str) -> None:
        if task == "write_journal" and fake_llm.before_reply is not None:
            fake_llm.before_reply = None

            def change(day) -> None:
                day.journal = "Typed while the AI was busy."

            owner_edits(api_storage, change)

    fake_llm.before_reply = edit_once
    result = processor.process(
        make_request(api_settings, api_storage, "b", hour=22, kind="note", text="Tacos.")
    )
    assert result.generation == "additive"
    day = parse(api_storage.read_text(day_file_path(OCT10)))
    assert day.journal.startswith("Typed while the AI was busy.")
    assert len(day.captures) == 2


def test_fallback_model_is_used_and_recorded(
    processor: CaptureProcessor, api_settings: Settings, api_storage: LocalStorage, fake_llm
) -> None:
    fake_llm.fail_models.add("test/extract")
    fake_llm.bad_json_models.add("test/journal")
    result = processor.process(make_request(api_settings, api_storage, "a", spoken="Maya."))
    assert result.generation == "full"
    day = parse(api_storage.read_text(day_file_path(OCT10)))
    assert day.meta.models_used["extract_facts"] == "test/fallback"
    assert day.meta.models_used["write_journal"] == "test/fallback"
    assert day.meta.people == ["Maya"]
    record = json.loads(api_storage.read_text("_system/activity/2026/10.jsonl").splitlines()[-1])
    steps = {s["name"]: s for s in record["steps"]}
    attempts = steps["extract_facts"]["detail"]["attempts"]
    assert [(a["model"], a["ok"]) for a in attempts] == [
        ("test/extract", False),
        ("test/fallback", True),
    ]
    assert attempts[0]["error"] == "RuntimeError: provider unavailable"
    assert "invalid JSON" in steps["write_journal"]["detail"]["attempts"][0]["error"]


def test_ai_failure_still_saves_the_transcript(
    processor: CaptureProcessor, api_settings: Settings, api_storage: LocalStorage, fake_llm
) -> None:
    fake_llm.fail_models |= {"test/extract", "test/journal", "test/fallback"}
    result = processor.process(make_request(api_settings, api_storage, "a", spoken="Run."))
    assert result.generation == "failed"
    assert result.errors == [
        "extract_facts: all models failed",
        "write_journal: all models failed",
    ]
    day = parse(api_storage.read_text(day_file_path(OCT10)))
    assert day.captures[0].text == "Run."
    assert day.journal == ""
    assert api_storage.exists(generated_snapshot_path(OCT10))


def test_transcription_failure_writes_nothing(
    processor: CaptureProcessor, api_settings: Settings, api_storage: LocalStorage
) -> None:
    class Broken:
        def transcribe(self, data: bytes, filename: str):
            raise TimeoutError("took too long")

    processor.transcriber = Broken()
    with pytest.raises(TimeoutError):
        processor.process(make_request(api_settings, api_storage, "a", spoken="Hi."))
    assert api_storage.list("2026") == []
    record = json.loads(api_storage.read_text("_system/activity/2026/10.jsonl"))
    assert record["status"] == "failed"
    assert record["errors"] == ["transcribe: TimeoutError: took too long"]


def test_nudge_failure_does_not_fail_the_capture(
    processor: CaptureProcessor,
    api_settings: Settings,
    api_storage: LocalStorage,
    nudges: NudgeRecorder,
) -> None:
    nudges.raise_error = True
    result = processor.process(make_request(api_settings, api_storage, "a", text="x", kind="note"))
    assert result.generation == "full"
    assert nudges.calls == [[day_file_path(OCT10)]]


def test_reprocessing_a_saved_capture_does_not_duplicate_it(
    processor: CaptureProcessor, api_settings: Settings, api_storage: LocalStorage
) -> None:
    req = make_request(api_settings, api_storage, "a", spoken="Run.")
    processor.process(req)
    again = processor.process(req)
    assert again.audio == "2026-10-10-2130.m4a"
    assert "capture already in the day file; regenerating only" in again.warnings
    day = parse(api_storage.read_text(day_file_path(OCT10)))
    assert len(day.captures) == 1
    assert [f.path for f in api_storage.list("2026") if f.path.endswith(".m4a")] == [
        "2026/10/2026-10-10/2026-10-10-2130.m4a"
    ]


def test_empty_transcript_skips_generation(
    processor: CaptureProcessor, api_settings: Settings, api_storage: LocalStorage, fake_llm
) -> None:
    class Silent:
        def transcribe(self, data: bytes, filename: str):
            from lumen.prism.pipeline.stt import Transcript

            return Transcript(text="", model="fake")

    processor.transcriber = Silent()
    result = processor.process(make_request(api_settings, api_storage, "a", spoken="..."))
    assert result.generation == "skipped"
    assert fake_llm.calls == []


def test_fake_llm_model_runs_offline(
    api_settings: Settings, api_storage: LocalStorage, nudges: NudgeRecorder
) -> None:
    settings = api_settings.model_copy(
        update={
            "llm_extract_facts_model": "fake",
            "llm_write_journal_model": "fake",
            "llm_fallback_model": "fake",
        }
    )
    processor = CaptureProcessor(settings, api_storage, nudge=nudges)
    result = processor.process(
        make_request(settings, api_storage, "a", text="Quiet day.", kind="note")
    )
    assert result.generation == "full"
    day = parse(api_storage.read_text(day_file_path(OCT10)))
    assert day.journal == "## Summary\n\nQuiet day."
    assert day.meta.models_used == {"extract_facts": "fake", "write_journal": "fake"}
