"""Indexer fixtures: fictional day files written through the dayfile helpers."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator, Sequence
from zoneinfo import ZoneInfo

import pytest

from bookshelf.bookmarks.core import Indexer
from bookshelf.books.dayfile import (
    Activity,
    Capture,
    DayFacts,
    DayFile,
    Meal,
    apply_generation,
    day_file_path,
    generated_snapshot_path,
    merge_capture,
    render,
)
from bookshelf.books.storage.local import LocalStorage
from bookshelf.config import Settings
from bookshelf.embeddings import embed_texts

TZ = ZoneInfo("America/Chicago")
GENERATED_AT = dt.datetime(2026, 10, 11, 0, 41, tzinfo=TZ)


class RecordingEmbedder:
    """Fake embeddings that remember what was embedded (and can be told to fail)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.calls: list[list[str]] = []
        self.fail_next = 0

    def __call__(self, texts: Sequence[str]) -> list[list[float]]:
        if self.fail_next:
            self.fail_next -= 1
            raise RuntimeError("embedding service unavailable")
        self.calls.append(list(texts))
        return embed_texts(texts, self.settings)

    @property
    def texts(self) -> list[str]:
        return [t for call in self.calls for t in call]


def make_day(
    day: dt.date,
    *,
    title: str = "A walk in the park",
    journal: str = "## Morning\n\nA long walk in the park with Robin.\n\n## Evening\n\nSoup.",
    people: Sequence[str] = ("Robin",),
    transcript: str = "Walked in the park with Robin this morning. Soup for dinner.",
    generated_at: dt.datetime = GENERATED_AT,
) -> DayFile:
    at = dt.datetime.combine(day, dt.time(21, 30), tzinfo=TZ)
    capture = Capture(
        id=Capture.make_id("recording", at),
        kind="recording",
        captured_at=at,
        text=transcript,
        audio=f"{day.isoformat()}-2130.m4a",
    )
    result = merge_capture(None, capture, day)
    facts = DayFacts(
        mood="calm",
        mood_score=4,
        people=list(people),
        meals=[Meal(type="Dinner", items=["soup", "bread"])],
        activities=[Activity(kind="walk", minutes=45)],
        highlights=["Saw a heron"],
    )
    return apply_generation(
        result,
        facts=facts,
        journal=journal,
        title=title,
        prompt_version="journal-v1",
        models_used={"write_journal": "fake/model"},
        generated_at=generated_at,
    )


def write_day(storage: LocalStorage, day: DayFile, *, snapshot: bool = True) -> str:
    text = render(day)
    path = day_file_path(day.date)
    storage.write_text(path, text)
    if snapshot:
        storage.write_text(generated_snapshot_path(day.date), text)
    return path


@pytest.fixture
def embedder(settings: Settings) -> RecordingEmbedder:
    return RecordingEmbedder(settings)


@pytest.fixture
def indexer(
    settings: Settings, storage: LocalStorage, embedder: RecordingEmbedder
) -> Iterator[Indexer]:
    idx = Indexer(settings, storage, embed=embedder)
    yield idx
    idx.close()
