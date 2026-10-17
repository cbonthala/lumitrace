"""Regenerate past days from their stored transcripts with the current prompts and day format.

``lumitrace-prism regenerate`` runs this. For each day file in the date range:

* a day the owner has not edited gets its facts, title and journal replaced (the owner's notes,
  the transcripts, the audio and the photos are never touched);
* a day the owner edited keeps every word they wrote: the new facts are only added to it
  (:func:`~lumitrace.frames.dayfile.merge_generation_additive`), the journal is not changed;
* a day without any transcript text is skipped.

A day counts as unedited when its generated hash matches, or when the file is identical to the
snapshot the Prism wrote (``_system/generated/``). The second rule covers days written in the
older day format 2, whose hash no longer matches after the format changed.

Every day is written like the Prism writes it: the day file, then the identical snapshot.
Spectrum picks the changes up on its next sync; ``nudge`` asks it to do so right away.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass

from lumitrace.config import Settings
from lumitrace.frames.dayfile import (
    DayFile,
    DayFileParseError,
    apply_generation,
    default_title,
    generated_snapshot_path,
    merge_generation_additive,
    parse,
    parse_day_file_path,
    render,
)
from lumitrace.frames.storage.base import Storage
from lumitrace.nudge import nudge_indexer
from lumitrace.prism.pipeline.generate import Generator
from lumitrace.prism.pipeline.llm import LLMError
from lumitrace.prism.pipeline.prompts import combined_version

log = logging.getLogger(__name__)

Status = str
"""``regenerated`` | ``merged`` (edited day, facts added only) | ``skipped`` | ``failed``;
``would regenerate`` and ``would merge`` in a dry run."""


@dataclass
class DayOutcome:
    date: dt.date
    status: Status
    detail: str = ""


def _in_range(day: dt.date, start: dt.date | None, end: dt.date | None) -> bool:
    return (start is None or day >= start) and (end is None or day <= end)


def _day_files(
    storage: Storage, start: dt.date | None, end: dt.date | None
) -> list[tuple[dt.date, str]]:
    found: dict[dt.date, str] = {}
    for info in storage.list(""):
        day = parse_day_file_path(info.path)
        if day is not None and _in_range(day, start, end):
            found[day] = info.path
    return sorted(found.items())


def _is_edited(day: DayFile, live: str, snapshot: str | None) -> bool:
    if snapshot is not None and snapshot == live:
        return False
    return day.is_user_edited()


def regenerate_days(
    settings: Settings,
    storage: Storage,
    generator: Generator,
    *,
    start: dt.date | None = None,
    end: dt.date | None = None,
    dry_run: bool = False,
    nudge: bool = False,
    on_outcome: Callable[[DayOutcome], None] | None = None,
) -> list[DayOutcome]:
    """Regenerate every day in ``[start, end]`` (both optional). Returns one outcome per day."""
    outcomes: list[DayOutcome] = []
    written: list[str] = []

    def done(outcome: DayOutcome) -> None:
        outcomes.append(outcome)
        if on_outcome is not None:
            on_outcome(outcome)

    for date, path in _day_files(storage, start, end):
        live = storage.read_text(path)
        try:
            day = parse(live, fallback_date=date)
        except DayFileParseError as exc:
            done(DayOutcome(date, "failed", f"cannot read the day file: {exc}"))
            continue
        if not any(c.text.strip() or c.translation.strip() for c in day.captures):
            done(DayOutcome(date, "skipped", "no transcript text"))
            continue
        snapshot_path = generated_snapshot_path(date)
        snapshot = storage.read_text(snapshot_path) if storage.exists(snapshot_path) else None
        edited = _is_edited(day, live, snapshot)
        if dry_run:
            done(DayOutcome(date, "would merge" if edited else "would regenerate"))
            continue
        try:
            facts_result, facts_prompt = generator.extract_facts(date, day.captures)
            labels = [facts_prompt.label]
            models = {**day.meta.models_used, "extract_facts": facts_result.model}
            if edited:
                updated = merge_generation_additive(
                    day,
                    facts=facts_result.value,
                    prompt_version=combined_version(labels),
                    models_used=models,
                )
                status = "merged"
            else:
                journal_result, journal_prompt = generator.write_journal(
                    date, day.captures, facts_result.value
                )
                labels.append(journal_prompt.label)
                models["write_journal"] = journal_result.model
                headline = journal_result.value.headline
                title = default_title(date) + (f" · {headline}" if headline else "")
                updated = apply_generation(
                    day,
                    facts=facts_result.value,
                    journal=journal_result.value.journal,
                    title=title,
                    prompt_version=combined_version(labels),
                    models_used=models,
                    force=True,  # only reached for a day that is unedited
                )
                status = "regenerated"
        except LLMError as exc:
            log.warning("regenerate %s: all models failed", date)
            done(DayOutcome(date, "failed", f"all models failed: {exc}"))
            continue
        text = render(updated)
        storage.write_text(path, text)
        storage.write_text(snapshot_path, text)
        written.append(path)
        done(DayOutcome(date, status))
    if nudge and written:
        nudge_indexer(settings, written)
    return outcomes
