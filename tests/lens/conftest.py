"""Fixtures for the MCP server: fictional day files in LocalStorage and a small index built
directly with ``lumitrace.index.schema`` (the real indexer is a separate work stream)."""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from lumitrace.config import Settings
from lumitrace.embeddings import embed_texts
from lumitrace.frames.dayfile import (
    Activity,
    Capture,
    DayFacts,
    DayFile,
    FamilyMember,
    FrontMatter,
    Meal,
    day_dir,
    day_file_path,
    parse,
    render,
)
from lumitrace.frames.storage.local import LocalStorage
from lumitrace.index.schema import connect, serialize_embedding
from lumitrace.lens.tools import LensTools
from lumitrace.spectrum.core import _insert_day

TZ = ZoneInfo("America/Chicago")


def _capture(day: dt.date, hour: int, text: str, kind: str = "recording") -> Capture:
    at = dt.datetime(day.year, day.month, day.day, hour, 0, tzinfo=TZ)
    return Capture(id=Capture.make_id(kind, at), kind=kind, captured_at=at, text=text)


def fixture_days(sample_day_markdown: str) -> list[DayFile]:
    """Four fictional days: 2024-10-10, 2025-10-10, 2026-09-15 and the sample 2026-10-10."""
    d1, d2, d3 = dt.date(2024, 10, 10), dt.date(2025, 10, 10), dt.date(2026, 9, 15)
    return [
        DayFile(
            meta=FrontMatter(date=d1),
            facts=DayFacts(
                mood="cheerful",
                mood_score=4,
                people=["Maya", "Leo"],
                places=["Pumpkin patch", "the farm trail"],
                meals=[Meal(type="breakfast", items=["pancakes"])],
                activities=[Activity(kind="hike", minutes=90)],
                family=[
                    FamilyMember(
                        name="Leo",
                        meals=[Meal(type="snacks", items=["pumpkin pie"])],
                        moments=["picked the biggest pumpkin"],
                    ),
                    FamilyMember(name="Maya", moments=["hiked the farm trail"]),
                ],
                highlights=["Leo picked the biggest pumpkin"],
            ),
            title="Thursday, October 10, 2024 · Pumpkin patch",
            journal="## Summary\n\nWe drove out to the pumpkin patch and hiked the farm trail.",
            captures=[_capture(d1, 20, "Pumpkin patch today, Leo found a giant pumpkin.")],
        ),
        DayFile(
            meta=FrontMatter(date=d2),
            facts=DayFacts(
                mood="tired",
                mood_score=2,
                people=["Maya"],
                meals=[
                    Meal(type="lunch", items=["ramen"]),
                    Meal(type="dinner", items=["pasta"]),
                ],
                activities=[Activity(kind="run", minutes=30)],
                highlights=["Finished the quarterly report"],
            ),
            title="Friday, October 10, 2025 · Rainy day",
            journal=(
                "## Summary\n\nA rainy Friday. Ramen for lunch and pasta for dinner.\n\n"
                "## Evening\n\nA short run in the drizzle, then the quarterly report was done."
            ),
            captures=[_capture(d2, 21, "Rainy day, ramen, pasta, short run.")],
        ),
        DayFile(
            meta=FrontMatter(date=d3),
            facts=DayFacts(
                mood="happy",
                mood_score=5,
                people=["Leo", "Grandma Rose"],
                places=["home", "the farmers market"],
                activities=[Activity(kind="Run", minutes=45), Activity(kind="reading")],
                family=[
                    FamilyMember(
                        name="Leo",
                        feelings=["happy"],
                        meals=[
                            Meal(type="dinner", items=["pasta"]),
                            Meal(type="snacks", items=["lemonade"]),
                        ],
                        health=["a runny nose"],
                        moments=["passed the spelling test"],
                    ),
                ],
                highlights=["Grandma Rose visited"],
            ),
            title="Tuesday, September 15, 2026 · Grandma visits",
            journal="## Summary\n\nGrandma Rose came to visit and we made pasta together.",
            notes="Ask Grandma Rose for the sauce recipe.",
            captures=[_capture(d3, 21, "Grandma Rose is here. We cooked pasta.")],
        ),
        parse(sample_day_markdown),
    ]


def _passages(day: DayFile) -> list[tuple[str, str | None, str | None, str]]:
    """(section, heading, capture_id, text) chunks, roughly as the indexer would make them."""
    out: list[tuple[str, str | None, str | None, str]] = [("title", None, None, day.title)]
    heading: str | None = None
    for block in day.journal.split("\n## "):
        lines = block.removeprefix("## ").split("\n", 1)
        heading = lines[0].strip()
        body = lines[1].strip() if len(lines) > 1 else ""
        if body:
            out.append(("journal", heading, None, body))
    if day.notes:
        out.append(("notes", None, None, day.notes))
    out.extend(("transcript", None, c.id, c.text) for c in day.captures if c.text)
    facts = day.facts
    fact_text = "; ".join(
        [
            *(f"{m.type}: {', '.join(m.items)}" for m in facts.meals),
            *(a.kind for a in facts.activities),
            *facts.people,
            *facts.places,
            *facts.highlights,
        ]
    )
    if fact_text:
        out.append(("facts", None, None, fact_text))
    return out


def index_day(conn, settings: Settings, day: DayFile) -> None:
    date = day.date.isoformat()
    path = day_file_path(day.date)
    with conn:
        conn.execute("DELETE FROM days WHERE date = ?", (date,))
        conn.execute("DELETE FROM files WHERE path = ?", (path,))
        conn.execute(
            "INSERT INTO files(path, kind, date, content_hash, indexed_at) "
            "VALUES (?, 'day', ?, 'hash', '2026-10-11T00:00:00+00:00')",
            (path, date),
        )
        _insert_day(conn, path, day)
        chunks = _passages(day)
        vectors = embed_texts([c[3] for c in chunks], settings)
        for ordinal, ((section, heading, capture_id, text), vector) in enumerate(
            zip(chunks, vectors, strict=True)
        ):
            cur = conn.execute(
                "INSERT INTO passages(path, date, section, heading, capture_id, ordinal, text, "
                "text_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    path,
                    date,
                    section,
                    heading,
                    capture_id,
                    ordinal,
                    text,
                    hashlib.sha256(text.encode()).hexdigest(),
                ),
            )
            conn.execute(
                "INSERT INTO passages_vec(rowid, embedding) VALUES (?, ?)",
                (cur.lastrowid, serialize_embedding(vector)),
            )


@pytest.fixture
def days(sample_day_markdown: str) -> list[DayFile]:
    return fixture_days(sample_day_markdown)


@pytest.fixture
def populated(settings: Settings, storage: LocalStorage, days: list[DayFile]) -> Path:
    """Day files in storage (plus the sample day's audio and first photo) and a built index."""
    for day in days:
        storage.write_text(day_file_path(day.date), render(day))
    sample = days[-1]
    storage.write_bytes(f"{day_dir(sample.date)}/{sample.meta.audio[0]}", b"fake audio")
    storage.write_bytes(f"{day_dir(sample.date)}/{sample.meta.photos[0]}", b"fake jpeg")
    conn = connect(settings.index_path, settings.embedding_dimension, embedding_model="fake")
    try:
        for day in days:
            index_day(conn, settings, day)
    finally:
        conn.close()
    return Path(settings.index_path)


@pytest.fixture
def tools(settings: Settings, storage: LocalStorage) -> LensTools:
    return LensTools(settings, storage)
