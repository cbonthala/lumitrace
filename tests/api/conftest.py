"""Fixtures for the recording API: a scripted fake LLM, a fake compressor, a nudge recorder, and
an app wired to local storage. All data is fictional."""

from __future__ import annotations

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

from lifelog.api.app import create_app
from lifelog.config import Settings
from lifelog.pipeline.audio import AudioResult
from lifelog.pipeline.llm import LLMClient
from lifelog.pipeline.processor import CaptureProcessor
from lifelog.storage.local import LocalStorage

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "test-token-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def task_of(messages: list[dict[str, str]]) -> str:
    system = messages[0]["content"]
    if "extract structured facts" in system:
        return "extract_facts"
    if "Write a short addition" in system:
        return "journal_addendum"
    return "write_journal"


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
        elif task == "extract_facts":
            content = json.dumps(self.facts(user))
        elif task == "write_journal":
            entries = user.count("· Log My Day") + user.count("· Quick Note")
            content = json.dumps(
                {"headline": "Taco day", "journal": f"## Summary\n\nA day with {entries} entries."}
            )
        else:
            content = "```json\n" + json.dumps({"text": "Later you added a quick note."}) + "\n```"
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    @staticmethod
    def facts(user: str) -> dict[str, Any]:
        entries = user.split("Journal entries for this day", 1)[-1]
        facts: dict[str, Any] = {
            "mood": "content",
            "mood_score": 4,
            "people": [n for n in ("Maya", "Leo", "Priya") if n in entries],
            "meals": [],
            "activities": [],
        }
        if "tacos" in entries:
            facts["meals"].append({"type": "lunch", "items": ["fish tacos"]})
        if "run" in entries:
            facts["activities"].append({"kind": "run", "minutes": 40})
        return facts

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
            "llm_extract_facts_model": "test/extract",
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
