"""The journal is written once, after the day closes, not on every recording."""

from __future__ import annotations

import datetime as dt

from lumitrace.config import Settings
from lumitrace.frames.dayfile import day_file_path, parse
from lumitrace.frames.storage.local import LocalStorage
from lumitrace.prism.journal_schedule import JournalScheduler, next_journal_at
from lumitrace.prism.pipeline.processor import CaptureProcessor
from tests.prism.test_pipeline import make_request, owner_edits

OCT10 = dt.date(2026, 10, 10)


def test_next_journal_at_is_five_minutes_after_the_rollover(api_settings: Settings) -> None:
    tz = api_settings.tz
    hour = api_settings.day_rollover_hour
    assert next_journal_at(dt.datetime(2026, 10, 17, 15, tzinfo=tz), tz, hour) == dt.datetime(
        2026, 10, 18, hour, 5, tzinfo=tz
    )
    assert next_journal_at(dt.datetime(2026, 10, 18, 3, 30, tzinfo=tz), tz, hour) == dt.datetime(
        2026, 10, 18, hour, 5, tzinfo=tz
    )
    assert next_journal_at(dt.datetime(2026, 10, 18, hour, 5, tzinfo=tz), tz, hour) == dt.datetime(
        2026, 10, 19, hour, 5, tzinfo=tz
    )


def test_open_day_keeps_every_recording_and_writes_the_journal_once(
    processor: CaptureProcessor, api_settings: Settings, api_storage: LocalStorage, fake_llm
) -> None:
    clock = [dt.datetime(2026, 10, 10, 15, tzinfo=api_settings.tz)]
    processor._now_fn = lambda: clock[0]

    first = processor.process(make_request(api_settings, api_storage, "a", spoken="Run with Maya."))
    second = processor.process(
        make_request(api_settings, api_storage, "b", hour=22, spoken="Tacos with Leo.")
    )
    assert (first.generation, second.generation) == ("deferred", "deferred")
    assert fake_llm.calls == []
    saved = parse(api_storage.read_text(day_file_path(OCT10)))
    assert saved.journal == ""
    assert [c.text for c in saved.captures] == ["Run with Maya.", "Tacos with Leo."]
    assert api_storage.exists(processor._due_path(OCT10))

    clock[0] = dt.datetime(2026, 10, 11, 3, 30, tzinfo=api_settings.tz)
    assert processor.generate_pending() == []
    assert fake_llm.calls == []

    clock[0] = dt.datetime(2026, 10, 11, 4, 6, tzinfo=api_settings.tz)
    assert processor.generate_pending() == [(OCT10, "full")]
    assert processor.generate_pending() == []
    assert fake_llm.tasks() == ["fill_day"]
    day = parse(api_storage.read_text(day_file_path(OCT10)))
    assert day.journal == "## Summary\n\nA day with 2 entries."
    assert day.facts.people == ["Maya", "Leo"]
    assert not day.is_user_edited()
    assert not api_storage.exists(processor._due_path(OCT10))
    filled = fake_llm.calls[0]
    assert "Run with Maya." in filled[2][1]["content"]
    assert "Tacos with Leo." in filled[2][1]["content"]
    assert "Day file template" in filled[2][1]["content"]


def test_morning_run_writes_the_journal_even_if_one_was_typed_early(
    processor: CaptureProcessor, api_settings: Settings, api_storage: LocalStorage, fake_llm
) -> None:
    clock = [dt.datetime(2026, 10, 10, 15, tzinfo=api_settings.tz)]
    processor._now_fn = lambda: clock[0]
    processor.process(make_request(api_settings, api_storage, "a", spoken="Run with Maya."))

    def edit(day) -> None:
        day.journal = "My own words about the run."
        day.notes = "Keep this note."

    owner_edits(api_storage, edit)
    clock[0] = dt.datetime(2026, 10, 11, 4, 6, tzinfo=api_settings.tz)
    assert processor.generate_pending() == [(OCT10, "full")]
    day = parse(api_storage.read_text(day_file_path(OCT10)))
    assert day.journal == "## Summary\n\nA day with 1 entries."
    assert "My own words about the run." not in day.journal
    assert day.notes == "Keep this note."
    assert fake_llm.tasks() == ["fill_day"]


def test_a_failed_morning_run_is_tried_again(
    processor: CaptureProcessor, api_settings: Settings, api_storage: LocalStorage, fake_llm
) -> None:
    clock = [dt.datetime(2026, 10, 10, 15, tzinfo=api_settings.tz)]
    processor._now_fn = lambda: clock[0]
    processor.process(make_request(api_settings, api_storage, "a", spoken="Run."))
    clock[0] = dt.datetime(2026, 10, 11, 4, 6, tzinfo=api_settings.tz)
    fake_llm.fail_models |= {"test/journal", "test/fallback"}

    assert processor.generate_pending() == [(OCT10, "failed")]
    assert api_storage.exists(processor._due_path(OCT10))
    assert parse(api_storage.read_text(day_file_path(OCT10))).journal == ""

    fake_llm.fail_models.clear()
    assert processor.generate_pending() == [(OCT10, "full")]
    assert parse(api_storage.read_text(day_file_path(OCT10))).journal.startswith("## Summary")


def test_scheduler_stops_while_it_is_waiting(processor: CaptureProcessor) -> None:
    class Idle:
        def wait_idle(self, timeout: float = 30.0) -> bool:
            return True

    scheduler = JournalScheduler(processor, Idle())  # type: ignore[arg-type]
    scheduler.start()
    scheduler.stop(timeout=5)
    assert scheduler._thread is None
