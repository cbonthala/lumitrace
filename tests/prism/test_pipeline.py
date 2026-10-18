"""CaptureProcessor without HTTP: edit protection, fallbacks, failures, re-processing."""

from __future__ import annotations

import datetime as dt
import json

import pytest

from lumitrace.config import Settings
from lumitrace.frames.dayfile import day_file_path, generated_snapshot_path, parse, render
from lumitrace.frames.storage.local import LocalStorage
from lumitrace.prism.pipeline.processor import CaptureProcessor, CaptureRequest, UploadedFile
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


def test_edited_day_gets_section_update(
    processor: CaptureProcessor, api_settings: Settings, api_storage: LocalStorage, fake_llm
) -> None:
    first = processor.process(make_request(api_settings, api_storage, "a", spoken="Run with Maya."))
    assert first.generation == "full"

    def edit(day) -> None:
        day.journal = "## Summary\n\nMy own words about the run."
        day.facts.mood = "proud"
        day.notes = "Private thought."

    owner_edits(api_storage, edit)
    second = processor.process(
        make_request(api_settings, api_storage, "b", hour=22, kind="note", text="Tacos with Leo.")
    )
    assert second.generation == "update"
    day = parse(api_storage.read_text(day_file_path(OCT10)))
    assert day.journal.startswith("## Summary\n\nMy own words about the run.")
    assert day.journal.endswith("## Evening\n\n- You added another detail to the day.")
    assert "## Later" not in day.journal
    assert day.facts.mood == "proud"
    assert day.facts.people == ["Maya", "Leo"]
    assert day.notes == "Private thought."
    assert day.is_user_edited()
    assert day.meta.prompt_version == "update_day"
    assert day.meta.models_used["update_day"] == "test/journal"
    assert day.meta.models_used["stt"] == "fake"
    update_call = next(c for c in fake_llm.calls if c[0] == "update_day")
    assert "My own words about the run." in update_call[2][1]["content"]
    assert "Tacos with Leo." in update_call[2][1]["content"]
    assert "Run with Maya." in update_call[2][1]["content"]
    assert "Private thought." in update_call[2][1]["content"]


def test_edit_during_generation_is_not_overwritten(
    processor: CaptureProcessor, api_settings: Settings, api_storage: LocalStorage, fake_llm
) -> None:
    processor.process(make_request(api_settings, api_storage, "a", spoken="Run with Maya."))

    def edit_once(task: str) -> None:
        if task != "fill_day" or fake_llm.before_reply is None:
            return
        if len(fake_llm.calls) < 2:
            return
        fake_llm.before_reply = None

        def change(day) -> None:
            day.journal = "Typed while the AI was busy."

        owner_edits(api_storage, change)

    fake_llm.before_reply = edit_once
    result = processor.process(
        make_request(api_settings, api_storage, "b", hour=22, kind="note", text="Tacos.")
    )
    assert result.generation == "update"
    day = parse(api_storage.read_text(day_file_path(OCT10)))
    assert day.journal == "Typed while the AI was busy."
    assert "## Later" not in day.journal
    assert len(day.captures) == 2


def test_fallback_model_is_used_and_recorded(
    processor: CaptureProcessor, api_settings: Settings, api_storage: LocalStorage, fake_llm
) -> None:
    fake_llm.bad_json_models.add("test/journal")
    result = processor.process(make_request(api_settings, api_storage, "a", spoken="Maya."))
    assert result.generation == "full"
    day = parse(api_storage.read_text(day_file_path(OCT10)))
    assert day.meta.models_used["fill_day"] == "test/fallback"
    assert day.journal.startswith("## Summary")
    record = json.loads(api_storage.read_text("_system/activity/2026/10.jsonl").splitlines()[-1])
    steps = {s["name"]: s for s in record["steps"]}
    attempts = steps["fill_day"]["detail"]["attempts"]
    assert [(a["model"], a["ok"]) for a in attempts] == [
        ("test/journal", False),
        ("test/fallback", True),
    ]
    assert "invalid JSON" in attempts[0]["error"]


def test_ai_failure_still_saves_the_transcript(
    processor: CaptureProcessor, api_settings: Settings, api_storage: LocalStorage, fake_llm
) -> None:
    fake_llm.fail_models |= {"test/journal", "test/fallback"}
    result = processor.process(make_request(api_settings, api_storage, "a", spoken="Run."))
    assert result.generation == "failed"
    assert result.errors == ["fill_day: all models failed"]
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


def test_translation_is_saved_with_the_transcript(
    processor: CaptureProcessor, api_settings: Settings, api_storage: LocalStorage
) -> None:
    from lumitrace.prism.pipeline.stt import Transcript

    class Translating:
        def transcribe(self, data: bytes, filename: str) -> Transcript:
            return Transcript(
                text="mana park ki vellam",
                model="sarvam/saaras:v4",
                translation="We went to the park.",
                warnings=("keyterms ignored",),
            )

    processor.transcriber = Translating()
    processor.process(make_request(api_settings, api_storage, "a", spoken="ignored"))
    (saved,) = parse(api_storage.read_text(day_file_path(OCT10))).captures
    assert (saved.text, saved.translation) == ("mana park ki vellam", "")
    assert "English translation" not in api_storage.read_text(day_file_path(OCT10))
    record = json.loads(api_storage.read_text("_system/activity/2026/10.jsonl"))
    assert record["warnings"] == ["transcribe: keyterms ignored"]
    step = next(s for s in record["steps"] if s["name"] == "transcribe")
    assert step["detail"]["translation_chars"] == len("We went to the park.")


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

    def edit(day) -> None:
        day.journal = "## Summary\n\nMy corrected words."

    owner_edits(api_storage, edit)
    again = processor.process(req)
    assert again.audio == "2026-10-10-2130.m4a"
    assert again.generation == "unchanged"
    assert "capture already in the day file; checking journal only" in again.warnings
    day = parse(api_storage.read_text(day_file_path(OCT10)))
    assert len(day.captures) == 1
    assert day.journal == "## Summary\n\nMy corrected words."
    assert [f.path for f in api_storage.list("2026") if f.path.endswith(".m4a")] == [
        "2026/10/2026-10-10/2026-10-10-2130.m4a"
    ]


def test_empty_transcript_skips_generation(
    processor: CaptureProcessor, api_settings: Settings, api_storage: LocalStorage, fake_llm
) -> None:
    class Silent:
        def transcribe(self, data: bytes, filename: str):
            from lumitrace.prism.pipeline.stt import Transcript

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
    assert day.meta.models_used == {"fill_day": "fake"}
