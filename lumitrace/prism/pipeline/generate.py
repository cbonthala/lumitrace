"""AI steps: extract facts, write the journal, or write an addendum for an edited day.

Each step loads its versioned prompt, calls
:class:`~lumitrace.prism.pipeline.llm.LLMClient` and validates the JSON reply (facts against
:class:`lumitrace.frames.dayfile.DayFacts`).
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, field_validator

from lumitrace.frames.dayfile import CAPTURE_LABELS, Capture, DayFacts, FamilyMember
from lumitrace.prism.pipeline.llm import LLMClient, LLMResult
from lumitrace.prism.pipeline.prompts import Prompt, load_prompt


class JournalDraft(BaseModel):
    headline: str = ""
    journal: str

    @field_validator("headline", "journal", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else ("" if value is None else value)

    @field_validator("journal")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("journal is empty")
        return value


class Addendum(BaseModel):
    text: str = ""

    @field_validator("text", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else ("" if value is None else value)


def parse_facts(raw: Any) -> DayFacts:
    """Validate a fact-extraction reply. An out-of-range ``mood_score`` becomes null instead of
    failing the whole reply; a reply wrapped as ``{"facts": {...}}`` is unwrapped."""
    if isinstance(raw, dict) and set(raw) == {"facts"} and isinstance(raw["facts"], dict):
        raw = raw["facts"]
    if not isinstance(raw, dict):
        raise ValueError("facts reply is not a JSON object")
    data = dict(raw)
    score = data.get("mood_score")
    if score is not None and not (isinstance(score, int) and 1 <= score <= 5):
        data["mood_score"] = None
    return DayFacts.model_validate(data)


def keep_family(facts: DayFacts, members: Sequence[str]) -> DayFacts:
    """One block per configured family member, in config order and spelled as configured: the
    first entry the model gave for that name (any case), or an empty block. Nobody else gets a
    family section."""
    by_key = {name.casefold(): name for name in members}
    found: dict[str, FamilyMember] = {}
    for member in facts.family:
        name = by_key.get(member.name.casefold())
        if name is not None and name not in found:
            found[name] = member.model_copy(update={"name": name})
    ordered = [found.get(name) or FamilyMember(name=name) for name in members]
    return facts.model_copy(update={"family": ordered})


def format_capture(capture: Capture) -> str:
    label = CAPTURE_LABELS.get(capture.kind, capture.kind)
    head = f"### {capture.captured_at:%H:%M} · {label}"
    if capture.location:
        head += f" (location: {capture.location})"
    return f"{head}\n\n{capture.text.strip() or '(no words)'}"


def format_captures(captures: Sequence[Capture]) -> str:
    return "\n\n".join(format_capture(c) for c in captures if c.text.strip())


def _date_label(day: dt.date) -> str:
    return f"{day.isoformat()} ({day:%A})"


class Generator:
    def __init__(self, llm: LLMClient, prompts_dir: Path) -> None:
        self.llm = llm
        self.prompts_dir = prompts_dir
        self.settings = llm.settings

    def prompt(self, task: str) -> Prompt:
        return load_prompt(self.prompts_dir, task)

    def extract_facts(
        self, day: dt.date, captures: Sequence[Capture]
    ) -> tuple[LLMResult[DayFacts], Prompt]:
        prompt = self.prompt("extract_facts")
        locations = list(dict.fromkeys(c.location for c in captures if c.location))
        family = self.settings.family_members
        messages = prompt.render(
            date=_date_label(day),
            family=", ".join(family),
            location="; ".join(locations),
            captures=format_captures(captures),
        )
        result = self.llm.complete_json(
            task="extract_facts",
            model=self.settings.llm_extract_facts_model,
            messages=messages,
            parse=lambda raw: keep_family(parse_facts(raw), family),
            fake=lambda: {},
        )
        return result, prompt

    def write_journal(
        self, day: dt.date, captures: Sequence[Capture], facts: DayFacts
    ) -> tuple[LLMResult[JournalDraft], Prompt]:
        prompt = self.prompt("write_journal")
        messages = prompt.render(
            date=_date_label(day),
            facts=json.dumps(facts.model_dump(mode="json"), ensure_ascii=False, indent=2),
            captures=format_captures(captures),
        )

        def fake() -> dict[str, str]:
            body = "\n\n".join(c.text.strip() for c in captures if c.text.strip())
            return {"headline": "", "journal": f"## Summary\n\n{body}"}

        result = self.llm.complete_json(
            task="write_journal",
            model=self.settings.llm_write_journal_model,
            messages=messages,
            parse=JournalDraft.model_validate,
            fake=fake,
        )
        return result, prompt

    def write_addendum(
        self, day: dt.date, capture: Capture, journal: str
    ) -> tuple[LLMResult[Addendum], Prompt]:
        prompt = self.prompt("journal_addendum")
        messages = prompt.render(
            date=_date_label(day),
            journal=journal.strip() or "(empty)",
            capture=format_capture(capture),
        )
        result = self.llm.complete_json(
            task="journal_addendum",
            model=self.settings.llm_write_journal_model,
            messages=messages,
            parse=Addendum.model_validate,
            fake=lambda: {"text": capture.text.strip()},
        )
        return result, prompt
