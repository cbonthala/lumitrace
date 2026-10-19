"""Fixtures for the recording API: a scripted fake LLM, a fake compressor, a nudge recorder, and
an app wired to local storage. All data is fictional."""

from __future__ import annotations

import datetime as dt
import io
import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from lumitrace.config import Settings
from lumitrace.frames.storage.local import LocalStorage
from lumitrace.prism.app import create_app
from lumitrace.prism.pipeline.audio import AudioResult
from lumitrace.prism.pipeline.llm import LLMClient
from lumitrace.prism.pipeline.processor import CaptureProcessor

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "test-token-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def task_of(messages: list[dict[str, str]]) -> str:
    system = messages[0]["content"]
    if "update an existing" in system:
        return "update_day"
    return "fill_day"


class FakeLLM:
    """Stands in for ``litellm.completion``. Facts are derived from keywords in the entries."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list[dict[str, str]]]] = []
        self.fail_models: set[str] = set()
        self.bad_json_models: set[str] = set()
        self.before_reply: Callable[[str], None] | None = None

    def __call__(self, *, model: str, messages: list[dict[str, str]], **_: Any) -> Any:
        task = task_of(messages)
        self.calls.append((task, model, messages))
        if self.before_reply is not None:
            self.before_reply(task)
        if model in self.fail_models:
            raise RuntimeError("provider unavailable")
        user = messages[1]["content"]
        if model in self.bad_json_models:
            content = "Sure! Here are the facts: mood is great"
        elif task == "update_day":
            content = json.dumps(
                {
                    "additions": [
                        {
                            "section": "Evening",
                            "text": "You added another detail to the day.",
                        }
                    ],
                    "replacements": [],
                    "deletions": [],
                    "structured": self.content(user),
                }
            )
        else:
            spoken = user.split("Journal entries for this day", 1)[-1]
            entries = spoken.count("· Log My Day") + spoken.count("· Quick Note")
            structured = self.content(user)
            content = json.dumps(
                {
                    "headline": "Taco day",
                    "timeline": {
                        "highlight": structured["highlight"],
                        "context": structured["context"],
                        "time_not_stated": [f"A day with {entries} entries."],
                        "remember": structured["remember"],
                    },
                    "trackers": structured["trackers"],
                }
            )
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    @staticmethod
    def content(user: str) -> dict[str, Any]:
        marker = (
            "Journal entries for this day"
            if "Journal entries for this day" in user
            else "Every recording for this date"
        )
        entries = user.split(marker, 1)[-1]
        lowered = entries.casefold()
        people = [
            {"name": name, "family_members": []}
            for name in ("Maya", "Leo", "Priya")
            if name in entries
        ]
        family: list[dict[str, Any]] = []
        sam: dict[str, Any] = {"name": "Sam"}
        if "tacos" in lowered:
            sam["food"] = {
                "lunch": {"status": "consumed", "items": ["fish tacos"]},
            }
        if "run" in lowered:
            sam["health_fitness"] = {
                "exercise_movement": [{"activity": "run", "minutes": 40}],
            }
        family.append(sam)
        return {
            "highlight": None,
            "context": {"people_met": people},
            "remember": None,
            "trackers": {
                "family": family,
                "pregnancy_baby": {},
                "tags": ["content"],
            },
        }

    @staticmethod
    def facts(user: str) -> dict[str, Any]:
        """Legacy helper retained for tests that exercise Format 5 parser compatibility."""
        content = FakeLLM.content(user)
        people = content["context"]["people_met"]
        return {"mood": "content", "mood_score": 4, "people": people}

    def tasks(self) -> list[str]:
        return [c[0] for c in self.calls]


def fake_compress(data: bytes, filename: str, bitrate_kbps: int) -> AudioResult:
    return AudioResult(data=data, ext=".m4a", compressor="fake")


class NudgeRecorder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.raise_error = False

    def __call__(self, settings: Settings, paths: Any) -> bool:
        self.calls.append(list(paths))
        if self.raise_error:
            raise RuntimeError("indexer down")
        return True


@pytest.fixture
def api_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "api_token": settings.api_token.__class__(TOKEN),
            "prompts_dir": ROOT / "prompts",
            "llm_write_journal_model": "test/journal",
            "llm_fallback_model": "test/fallback",
        }
    )


@pytest.fixture
def api_storage(api_settings: Settings) -> LocalStorage:
    return LocalStorage(api_settings.local_root)


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def nudges() -> NudgeRecorder:
    return NudgeRecorder()


@pytest.fixture
def processor(
    api_settings: Settings, api_storage: LocalStorage, fake_llm: FakeLLM, nudges: NudgeRecorder
) -> CaptureProcessor:
    return CaptureProcessor(
        api_settings,
        api_storage,
        llm=LLMClient(api_settings, completion_fn=fake_llm),
        nudge=nudges,
        compress=fake_compress,
        now=lambda: dt.datetime(2026, 10, 17, 15, tzinfo=api_settings.tz),
    )


@pytest.fixture
def app(api_settings: Settings, processor: CaptureProcessor) -> FastAPI:
    return create_app(api_settings, processor=processor, retry_delays=(0.05,))


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def wait_idle(app: FastAPI) -> None:
    assert app.state.services.worker.wait_idle(10)


def poll_status(client: TestClient, capture_id: str, want: str, timeout: float = 10) -> dict:
    deadline = time.monotonic() + timeout
    body: dict = {}
    while time.monotonic() < deadline:
        body = client.get(f"/captures/{capture_id}", headers=AUTH).json()
        if body.get("status") == want:
            return body
        time.sleep(0.02)
    raise AssertionError(f"capture {capture_id} never reached {want}: {body}")


def image_bytes(size: tuple[int, int] = (64, 48), fmt: str = "PNG", mode: str = "RGB") -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, size, (200, 100, 50) if mode == "RGB" else (200, 100, 50, 128)).save(
        buffer, format=fmt
    )
    return buffer.getvalue()
