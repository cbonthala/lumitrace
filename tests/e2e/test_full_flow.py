"""End to end, offline: recording API → storage → indexer (via a real nudge) → MCP tools.

All three programs run in-process on one ``LocalStorage`` in a temp folder:

* the recording API (``create_app``) with fake speech to text (uploaded UTF-8 bytes become the
  transcript), a scripted LiteLLM stand-in for fact extraction, the built-in ``fake`` journal
  model, and the real compressor forced onto its keep-the-original fallback;
* the indexer service (worker thread + ``POST /nudge``), nudged by the API through
  ``nudge_indexer`` exactly as in production;
* the MCP server, called through an MCP client.

All data is fictional.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import sqlite3
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient
from mcp import Client
from PIL import Image

from lumitrace.config import Settings
from lumitrace.frames.dayfile import FamilyMember, day_file_path, generated_snapshot_path, parse
from lumitrace.frames.storage.local import LocalStorage
from lumitrace.index.schema import connect
from lumitrace.lens.server import build_server
from lumitrace.nudge import nudge_indexer
from lumitrace.prism.app import create_app as create_api_app
from lumitrace.prism.pipeline.audio import AudioResult, compress_audio
from lumitrace.prism.pipeline.llm import LLMClient
from lumitrace.prism.pipeline.processor import CaptureProcessor
from lumitrace.spectrum.core import Indexer
from lumitrace.spectrum.service import IndexerService
from lumitrace.spectrum.service import create_app as create_indexer_app

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "e2e-token-0123456789abcdef"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
DAY = dt.date(2026, 10, 10)
LAST_YEAR = dt.date(2025, 10, 10)


def fake_extract_facts(*, model: str, messages: list[dict[str, str]], **_: Any) -> Any:
    """Stands in for ``litellm.completion`` on the fact-extraction model (keyword based)."""
    entries = messages[1]["content"].split("Journal entries for this day", 1)[-1]
    lower = entries.lower()
    facts: dict[str, Any] = {
        "mood": "content",
        "mood_score": 4,
        "people": [n for n in ("Maya", "Leo") if n in entries],
        "places": ["the lake"] if "lake" in lower else [],
        "meals": [{"type": "Lunch", "items": ["fish tacos"]}] if "tacos" in lower else [],
        "activities": [{"kind": "run", "minutes": 40}] if " run " in lower else [],
        "highlights": ["Pumpkin patch"] if "pumpkin" in lower else [],
        "family": (
            [{"name": "leo", "activities": [{"kind": "walk"}], "moments": ["saw the stars"]}]
            if "Leo" in entries
            else []
        ),
    }
    content = json.dumps(facts)
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def keep_original(data: bytes, filename: str, bitrate_kbps: int) -> AudioResult:
    """The real compressor, as on a machine without ffmpeg or afconvert."""
    return compress_audio(data, filename, bitrate_kbps, which=lambda _: None)


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 100, 50)).save(buffer, format="PNG")
    return buffer.getvalue()


def wait_until(predicate: Callable[[], Any], what: str, timeout: float = 15) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


def query_index(settings: Settings, sql: str, params: tuple[Any, ...] = ()) -> list[dict]:
    try:
        conn = connect(settings.index_path, settings.embedding_dimension, read_only=True)
    except sqlite3.OperationalError:
        return []
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


class Stack:
    """The three programs wired together."""

    def __init__(self, settings: Settings, storage: LocalStorage) -> None:
        self.settings = settings
        self.storage = storage
        self.indexer_service = IndexerService(
            Indexer(settings, storage), poll_interval=3600, debounce=0.05
        )
        self.indexer_http = TestClient(create_indexer_app(self.indexer_service))
        self.nudges: list[bool] = []

        def nudge(s: Settings, paths: Any) -> bool:
            accepted = nudge_indexer(s, paths, client=self.indexer_http)
            self.nudges.append(accepted)
            return accepted

        processor = CaptureProcessor(
            settings,
            storage,
            llm=LLMClient(settings, completion_fn=fake_extract_facts),
            nudge=nudge,
            compress=keep_original,
        )
        self.api = TestClient(create_api_app(settings, processor=processor, retry_delays=(0.05,)))

    def __enter__(self) -> Stack:
        self.indexer_http.__enter__()
        self.api.__enter__()
        return self

    def __exit__(self, *exc: object) -> None:
        self.api.__exit__(*exc)
        self.indexer_http.__exit__(*exc)
        self.indexer_service.indexer.close()

    # --- recording API ---------------------------------------------------------------------

    def wait_done(self, capture_id: str) -> dict:
        def done() -> dict | None:
            body = self.api.get(f"/captures/{capture_id}", headers=AUTH).json()
            assert body["status"] != "failed", body
            return body if body["status"] == "done" else None

        return wait_until(done, f"capture {capture_id}")

    def note(self, capture_id: str, text: str, captured_at: str) -> dict:
        resp = self.api.post(
            "/notes",
            headers=AUTH,
            json={"text": text, "captured_at": captured_at, "capture_id": capture_id},
        )
        assert resp.status_code == 202, resp.text
        return self.wait_done(capture_id)

    # --- indexer -----------------------------------------------------------------------------

    def wait_indexed(self, day: dt.date) -> dict:
        """Until the index holds the day file as it is in storage right now."""
        live = parse(self.storage.read_text(day_file_path(day)))
        want_at = live.meta.generated_at.astimezone(dt.UTC).isoformat()

        def current() -> dict | None:
            rows = query_index(
                self.settings,
                "SELECT * FROM days WHERE date = ? AND generated_at = ? AND capture_count = ?",
                (day.isoformat(), want_at, len(live.captures)),
            )
            return rows[0] if rows else None

        return wait_until(current, f"index of {day}")

    # --- MCP ---------------------------------------------------------------------------------

    def mcp(self, *calls: tuple[str, dict[str, Any]]) -> list[dict[str, Any]]:
        server = build_server(self.settings, self.storage, transport="stdio")
        results: list[dict[str, Any]] = []

        async def run() -> None:
            async with Client(server) as client:
                for name, args in calls:
                    result = await client.call_tool(name, args)
                    assert not result.is_error, (name, result.content)
                    results.append(result.structured_content)

        anyio.run(run)
        return results


@pytest.fixture
def e2e_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "api_token": settings.api_token.__class__(TOKEN),
            "prompts_dir": ROOT / "prompts",
            "llm_extract_facts_model": "test/extract-facts",
            "llm_write_journal_model": "fake",
            "llm_fallback_model": "fake",
            "indexer_nudge_url": "http://testserver/nudge",
            "indexer_backup_interval_hours": 0,
            "family": "Leo",
        }
    )


@pytest.fixture
def stack(e2e_settings: Settings) -> Iterator[Stack]:
    storage = LocalStorage(e2e_settings.local_root)
    with Stack(e2e_settings, storage) as running:
        yield running


@pytest.mark.filterwarnings("ignore:You should not use the 'timeout' argument")
def test_full_flow(stack: Stack) -> None:
    storage, settings = stack.storage, stack.settings
    day_path = day_file_path(DAY)

    # 1. Capture: a Log My Day recording with a photo, a quick note, and a note from last year.
    resp = stack.api.post(
        "/recordings",
        headers=AUTH,
        files=[
            ("audio", ("memo.wav", b"Morning run by the lake with Maya. Good start.", "audio/wav")),
            ("photos", ("lake.png", png_bytes(), "image/png")),
        ],
        data={
            "captured_at": "2026-10-10T21:30:00-05:00",
            "capture_id": "e2e-recording-1",
            "place": "Austin",
            "lat": "30.2672",
            "lon": "-97.7431",
        },
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["entry_date"] == "2026-10-10"
    recording = stack.wait_done("e2e-recording-1")
    assert recording["generation"] == "full"
    assert recording["audio"] == "2026-10-10-2130.wav"
    assert recording["photos"] == ["photo-01.jpg"]
    assert any("audio kept uncompressed" in w for w in recording["warnings"])

    note = stack.note("e2e-note-1", "Fish tacos for lunch with Maya.", "2026-10-10T13:05:00-05:00")
    assert note["generation"] == "full"
    stack.note("e2e-old-note", "Pumpkin patch trip, lovely day.", "2025-10-10T19:00:00-05:00")
    assert all(stack.nudges), "the indexer refused a nudge"

    # The generated snapshot is the exact file the API wrote (same generated_at).
    assert storage.read_text(generated_snapshot_path(DAY)) == storage.read_text(day_path)
    day = parse(storage.read_text(day_path))
    assert [c.id for c in day.captures] == ["e2e-note-1", "e2e-recording-1"]
    assert day.facts.mood == "content"
    assert day.facts.places == ["the lake"]
    assert day.facts.family == [FamilyMember(name="Leo")], (
        "only LUMITRACE_FAMILY members get a block"
    )
    text = storage.read_text(day_path)
    assert "### Places visited\n\n- the lake" in text
    assert "#### Leo\n\n- **Morning:** not mentioned\n- **Lunch:** not mentioned\n" in text
    assert "- **Snacks / drinks / other:** not mentioned" in text
    assert "#### Everyone\n\n- **Lunch:** fish tacos" in text
    assert "Fish tacos for lunch" in day.journal
    assert storage.exists("2026/10/2026-10-10/2026-10-10-2130.wav")
    assert not storage.list("_system/inbox")

    activity = "".join(storage.read_text(f.path) for f in storage.list("_system/activity"))
    assert "e2e-recording-1" in activity
    assert "tacos" not in activity.lower(), "activity records must not contain journal text"

    # 2. Index: the nudges alone (no poll) bring both days into the index.
    indexed = stack.wait_indexed(DAY)
    assert indexed["user_edited"] == 0
    stack.wait_indexed(LAST_YEAR)

    # 3. Ask: every MCP tool finds the content under the right date.
    search, other_search, get_day, meals, runs, places, on_this_day, feedback = stack.mcp(
        ("search", {"query": "fish tacos"}),
        ("search", {"query": "pumpkin patch"}),
        ("get_day", {"date": "2026-10-10"}),
        ("query_facts", {"kind": "meals", "contains": "tacos"}),
        ("query_facts", {"kind": "activities"}),
        ("query_facts", {"kind": "places"}),
        ("on_this_day", {"date": "2026-10-10"}),
        (
            "feedback",
            {
                "question": "What did I eat on Oct 10?",
                "answer": "Fish tacos (2026-10-10).",
                "comment": "Correct.",
                "rating": "good",
            },
        ),
    )
    assert search["results"][0]["date"] == "2026-10-10"
    assert "keyword" in search["results"][0]["matched_by"]
    assert other_search["results"][0]["date"] == "2025-10-10"

    assert get_day["found"] is True
    assert get_day["facts"]["people"] == ["Maya"]
    assert [t["text"] for t in get_day["transcript"]] == [
        "Fish tacos for lunch with Maya.",
        "Morning run by the lake with Maya. Good start.",
    ]
    assert get_day["transcript"][1]["location"] == "Austin (30.26720, -97.74310)"
    assert get_day["audio"][0]["name"] == "2026-10-10-2130.wav"
    assert get_day["audio"][0]["link"].startswith("file://")
    assert get_day["photos"][0]["name"] == "photo-01.jpg"

    assert meals["rows"] == [
        {"date": "2026-10-10", "person": "", "meal_type": "lunch", "item": "fish tacos"}
    ]
    assert runs["rows"] == [{"date": "2026-10-10", "kind": "run", "minutes": 40}]
    assert places["rows"] == [{"date": "2026-10-10", "name": "the lake"}]
    assert [d["date"] for d in on_this_day["days"]] == ["2025-10-10"]
    assert on_this_day["days"][0]["years_ago"] == 1
    assert on_this_day["days"][0]["highlights"] == ["Pumpkin patch"]

    assert feedback["saved"] is True
    assert feedback["dates"] == ["2026-10-10"]
    assert storage.exists(feedback["storage_path"])
    rows = query_index(settings, "SELECT rating, dates_json FROM feedback")
    assert rows == [{"rating": "good", "dates_json": '["2026-10-10"]'}]

    # 4. The owner edits the day in Obsidian; a sync records edit signals.
    original = storage.read_text(day_path)
    edited = original.replace("**Mood:** content", "**Mood:** great").replace(
        "## Summary\n\n", "## Summary\n\nBest tacos in town, honestly.\n\n", 1
    )
    assert edited != original
    storage.write_text(day_path, edited)
    resp = stack.indexer_http.post("/nudge", json={"paths": [day_path]})
    assert resp.status_code == 202

    def signals() -> list[dict]:
        return query_index(
            settings,
            "SELECT section, field, before, after FROM edit_signals WHERE date = ?",
            (DAY.isoformat(),),
        )

    found = wait_until(lambda: len(signals()) >= 2 and signals(), "edit signals")
    by_section = {(s["section"], s["field"]): s for s in found}
    assert by_section[("facts", "mood")]["before"] == '"content"'
    assert by_section[("facts", "mood")]["after"] == '"great"'
    assert "Best tacos in town" in by_section[("journal", None)]["after"]
    assert "Best tacos in town" not in by_section[("journal", None)]["before"]
    edited_row = query_index(
        settings, "SELECT user_edited FROM days WHERE date = ?", ("2026-10-10",)
    )
    assert edited_row == [{"user_edited": 1}]

    # 5. Another capture for the edited day is merged additively; the owner's edit survives.
    late = stack.note(
        "e2e-note-2", "Late walk with Leo under the stars.", "2026-10-10T22:15:00-05:00"
    )
    assert late["generation"] == "additive"
    day = parse(storage.read_text(day_path))
    assert day.facts.mood == "great"
    assert "Best tacos in town, honestly." in day.journal
    assert "## Later\n\n**22:15 · Quick Note**" in day.journal
    assert "Late walk with Leo under the stars." in day.journal
    assert day.facts.people == ["Maya", "Leo"]
    assert [(m.name, m.moments) for m in day.facts.family] == [("Leo", ["saw the stars"])]
    assert [c.id for c in day.captures] == ["e2e-note-1", "e2e-recording-1", "e2e-note-2"]
    assert day.is_user_edited()
    assert storage.read_text(generated_snapshot_path(DAY)) == storage.read_text(day_path)

    stack.wait_indexed(DAY)
    stars, people, leo, activities = stack.mcp(
        ("search", {"query": "stars", "from_date": "2026-10-10", "to_date": "2026-10-10"}),
        ("query_facts", {"kind": "people", "contains": "leo"}),
        ("query_facts", {"kind": "family", "person": "leo"}),
        ("query_facts", {"kind": "activities"}),
    )
    assert stars["results"][0]["date"] == "2026-10-10"
    assert people["rows"] == [{"date": "2026-10-10", "name": "Leo"}]
    assert [(r["category"], r["text"]) for r in leo["rows"]] == [("moments", "saw the stars")]
    assert "walk (leo)" in [a["kind"] for a in activities["rows"]]
    kept = {(s["section"], s["field"]) for s in signals()}
    assert {("facts", "mood"), ("journal", None)} <= kept, "earlier edit signals were lost"
