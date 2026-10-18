from __future__ import annotations

import datetime as dt

from lumitrace.config import Settings
from lumitrace.frames.dayfile import (
    FORMAT_VERSION,
    day_file_path,
    generated_facts_path,
    generated_snapshot_path,
    parse,
)
from lumitrace.frames.storage.local import LocalStorage
from lumitrace.prism.pipeline.generate import Generator
from lumitrace.prism.pipeline.llm import LLMClient
from lumitrace.prism.regenerate import regenerate_days
from tests.prism.conftest import FakeLLM

DAY = dt.date(2026, 10, 10)


def _generator(settings: Settings, llm: FakeLLM) -> Generator:
    return Generator(LLMClient(settings, completion_fn=llm), settings.prompts_dir)


def _write(storage: LocalStorage, day: dt.date, text: str, *, snapshot: bool) -> str:
    path = day_file_path(day)
    storage.write_text(path, text)
    if snapshot:
        storage.write_text(generated_snapshot_path(day), text)
    return path


def test_regenerate_updates_an_existing_format_2_day_like_generate(
    api_settings: Settings,
    api_storage: LocalStorage,
    fake_llm: FakeLLM,
    sample_day_v2_markdown: str,
) -> None:
    path = _write(api_storage, DAY, sample_day_v2_markdown, snapshot=True)
    before = parse(sample_day_v2_markdown)
    generator = _generator(api_settings, fake_llm)

    outcomes = regenerate_days(api_settings, api_storage, generator)

    assert [(o.date, o.status) for o in outcomes] == [(DAY, "update")]
    live = api_storage.read_text(path)
    assert api_storage.read_text(generated_snapshot_path(DAY)) == live
    day = parse(live)
    assert day.meta.lumitrace_format == FORMAT_VERSION
    assert day.meta.prompt_version == "update_day"
    assert day.title == before.title
    assert "Fish tacos and a horchata" in day.journal
    assert "You added another detail to the day." in day.journal
    assert day.facts.mood == "happy"
    assert day.facts.people == ["Maya", "Leo"]
    assert api_storage.exists(generated_facts_path(DAY))
    assert day.notes == before.notes
    assert [c.text for c in day.captures] == [c.text for c in before.captures]
    assert day.meta.audio == before.meta.audio
    assert fake_llm.tasks() == ["update_day"]

    again = regenerate_days(api_settings, api_storage, generator)
    assert [o.status for o in again] == ["unchanged"]
    assert fake_llm.tasks() == ["update_day"]


def test_regenerate_leaves_a_day_the_owner_edited(
    api_settings: Settings, api_storage: LocalStorage, fake_llm: FakeLLM, sample_day_markdown: str
) -> None:
    edited = sample_day_markdown.replace("**Mood:** happy", "**Mood:** great").replace(
        "A full, happy Saturday", "My own words. A full, happy Saturday"
    )
    path = _write(api_storage, DAY, edited, snapshot=False)
    api_storage.write_text(generated_snapshot_path(DAY), sample_day_markdown)
    assert parse(edited).is_user_edited()

    outcomes = regenerate_days(api_settings, api_storage, _generator(api_settings, fake_llm))

    assert [o.status for o in outcomes] == ["update"]
    day = parse(api_storage.read_text(path))
    assert day.facts.mood == "great"
    assert "My own words." in day.journal
    assert "You added another detail to the day." in day.journal
    assert day.is_user_edited()
    assert fake_llm.tasks() == ["update_day"]


def test_regenerate_dry_run_range_and_days_without_text(
    api_settings: Settings,
    api_storage: LocalStorage,
    fake_llm: FakeLLM,
    sample_day_v2_markdown: str,
) -> None:
    _write(api_storage, DAY, sample_day_v2_markdown, snapshot=True)
    other = dt.date(2026, 9, 1)
    empty = (
        "---\ndate: 2026-09-01\nlumitrace_format: 3\n---\n\n# T\n\n## Transcript\n\n"
        "<!-- lumitrace:transcript:start -->\n<!-- lumitrace:transcript:end -->\n"
    )
    _write(api_storage, other, empty, snapshot=False)
    generator = _generator(api_settings, fake_llm)

    dry = regenerate_days(api_settings, api_storage, generator, dry_run=True)
    assert [(o.date, o.status) for o in dry] == [
        (other, "skipped"),
        (DAY, "would update"),
    ]
    assert api_storage.read_text(day_file_path(DAY)) == sample_day_v2_markdown
    assert fake_llm.calls == []

    ranged = regenerate_days(
        api_settings, api_storage, generator, start=dt.date(2026, 10, 1), end=dt.date(2026, 10, 31)
    )
    assert [o.date for o in ranged] == [DAY]
