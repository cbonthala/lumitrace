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
from typing import Any

from pydantic import BaseModel, Field, field_validator

from lumitrace.frames.daycontent import (
    DayContent,
    FamilyTracker,
    TimelineAddition,
    TimelineDeletion,
    TimelineReplacement,
    from_legacy_day,
    to_legacy_facts,
)
from lumitrace.frames.dayfile import CAPTURE_LABELS, Capture, DayFacts, FamilyMember, Meal
from lumitrace.prism.pipeline.llm import LLMClient, LLMResult, model_max_output_tokens
from lumitrace.prism.pipeline.prompts import Prompt, day_template_path, load_prompt

log = logging.getLogger(__name__)


class DayDraft(BaseModel):
    """One complete Format 6 day returned by the fill prompt."""

    headline: str = ""
    content: DayContent
    journal: str = ""
    """Compatibility projection for callers that still inspect the old field."""
    facts: DayFacts = Field(default_factory=DayFacts)
    """Compatibility projection for Format 5 query surfaces during migration."""

    @field_validator("headline", "journal", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else ("" if value is None else value)


def parse_day_draft(raw: Any, members: Sequence[str]) -> DayDraft:
    """Validate Format 6, while accepting old fake/provider replies during migration."""
    if not isinstance(raw, dict):
        raise ValueError("day reply is not a JSON object")
    if isinstance(raw.get("timeline"), dict):
        content = keep_content_family(DayContent.model_validate(raw), members)
        journal = ""
    else:
        facts_raw = raw.get("facts")
        if not isinstance(facts_raw, dict):
            facts_raw = {key: raw[key] for key in DayFacts.model_fields if key in raw}
        if not facts_raw and not isinstance(raw.get("facts"), dict):
            raise ValueError("day reply has no timeline or facts object")
        facts = with_day_meals(keep_family(parse_facts(facts_raw), members))
        journal = str(raw.get("journal") or "")
        content = keep_content_family(
            from_legacy_day(facts.model_dump(mode="json"), journal), members
        )
    if content.is_blank():
        raise ValueError("day reply has no timeline or tracker facts")
    facts = DayFacts.model_validate(to_legacy_facts(content))
    return DayDraft(
        headline=raw.get("headline") or "",
        content=content,
        journal=journal,
        facts=facts,
    )


JournalAddition = TimelineAddition
JournalReplacement = TimelineReplacement


class DayUpdate(BaseModel):
    """Timeline patches plus complete structured tracker state."""

    additions: list[TimelineAddition] = Field(default_factory=list, max_length=20)
    replacements: list[TimelineReplacement] = Field(default_factory=list, max_length=20)
    deletions: list[TimelineDeletion] = Field(default_factory=list, max_length=20)
    headline: str = ""
    content: DayContent
    facts: DayFacts = Field(default_factory=DayFacts)

    @field_validator("headline", mode="before")
    @classmethod
    def _strip_headline(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else ("" if value is None else value)


def parse_day_update(raw: Any, members: Sequence[str]) -> DayUpdate:
    """Validate an update-day reply."""
    if not isinstance(raw, dict):
        raise ValueError("update reply is not a JSON object")
    if isinstance(raw.get("structured"), dict):
        structured = raw["structured"]
        content = DayContent.model_validate(
            {
                "timeline": {
                    "highlight": structured.get("highlight"),
                    "context": structured.get("context"),
                    "remember": structured.get("remember"),
                },
                "trackers": structured.get("trackers") or {},
            }
        )
        additions = raw.get("additions") or []
        replacements = raw.get("replacements") or []
        deletions = raw.get("deletions") or []
    elif isinstance(raw.get("facts"), dict):
        facts = with_day_meals(keep_family(parse_facts(raw["facts"]), members))
        content = from_legacy_day(facts.model_dump(mode="json"), "")
        aliases = {
            "Summary": "Time not stated",
            "Morning": "Morning",
            "Afternoon": "Afternoon",
            "Evening": "Evening",
            "Thoughts": "Time not stated",
        }
        additions = [
            {"section": aliases.get(item.get("section"), "Time not stated"), "text": item["text"]}
            for item in raw.get("additions") or []
        ]
        replacements = [
            {
                "find_section": aliases.get(item.get("section"), "Time not stated"),
                "find": item["find"],
                "replace_section": aliases.get(item.get("section"), "Time not stated"),
                "replace": item["replace"],
            }
            for item in raw.get("replacements") or []
        ]
        deletions = []
    else:
        raise ValueError("update reply has no structured or facts object")
    content = keep_content_family(content, members)
    facts = DayFacts.model_validate(to_legacy_facts(content))
    return DayUpdate.model_validate(
        {
            "additions": additions,
            "replacements": replacements,
            "deletions": deletions,
            "headline": raw.get("headline") or "",
            "content": content,
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


def keep_content_family(content: DayContent, members: Sequence[str]) -> DayContent:
    """Keep one tracker per configured family member, in configured order and spelling."""
    by_key = {name.casefold(): name for name in members}
    found = {}
    for member in content.family:
        name = by_key.get(member.name.casefold())
        if name is not None and name not in found:
            found[name] = member.model_copy(update={"name": name}, deep=True)
    ordered = [found.get(name) or FamilyTracker(name=name) for name in members]
    return content.model_copy(update={"family": ordered}, deep=True)


def format_capture(capture: Capture) -> str:
    label = CAPTURE_LABELS.get(capture.kind, capture.kind)
    head = f"### {capture.captured_at:%H:%M} · {label}"
    if capture.location:
        head += f" (location: {capture.location})"
    meta: list[str] = []
    if capture.audio:
        meta.append(f"audio: {capture.audio}")
    if capture.photos:
        meta.append("photos: " + ", ".join(capture.photos))
    body = capture.text.strip() or "(no words)"
    if meta:
        body = "\n".join(meta) + "\n\n" + body
    return f"{head}\n\n{body}"


def format_captures(captures: Sequence[Capture]) -> str:
    """Every capture that has words, audio or photos, in order, with nothing cut off."""
    return "\n\n".join(
        format_capture(c) for c in captures if c.text.strip() or c.audio or c.photos
    )


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
            weather="(none)",
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
            return {
                "headline": "",
                "timeline": {"time_not_stated": [body] if body else []},
                "trackers": {
                    "family": [{"name": name} for name in family],
                    "pregnancy_baby": {},
                    "tags": [],
                },
            }

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
            template=_day_template(self.prompts_dir),
            journal=journal.strip() or "(empty)",
            weather="(none)",
            notes=notes.strip() or "(none)",
            captures=format_captures(captures) or "(none)",
        )
        result = self.llm.complete_json(
            task="update_day",
            model=self.settings.llm_write_journal_model,
            messages=messages,
            parse=lambda raw: parse_day_update(raw, family),
            fake=lambda: {
                "headline": "",
                "additions": [
                    {"section": "Time not stated", "text": capture.text.strip()}
                    for capture in captures
                    if capture.text.strip() and capture.text.strip() not in journal
                ],
                "replacements": [],
                "deletions": [],
                "structured": {
                    "highlight": None,
                    "context": {},
                    "remember": None,
                    "trackers": {
                        "family": [{"name": name} for name in family],
                        "pregnancy_baby": {},
                        "tags": [],
                    },
                },
            },
        )
        return result, prompt
