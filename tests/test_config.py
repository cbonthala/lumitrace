from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from lifelog.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def test_defaults_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(__import__("os").environ):
        if key.startswith("LIFELOG_"):
            monkeypatch.delenv(key)
    s = Settings(_env_file=None)
    assert s.timezone == "America/Chicago"
    assert s.day_rollover_hour == 4
    assert s.storage_backend == "local"
    assert s.gdrive_root_folder == "LifeLog"
    assert s.embedding_dimension == 1536
    assert s.tz.key == "America/Chicago"


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIFELOG_STORAGE_BACKEND", "gdrive")
    monkeypatch.setenv("LIFELOG_DAY_ROLLOVER_HOUR", "5")
    monkeypatch.setenv("LIFELOG_API_TOKEN", "tok-4f9a2c")
    s = Settings(_env_file=None)
    assert s.storage_backend == "gdrive"
    assert s.day_rollover_hour == 5
    assert s.api_token.get_secret_value() == "tok-4f9a2c"
    assert "tok-4f9a2c" not in repr(s)


def test_validation() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, timezone="Mars/Olympus")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, day_rollover_hour=24)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, storage_backend="s3")


def test_env_example_documents_every_setting() -> None:
    text = (ROOT / ".env.example").read_text()
    documented = set(re.findall(r"^#?\s*(LIFELOG_[A-Z0-9_]+)=", text, re.MULTILINE))
    expected = {f"LIFELOG_{name.upper()}" for name in Settings.model_fields}
    assert expected - documented == set(), "add these to .env.example"
    assert documented - expected == set(), "remove these from .env.example"
