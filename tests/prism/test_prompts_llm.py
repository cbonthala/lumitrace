from __future__ import annotations

import datetime as dt
import logging
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from lumitrace.config import Settings
from lumitrace.frames.dayfile import Capture, DayFacts, FamilyMember, Meal
from lumitrace.household import Household, Person
from lumitrace.prism.pipeline.generate import (
    Generator,
    keep_family,
    parse_day_draft,
    parse_day_update,
    parse_facts,
)
from lumitrace.prism.pipeline.llm import LLMClient, LLMError, extract_json
from lumitrace.prism.pipeline.prompts import (
    PROMPT_TASKS,
    PromptError,
    join_prompt_labels,
    load_prompt,
    parse_prompt,
    resolve_prompts_dir,
)
from tests.prism.conftest import ROOT, FakeLLM


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
    gen.fill_day(day, [capture], "Owner note.")
    gen.update_day(day, [capture], "Owner note.", "## Summary\n\nEarlier.")
    assert sorted({c[0] for c in llm.calls}) == sorted(PROMPT_TASKS)
    for _, _, messages in llm.calls:
        for message in messages:
            assert "{{" not in message["content"]
    facts_user = llm.calls[0][2][1]["content"]
    assert "2026-10-10 (Saturday)" in facts_user
    assert "### 13:05 · Quick Note (location: Austin)\n\nTacos with Maya." in facts_user
    assert all("Owner note." in call[2][1]["content"] for call in llm.calls)


def test_prompt_files_follow_the_layout() -> None:
    for task in PROMPT_TASKS:
        path = ROOT / "prompts" / f"{task}.md"
        text = path.read_text(encoding="utf-8")
        prompt = parse_prompt(task, text)
        assert prompt.label == task
        assert re.search(r"(?i)never (invent|guess)", prompt.system), task
    template = ROOT / "prompts" / "day-template.md"
    assert template.is_file()
    assert "### Food" in template.read_text(encoding="utf-8")


def test_prompt_errors(tmp_path: Path) -> None:
    with pytest.raises(PromptError):
        parse_prompt("x", "no markers here")
    prompt = parse_prompt(
        "x", "<!-- lumitrace-prompt: system -->\nS {{a}}\n<!-- lumitrace-prompt: user -->\nU"
    )
    with pytest.raises(KeyError):
        prompt.render()
    assert prompt.render(a="1")[0]["content"] == "S 1"
    with pytest.raises(PromptError):
        load_prompt(tmp_path, "fill_day")


def test_relative_prompts_dir_falls_back_to_repository(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert resolve_prompts_dir(Path("prompts")) == ROOT / "prompts"


def test_join_prompt_labels() -> None:
    assert join_prompt_labels(["fill_day", "update_day"]) == "fill_day+update_day"
    assert join_prompt_labels(["fill_day", "fill_day"]) == "fill_day"
    assert join_prompt_labels([]) == ""


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


def test_keep_family_drops_unknown_names_and_uses_configured_spelling() -> None:
    facts = DayFacts(
        family=[
            FamilyMember(name="Sam", food=["cake"]),
            FamilyMember(name="leo", food=["pizza"]),
            FamilyMember(name="MAYA", moments=["new job"]),
            FamilyMember(name="Leo", food=["soup"]),
        ]
    )
    kept = keep_family(facts, ["Maya", "Leo"])
    assert kept.family == [
        FamilyMember(name="Maya", moments=["new job"]),
        FamilyMember(name="Leo", food=["pizza"]),
    ]
    assert keep_family(facts, []).family == []
    padded = keep_family(DayFacts(), ["Maya", "Leo"]).family
    assert padded == [FamilyMember(name="Maya"), FamilyMember(name="Leo")]


def test_fill_day_sends_the_family_list(api_settings: Settings) -> None:
    at = dt.datetime(2026, 10, 10, 13, 5, tzinfo=api_settings.tz)
    capture = Capture(id="c", kind="note", captured_at=at, text="x")
    with_owner_household = Household(
        people=(
            Person("Sam", "me"),
            Person("Maya", "wife", dt.date(1990, 4, 12)),
            Person("Leo"),
        )
    )
    no_owner = Household(people=(Person("Maya"), Person("Leo")))
    users = {}
    for key, household in (("owner", with_owner_household), ("none", no_owner)):
        llm = FakeLLM()
        gen = Generator(
            LLMClient(api_settings.with_household(household), completion_fn=llm),
            api_settings.prompts_dir,
        )
        gen.fill_day(dt.date(2026, 10, 10), [capture])
        users[key] = llm.calls[0][2][1]["content"]
    with_owner = users["owner"]
    assert "The author (the person speaking): Sam\n" in with_owner
    assert (
        "relation to the author (may be empty): "
        "Sam (the author), Maya (the author's wife, born 1990-04-12), Leo\n"
    ) in with_owner
    assert "The author (the person speaking): (not given)\n" in users["none"]
    assert "relation to the author (may be empty): Maya, Leo\n" in users["none"]


def test_glossary_is_sent_to_every_prompt(api_settings: Settings) -> None:
    at = dt.datetime(2026, 10, 10, 13, 5, tzinfo=api_settings.tz)
    capture = Capture(id="c", kind="note", captured_at=at, text="x")
    notes = "## Other people\n- Leon: Leo's daycare friend."
    for glossary, expected in ((notes, True), ("", False)):
        settings = api_settings.with_household(Household(notes=glossary))
        llm = FakeLLM()
        gen = Generator(LLMClient(settings, completion_fn=llm), settings.prompts_dir)
        gen.fill_day(dt.date(2026, 10, 10), [capture])
        gen.update_day(
            dt.date(2026, 10, 10), [capture], "Owner note.", "## Summary\n\nEarlier."
        )
        for _, _, messages in llm.calls:
            system = messages[0]["content"]
            assert (notes in system) is expected
            assert "Background from the owner's family file" in system
            assert ("(none)" in system) is (not expected)


def test_journal_gets_the_transcript_and_keyterms_not_a_translation(
    api_settings: Settings,
) -> None:
    settings = api_settings.model_copy(update={"stt_keyterms": "Corner Bakery"}).with_household(
        Household(people=(Person("Sam", "me"), Person("Maya", "wife")), notes="Leon is a friend.")
    )
    llm = FakeLLM()
    gen = Generator(LLMClient(settings, completion_fn=llm), settings.prompts_dir)
    at = dt.datetime(2026, 10, 10, 21, 30, tzinfo=settings.tz)
    capture = Capture(
        id="c",
        kind="recording",
        captured_at=at,
        text="mana park ki vellam",
        translation="We went to the park.",
    )
    gen.fill_day(dt.date(2026, 10, 10), [capture], "Owner note.")
    gen.update_day(
        dt.date(2026, 10, 10), [capture], "Owner note.", "## Summary\n\nEarlier."
    )
    assert [c[0] for c in llm.calls] == ["fill_day", "update_day"]
    for _, _, messages in llm.calls:
        user = messages[1]["content"]
        assert "mana park ki vellam" in user
        assert "Sam, Maya, Corner Bakery" in user
        assert "We went to the park." not in user
        assert "English translation" not in user
        assert "Leon is a friend." in messages[0]["content"]
    assert "Facts already extracted" not in llm.calls[0][2][1]["content"]


def test_update_reply_classifies_additions_by_journal_section() -> None:
    update = parse_day_update(
        {
            "additions": [
                {"section": "Afternoon", "text": "- Walked to the park."},
                {"section": "Thoughts", "text": "Felt grateful."},
            ]
        },
        [],
    )
    assert [(item.section, item.text) for item in update.additions] == [
        ("Afternoon", "Walked to the park."),
        ("Thoughts", "Felt grateful."),
    ]
    with pytest.raises(ValueError):
        parse_day_update({"additions": [{"section": "Later", "text": "No."}]}, [])


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


def test_fill_day_prompt_covers_the_ending_and_keeps_an_i_item_with_the_author() -> None:
    for task in ("fill_day", "update_day"):
        text = (ROOT / "prompts" / f"{task}.md").read_text(encoding="utf-8")
        assert "Cover the transcript to its last sentence." in text
        assert "check the final third of each" in text
        assert "uses 'we' for it." in text
        assert "'I drank coffee' is the author only." in text
    template = (ROOT / "prompts" / "day-template.md").read_text(encoding="utf-8")
    assert "Cover the transcript to its last sentence." in template
    assert "'I drank coffee' is the author only." in template


def test_day_level_meals_are_the_union_of_each_persons_meals() -> None:
    raw = {
        "headline": "Breakfast at home",
        "journal": "## Summary\n\n- Home.",
        "facts": {
            "meals": [{"type": "breakfast", "items": ["shared coffee"]}],
            "family": [
                {
                    "name": "Sam",
                    "meals": [
                        {"type": "breakfast", "items": ["coffee"]},
                        {"type": "dinner", "items": ["rice"]},
                    ],
                },
                {"name": "maya", "meals": [{"type": "breakfast", "items": ["Oatmeal"]}]},
                {"name": "Leo", "meals": [{"type": "breakfast", "items": ["oatmeal"]}]},
                {"name": "Priya", "meals": [{"type": "lunch", "items": ["soup"]}]},
            ],
        },
    }
    draft = parse_day_draft(raw, ["Sam", "Maya", "Leo"])
    assert draft.facts.meals == [
        Meal(type="breakfast", items=["coffee (Sam)", "Oatmeal (Maya, Leo)"]),
        Meal(type="dinner", items=["rice (Sam)"]),
    ]
    assert [member.name for member in draft.facts.family] == ["Sam", "Maya", "Leo"]
    assert draft.facts.family[1].meals == [Meal(type="breakfast", items=["Oatmeal"])]
    kept = parse_day_draft(
        {
            "journal": "## Summary\n\n- Tacos.",
            "facts": {"meals": [{"type": "lunch", "items": ["fish tacos"]}]},
        },
        [],
    )
    assert kept.facts.meals == [Meal(type="lunch", items=["fish tacos"])]


def test_fill_day_sends_the_whole_transcript(
    api_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    ending = "FINAL SENTENCE about bedtime."
    text = ("nanna coffee thaganu. " * 800) + ending
    at = dt.datetime(2026, 10, 10, 21, 30, tzinfo=api_settings.tz)
    capture = Capture(id="long", kind="recording", captured_at=at, text=text)
    llm = FakeLLM()
    gen = Generator(LLMClient(api_settings, completion_fn=llm), api_settings.prompts_dir)
    with caplog.at_level(logging.INFO, logger="lumitrace.prism.pipeline.generate"):
        gen.fill_day(dt.date(2026, 10, 10), [capture])
    user = llm.calls[0][2][1]["content"]
    assert text in user
    assert user.strip().endswith(ending)
    match = re.search(r"captures_chars=(\d+) transcript_chars=(\d+)", caplog.text)
    assert match is not None
    assert int(match.group(1)) > int(match.group(2)) == len(text)
    assert "captures=1" in caplog.text
    assert "transcript_complete=True" in caplog.text
    assert "max_output_tokens=" in caplog.text


def _json_reply(content: str, finish: str, tokens: int) -> Any:
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message, finish_reason=finish)
    usage = SimpleNamespace(completion_tokens=tokens)
    return SimpleNamespace(choices=[choice], usage=usage)


def test_journal_call_asks_for_the_model_max_output_tokens(
    api_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("lumitrace.prism.pipeline.llm.model_max_output_tokens", lambda model: 65536)
    seen: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> Any:
        seen.append(kwargs)
        return _json_reply('{"ok": true}', "stop", 40)

    client = LLMClient(api_settings, completion_fn=completion)
    result = client.complete_json(
        task="fill_day",
        model="gemini/gemini-3.8-flash",
        messages=[],
        parse=lambda raw: raw,
        fake=dict,
    )
    assert result.value == {"ok": True}
    assert seen[0]["max_tokens"] == 65536
    assert len(seen) == 1


def test_output_token_limit_is_raised_when_the_reply_is_cut_off(
    api_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("lumitrace.prism.pipeline.llm.model_max_output_tokens", lambda model: 1000)
    seen: list[int | None] = []

    def completion(**kwargs: Any) -> Any:
        limit = kwargs.get("max_tokens")
        seen.append(limit)
        if limit == 100:
            return _json_reply("not json", "length", 80)
        return _json_reply('{"ok": true}', "stop", 20)

    client = LLMClient(api_settings, completion_fn=completion)
    result = client.complete_json(
        task="fill_day",
        model="gemini/gemini-3.8-flash",
        messages=[],
        parse=lambda raw: raw,
        fake=dict,
        max_tokens=100,
    )
    assert seen == [100, 1000]
    assert result.value == {"ok": True}
    assert [attempt.ok for attempt in result.attempts] == [False, True]
    assert result.attempts[0].error == "output truncated"


def test_output_already_at_the_model_max_is_not_retried(
    api_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("lumitrace.prism.pipeline.llm.model_max_output_tokens", lambda model: 1000)
    seen: list[int | None] = []

    def completion(**kwargs: Any) -> Any:
        seen.append(kwargs.get("max_tokens"))
        return _json_reply('{"ok": true}', "length", 1000)

    client = LLMClient(api_settings, completion_fn=completion)
    result = client.complete_json(
        task="fill_day",
        model="gemini/gemini-3.8-flash",
        messages=[],
        parse=lambda raw: raw,
        fake=dict,
    )
    assert seen == [1000]
    assert result.value == {"ok": True}
