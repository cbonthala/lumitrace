"""Shared fixtures. Area-specific fixtures belong in tests/<area>/conftest.py."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from lumitrace.config import Settings
from lumitrace.frames.storage.local import LocalStorage

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip `@pytest.mark.network` tests unless LUMITRACE_RUN_NETWORK_TESTS=1."""
    if os.environ.get("LUMITRACE_RUN_NETWORK_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="needs network/credentials; set LUMITRACE_RUN_NETWORK_TESTS=1")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Offline settings: local storage and index under tmp_path, fake embeddings."""
    return Settings(
        _env_file=None,
        api_token="test-token",
        storage_backend="local",
        local_root=tmp_path / "Lumitrace",
        index_path=tmp_path / "index" / "lumitrace.sqlite",
        embedding_model="fake",
        embedding_dimension=64,
        stt_provider="fake",
        indexer_nudge_url="",
        mcp_auth_mode="none",
    )


@pytest.fixture
def storage(settings: Settings) -> LocalStorage:
    return LocalStorage(settings.local_root)


@pytest.fixture
def sample_day_markdown() -> str:
    """A fictional, fully populated day file (tests/fixtures/sample-day.md)."""
    return (FIXTURES / "sample-day.md").read_text(encoding="utf-8")


@pytest.fixture
def sample_day_v1_markdown() -> str:
    """The same day in format 1, facts in the front matter (tests/fixtures/sample-day-v1.md)."""
    return (FIXTURES / "sample-day-v1.md").read_text(encoding="utf-8")
