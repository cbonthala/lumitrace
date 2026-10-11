from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from lifelog.config import Settings
from lifelog.dayfile import Capture, DayFacts
from lifelog.pipeline.generate import Generator, parse_facts
from lifelog.pipeline.llm import LLMClient, LLMError, extract_json
from lifelog.pipeline.prompts import (
    PROMPT_VERSIONS,
    PromptError,
    combined_version,
    load_prompt,
    parse_prompt,
    resolve_prompts_dir,
)
from tests.api.conftest import ROOT, FakeLLM


def test_every_current_prompt_exists_and_renders(api_settings: Settings) -> None:
    llm = FakeLLM()
    gen = Generator(LLMClient(api_settings, completion_fn=llm), api_settings.prompts_dir)
    day = dt.date(2026, 10, 10)
    capture = Capture(
        id="c",
        kind="note",
        captured_at=dt.datetime(2026, 10, 10, 13, 5, tzinfo=api_settings.tz),
        text="Tacos with Maya.",
        location="Austin",
    )
    facts, _ = gen.extract_facts(day, [capture])
    gen.write_journal(day, [capture], facts.value)
    gen.write_addendum(day, capture, "## Summary\n\nEarlier.")
    assert sorted({c[0] for c in llm.calls}) == sorted(PROMPT_VERSIONS)
    for _, _, messages in llm.calls:
        for message in messages:
            assert "{{" not in message["content"]
    facts_user = llm.calls[0][2][1]["content"]
    assert "2026-10-10 (Saturday)" in facts_user
    assert "### 13:05 · Quick Note (location: Austin)\n\nTacos with Maya." in facts_user


def test_prompt_files_follow_the_layout() -> None:
    for task, version in PROMPT_VERSIONS.items():
        path = ROOT / "prompts" / task / f"{version}.md"
        text = path.read_text(encoding="utf-8")
        prompt = parse_prompt(task, version, text)
        assert prompt.label == f"{task}-{version}"
        assert re.search(r"(?i)never (invent|guess)", prompt.system), task


def test_prompt_errors(tmp_path: Path) -> None:
    with pytest.raises(PromptError):
        parse_prompt("x", "v1", "no markers here")
    prompt = parse_prompt(
        "x", "v1", "<!-- lifelog-prompt: system -->\nS {{a}}\n<!-- lifelog-prompt: user -->\nU"
    )
    with pytest.raises(KeyError):
        prompt.render()
    assert prompt.render(a="1")[0]["content"] == "S 1"
    with pytest.raises(PromptError):
        load_prompt(tmp_path, "extract_facts")


def test_relative_prompts_dir_falls_back_to_repository(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert resolve_prompts_dir(Path("prompts")) == ROOT / "prompts"


def test_combined_version() -> None:
    assert combined_version(["extract_facts-v1", "write_journal-v2"]) == (
        "extract_facts-v1+write_journal-v2"
    )
    assert combined_version([]) == ""


def test_extract_json_tolerates_fences_and_chatter() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Here you go:\n{"a": {"b": 2}}\nThanks!') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        extract_json("no json at all")


def test_parse_facts_validates_against_dayfacts() -> None:
    facts = parse_facts({"facts": {"mood": "ok", "mood_score": 9, "people": None}})
    assert facts == DayFacts(mood="ok")
    with pytest.raises(ValueError):
        parse_facts(["not", "an", "object"])
    with pytest.raises(ValueError):
        parse_facts({"meals": [{"items": ["no type"]}]})


def test_llm_client_passes_config_and_falls_back(api_settings: Settings) -> None:
    seen: list[dict] = []

    def completion(**kwargs):
        seen.append(kwargs)
        if kwargs["model"] == "primary":
            raise RuntimeError("rate limited")
        msg = SimpleNamespace(content='{"ok": true}')
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    settings = api_settings.model_copy(
        update={"llm_fallback_model": "backup", "llm_timeout_seconds": 7, "llm_max_retries": 1}
    )
    client = LLMClient(settings, completion_fn=completion)
    result = client.complete_json(
        task="t", model="primary", messages=[], parse=lambda raw: raw, fake=dict
    )
    assert result.value == {"ok": True}
    assert result.model == "backup"
    assert [a.ok for a in result.attempts] == [False, True]
    assert seen[0]["timeout"] == 7 and seen[0]["num_retries"] == 1
    assert seen[0]["response_format"] == {"type": "json_object"}
    assert client.models_for("backup") == ["backup"]

    def always_fails(**kwargs):
        raise RuntimeError("down")

    with pytest.raises(LLMError) as info:
        LLMClient(settings, completion_fn=always_fails).complete_json(
            task="t", model="primary", messages=[], parse=lambda raw: raw, fake=dict
        )
    assert [a.model for a in info.value.attempts] == ["primary", "backup"]
