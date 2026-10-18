"""AI steps: fill a day in one call, or classify missing source into journal sections.

Each step loads its prompt, calls
:class:`~lumitrace.prism.pipeline.llm.LLMClient` and validates the JSON reply (facts against
:class:`lumitrace.frames.dayfile.DayFacts`).
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from lumitrace.frames.dayfile import CAPTURE_LABELS, Capture, DayFacts, FamilyMember, Meal
from lumitrace.prism.pipeline.llm import LLMClient, LLMResult, model_max_output_tokens
from lumitrace.prism.pipeline.prompts import Prompt, day_template_path, load_prompt

log = logging.getLogger(__name__)


class DayDraft(BaseModel):
    """One reply that fills the day: the At a glance facts and the journal page."""

    headline: str = ""
    journal: str
    facts: DayFacts = Field(default_factory=DayFacts)

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


def parse_day_draft(raw: Any, members: Sequence[str]) -> DayDraft:
    """Validate a fill-day reply. Facts may be nested under ``facts`` or sit beside the journal."""
    if not isinstance(raw, dict):
        raise ValueError("day reply is not a JSON object")
    facts_raw = raw.get("facts")
    if not isinstance(facts_raw, dict):
        facts_raw = {key: raw[key] for key in DayFacts.model_fields if key in raw}
    if not facts_raw and not isinstance(raw.get("facts"), dict):
        raise ValueError("day reply has no facts object")
    facts = with_day_meals(keep_family(parse_facts(facts_raw), members))
    draft = DayDraft.model_validate(
        {"headline": raw.get("headline"), "journal": raw.get("journal")}
    )
    return draft.model_copy(update={"facts": facts})


class JournalAddition(BaseModel):
    """One new journal bullet and the existing section it belongs in."""

    section: Literal["Summary", "Morning", "Afternoon", "Evening", "Thoughts"]
    text: str = ""

    @field_validator("text", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        if value is None:
            return ""
        if not isinstance(value, str):
            return value
        return " ".join(value.removeprefix("-").split())

    @field_validator("text")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("journal addition is empty")
        return value


class JournalReplacement(BaseModel):
    """One generated sentence a newer recording or My notes contradict."""

    section: Literal["Summary", "Morning", "Afternoon", "Evening", "Thoughts"] = "Summary"
    find: str = ""
    replace: str = ""

    @field_validator("find", "replace", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        if value is None:
            return ""
        if not isinstance(value, str):
            return value
        return " ".join(value.removeprefix("-").split())

    @field_validator("find", "replace")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("journal replacement is empty")
        return value


class DayUpdate(BaseModel):
    """Journal edits plus a complete facts candidate for owner-safe merging.

    ``additions`` are bullets the page does not already contain. ``replacements`` correct a
    generated sentence that a newer source contradicts. Facts are the whole day, not a delta.
    """

    additions: list[JournalAddition] = Field(default_factory=list, max_length=20)
    replacements: list[JournalReplacement] = Field(default_factory=list, max_length=20)
    facts: DayFacts = Field(default_factory=DayFacts)


def parse_day_update(raw: Any, members: Sequence[str]) -> DayUpdate:
    """Validate an update-day reply."""
    if not isinstance(raw, dict):
        raise ValueError("update reply is not a JSON object")
    if not isinstance(raw.get("facts"), dict):
        raise ValueError("update reply has no facts object")
    facts = with_day_meals(keep_family(parse_facts(raw["facts"]), members))
    return DayUpdate.model_validate(
        {
            "additions": raw.get("additions") or [],
            "replacements": raw.get("replacements") or [],
            "facts": facts,
        }
    )


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
    """Every non-empty transcript, in order, with nothing cut off."""
    return "\n\n".join(format_capture(c) for c in captures if c.text.strip())


def meals_from_family(facts: DayFacts) -> list[Meal]:
    """Day-level meals: each family meal, tagged with who had it.

    The same dish for several people is one item, names in family order:
    ``oatmeal (Maya, Leo)``. The model is not asked for this list.
    """
    names_for: dict[tuple[str, str], list[str]] = {}
    display: dict[tuple[str, str], str] = {}
    order: list[tuple[str, str]] = []
    for member in facts.family:
        name = member.name.strip()
        if not name:
            continue
        for meal in member.meals:
            for item in meal.items:
                key = (meal.type, item.casefold())
                if key not in display:
                    display[key] = item
                    names_for[key] = []
                    order.append(key)
                if name not in names_for[key]:
                    names_for[key].append(name)
    by_type: dict[str, list[str]] = {}
    for key in order:
        meal_type, _item = key
        tagged = f"{display[key]} ({', '.join(names_for[key])})"
        by_type.setdefault(meal_type, []).append(tagged)
    if not by_type:
        return []
    meals = [Meal(type=meal_type, items=items) for meal_type, items in by_type.items()]
    return DayFacts(meals=meals).meals


def with_day_meals(facts: DayFacts) -> DayFacts:
    """Replace day-level meals with :func:`meals_from_family` when anyone has a meal.

    A reply that only filled the day-level list (no per-person meals) is left as it is.
    """
    derived = meals_from_family(facts)
    if not derived:
        return facts
    return facts.model_copy(update={"meals": derived})


def _log_fill_input(day: dt.date, captures: Sequence[Capture], model: str) -> str:
    """Log how much transcript is sent, and that none of it was cut. Returns the text."""
    rendered = format_captures(captures)
    texts = [c.text.strip() for c in captures if c.text.strip()]
    missing = sum(1 for text in texts if text not in rendered)
    transcript_chars = sum(len(text) for text in texts)
    ceiling = model_max_output_tokens(model)
    log.info(
        "fill_day %s: captures_chars=%d transcript_chars=%d captures=%d "
        "transcript_complete=%s max_output_tokens=%s",
        day.isoformat(),
        len(rendered),
        transcript_chars,
        len(texts),
        missing == 0,
        ceiling if ceiling is not None else "unknown",
    )
    if missing:
        log.warning(
            "fill_day %s: %d capture(s) missing from the text sent to the model",
            day.isoformat(),
            missing,
        )
    return rendered


def _date_label(day: dt.date) -> str:
    return f"{day.isoformat()} ({day:%A})"


def _day_template(prompts_dir: Path) -> str:
    """The Markdown shape the fill-day prompt shows the model (``prompts/day-template.md``)."""
    return day_template_path(prompts_dir).read_text(encoding="utf-8")


class Generator:
    def __init__(self, llm: LLMClient, prompts_dir: Path) -> None:
        self.llm = llm
        self.prompts_dir = prompts_dir
        self.settings = llm.settings

    def prompt(self, task: str) -> Prompt:
        return load_prompt(self.prompts_dir, task)

    def _people(self) -> dict[str, str]:
        """The ``author``, ``family`` and ``glossary`` prompt values, from the family file."""
        return {
            "author": self.settings.owner_name or "(not given)",
            "family": self.settings.household.describe(),
            "glossary": self.settings.glossary_text,
        }

    def _keyterms(self) -> str:
        """Names, places and brands the transcript was biased toward, or ``(none)``."""
        terms = self.settings.stt_keyterm_list
        return ", ".join(terms) if terms else "(none)"

    def fill_day(
        self, day: dt.date, captures: Sequence[Capture], notes: str = ""
    ) -> tuple[LLMResult[DayDraft], Prompt]:
        """One call: transcripts, My notes, glossary, keyterms, and the day template.

        The reply is facts plus the journal page. The day file is written from that reply.
        No English translation is included.
        """
        prompt = self.prompt("fill_day")
        family = self.settings.family_members
        messages = prompt.render(
            date=_date_label(day),
            **self._people(),
            keyterms=self._keyterms(),
            template=_day_template(self.prompts_dir),
            notes=notes.strip() or "(none)",
            captures=_log_fill_input(day, captures, self.settings.llm_write_journal_model),
        )

        def fake() -> dict[str, Any]:
            body = "\n\n".join(
                part
                for part in (
                    *(c.text.strip() for c in captures if c.text.strip()),
                    notes.strip(),
                )
                if part
            )
            return {"headline": "", "journal": f"## Summary\n\n{body}", "facts": {}}

        result = self.llm.complete_json(
            task="fill_day",
            model=self.settings.llm_write_journal_model,
            messages=messages,
            parse=lambda raw: parse_day_draft(raw, family),
            fake=fake,
        )
        return result, prompt

    def update_day(
        self,
        day: dt.date,
        captures: Sequence[Capture],
        notes: str,
        journal: str,
    ) -> tuple[LLMResult[DayUpdate], Prompt]:
        """Return journal corrections, missing bullets and complete facts."""
        prompt = self.prompt("update_day")
        family = self.settings.family_members
        messages = prompt.render(
            date=_date_label(day),
            **self._people(),
            keyterms=self._keyterms(),
            journal=journal.strip() or "(empty)",
            notes=notes.strip() or "(none)",
            captures=format_captures(captures) or "(none)",
        )
        result = self.llm.complete_json(
            task="update_day",
            model=self.settings.llm_write_journal_model,
            messages=messages,
            parse=lambda raw: parse_day_update(raw, family),
            fake=lambda: {
                "additions": [
                    {"section": "Summary", "text": capture.text.strip()}
                    for capture in captures
                    if capture.text.strip() and capture.text.strip() not in journal
                ],
                "facts": {},
            },
        )
        return result, prompt
