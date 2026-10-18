from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from lumitrace.config import Settings, get_settings
from lumitrace.household import Household, Person

ROOT = Path(__file__).resolve().parents[1]


def test_defaults_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(__import__("os").environ):
        if key.startswith("LUMITRACE_"):
            monkeypatch.delenv(key)
    s = Settings(_env_file=None)
    assert s.timezone == "America/Chicago"
    assert s.day_rollover_hour == 4
    assert s.storage_backend == "local"
    assert s.gdrive_root_folder == "Lumitrace"
    assert s.embedding_dimension == 1536
    assert s.tz.key == "America/Chicago"


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUMITRACE_STORAGE_BACKEND", "gdrive")
    monkeypatch.setenv("LUMITRACE_DAY_ROLLOVER_HOUR", "5")
    monkeypatch.setenv("LUMITRACE_API_TOKEN", "tok-4f9a2c")
    s = Settings(_env_file=None)
    assert s.storage_backend == "gdrive"
    assert s.day_rollover_hour == 5
    assert s.api_token.get_secret_value() == "tok-4f9a2c"
    assert "tok-4f9a2c" not in repr(s)


def test_household_on_settings_drives_family_and_keyterms() -> None:
    household = Household(
        people=(Person("Sam", "me"), Person("Maya", "wife"), Person("Leo", "son")),
        notes="Leon is Leo's daycare friend.",
    )
    s = Settings(_env_file=None, household=household, stt_keyterms=" Corner Bakery ,maya,,")
    assert s.family_relations == {"Sam": "me", "Maya": "wife", "Leo": "son"}
    assert s.family_members == ["Sam", "Maya", "Leo"]
    assert s.owner_name == "Sam"
    assert s.glossary_text == "Leon is Leo's daycare friend."
    assert s.stt_keyterm_list == ["Sam", "Maya", "Leo", "Corner Bakery"]
    assert Settings(_env_file=None).family_members == []
    assert Settings(_env_file=None).glossary_text == "(none)"
    assert Settings(_env_file=None).stt_keyterm_list == []
    assert Settings(_env_file=None).owner_name is None


def test_settings_does_not_read_the_family_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "family.md"
    path.write_text("---\nfamily:\n  - name: Sam\n    relation: me\n---\n", encoding="utf-8")
    monkeypatch.setattr("lumitrace.household.family_file_candidates", lambda: (path,))
    assert Settings(_env_file=None).family_members == []


def test_get_settings_loads_the_first_family_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("---\nfamily:\n  - {name: Sam, relation: me}\n---\nnotes\n", encoding="utf-8")
    second.write_text("---\nfamily:\n  - {name: Maya, relation: wife}\n---\n", encoding="utf-8")
    monkeypatch.setattr("lumitrace.household.family_file_candidates", lambda: (first, second))
    get_settings.cache_clear()
    try:
        loaded = get_settings()
        assert loaded.owner_name == "Sam"
        assert loaded.glossary_text == "notes"
    finally:
        get_settings.cache_clear()


def test_validation() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, timezone="Mars/Olympus")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, day_rollover_hour=24)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, storage_backend="s3")


def test_env_example_documents_every_setting() -> None:
    text = (ROOT / ".env.example").read_text()
    documented = set(re.findall(r"^#?\s*(LUMITRACE_[A-Z0-9_]+)=", text, re.MULTILINE))
    expected = {f"LUMITRACE_{name.upper()}" for name in Settings.model_fields}
    assert expected - documented == set(), "add these to .env.example"
    assert documented - expected == set(), "remove these from .env.example"
