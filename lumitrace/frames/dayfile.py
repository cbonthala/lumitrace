"""The day-file contract: paths, entry dates, and the Markdown format of one day.

Full specification with an example: ``docs/frames-format.md``. Summary of the layout::

    ---
    <YAML front matter: FrontMatter>
    ---

    # <title>

    <!-- lumitrace:journal:start ... -->         generated journal (DayFile.journal)
    <!-- lumitrace:journal:end -->

    ## My notes

    <!-- lumitrace:notes:start ... -->           the owner's notes (DayFile.notes); never changed
    <!-- lumitrace:notes:end -->

    ## Transcript

    <!-- lumitrace:transcript:start ... -->      one block per Capture, oldest first; append-only
    <!-- lumitrace:capture {json} -->
    ### 21:30 · Log My Day
    ![[2026-10-10-2130.m4a]]

    transcript text
    <!-- lumitrace:transcript:end -->

Format 4 does not write ``## At a glance`` or an English translation (ADR 0057). :func:`parse`
still reads both from older files. The next :func:`render` drops them. Format 1 kept facts in
the front matter; :func:`parse` still reads those too.

Edit protection: ``FrontMatter.generated_hash`` is a hash of the facts, title and journal as the
system last wrote them. A format 4 write hashes empty facts. If the current content no longer
matches, the owner edited it (:meth:`DayFile.is_user_edited`) and :func:`apply_generation`
refuses to replace it; use :func:`merge_generation_additive` instead. Text found outside the
known regions is moved into the notes region on the next render, so it is never lost.

Files written under the project's earlier names use ``lifelog:`` (LifeLog, 0.1.0),
``bookshelf:`` (Bookshelf) or ``lumen:`` (Lumen) markers and a ``lifelog_format``,
``bookshelf_format`` or ``lumen_format`` key; :func:`parse` still reads them and :func:`render`
writes the current names.

All storage paths are relative to the Lumitrace root folder (see
``lumitrace.frames.storage.base``).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Iterable
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

FORMAT_VERSION = 4
SYSTEM_DIR = "_system"
AUDIO_EXT = ".m4a"
PHOTO_EXT = ".jpg"

FACTS_START = (
    "<!-- lumitrace:facts:start (found by Lumitrace; if you edit them, your edits are kept) -->"
)
FACTS_END = "<!-- lumitrace:facts:end -->"
JOURNAL_START = (
    "<!-- lumitrace:journal:start (written by Lumitrace; if you edit it, your edits are kept) -->"
)
JOURNAL_END = "<!-- lumitrace:journal:end -->"
NOTES_START = (
    "<!-- lumitrace:notes:start (your own notes; Lumitrace never changes this section) -->"
)
NOTES_END = "<!-- lumitrace:notes:end -->"
TRANSCRIPT_START = "<!-- lumitrace:transcript:start (raw transcripts, added by Lumitrace) -->"
TRANSCRIPT_END = "<!-- lumitrace:transcript:end -->"
CAPTURE_MARKER = "lumitrace:capture"
TRANSLATION_MARKER = "<!-- lumitrace:translation (English translation of the recording) -->"
TRANSLATION_HEADING = "#### English translation"
MARKER_PREFIXES: tuple[str, ...] = ("lumitrace", "lumen", "bookshelf", "lifelog")
"""Marker prefixes :func:`parse` accepts; the first is written, the rest are legacy."""
FORMAT_KEY = "lumitrace_format"
LEGACY_FORMAT_KEYS: tuple[str, ...] = ("lumen_format", "bookshelf_format", "lifelog_format")
"""Older names of :data:`FORMAT_KEY`; :func:`parse` reads them, newest first."""
FACTS_HEADING = "## At a glance"
NOTES_HEADING = "## My notes"
TRANSCRIPT_HEADING = "## Transcript"

CaptureKind = Literal["recording", "note"]
CAPTURE_LABELS: dict[str, str] = {"recording": "Log My Day", "note": "Quick Note"}
PathKind = Literal["day", "audio", "photo", "system", "other"]


class DayFileParseError(ValueError):
    """The Markdown could not be parsed as a day file (for example, broken front matter)."""


class UserEditsDetected(RuntimeError):
    """Raised by :func:`apply_generation` when the owner has edited generated content."""

    def __init__(self, day: dt.date) -> None:
        super().__init__(f"{day.isoformat()} has user edits; refusing to overwrite")
        self.day = day


# --- Paths ----------------------------------------------------------------------------------


def day_dir(day: dt.date) -> str:
    """``YYYY/MM/YYYY-MM-DD``"""
    return f"{day:%Y}/{day:%m}/{day.isoformat()}"


def day_file_path(day: dt.date) -> str:
    """``YYYY/MM/YYYY-MM-DD/YYYY-MM-DD.md``"""
    return f"{day_dir(day)}/{day.isoformat()}.md"


def audio_file_name(day: dt.date, local_time: dt.datetime | dt.time) -> str:
    """``YYYY-MM-DD-HHMM.m4a``: the entry date plus the local wall-clock capture time.

    A recording at 01:30 on Oct 11 that belongs to Oct 10 is named ``2026-10-10-0130.m4a``.
    Use :func:`unique_file_name` to avoid collisions within the day folder.
    """
    return f"{day.isoformat()}-{local_time:%H%M}{AUDIO_EXT}"


def audio_file_path(day: dt.date, local_time: dt.datetime | dt.time) -> str:
    return f"{day_dir(day)}/{audio_file_name(day, local_time)}"


def photo_file_name(number: int) -> str:
    """``photo-NN.jpg`` (1-based, at least two digits)."""
    if number < 1:
        raise ValueError("photo numbers start at 1")
    return f"photo-{number:02d}{PHOTO_EXT}"


def photo_file_path(day: dt.date, number: int) -> str:
    return f"{day_dir(day)}/{photo_file_name(number)}"


_PHOTO_RE = re.compile(r"^photo-(\d+)\.jpg$")


def next_photo_names(existing: Iterable[str], count: int) -> list[str]:
    """The next ``count`` photo names after the highest ``photo-NN.jpg`` in ``existing``."""
    highest = 0
    for name in existing:
        m = _PHOTO_RE.match(name.rsplit("/", 1)[-1])
        if m:
            highest = max(highest, int(m.group(1)))
    return [photo_file_name(highest + i) for i in range(1, count + 1)]


def unique_file_name(name: str, existing: Iterable[str]) -> str:
    """``name`` if unused, else ``stem-2.ext``, ``stem-3.ext``, ..."""
    taken = {e.rsplit("/", 1)[-1] for e in existing}
    if name not in taken:
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    n = 2
    while True:
        candidate = f"{stem}-{n}.{ext}" if dot else f"{stem}-{n}"
        if candidate not in taken:
            return candidate
        n += 1


def system_path(*parts: str) -> str:
    """Path under ``_system/`` (activity records, feedback, snapshots, backups)."""
    clean = [p.strip("/") for p in parts if p.strip("/")]
    return "/".join([SYSTEM_DIR, *clean])


def generated_snapshot_path(day: dt.date) -> str:
    """``_system/generated/YYYY/MM/YYYY-MM-DD.md``: exact copy of the day file as the system
    last wrote it. The indexer diffs the live file against it to record edit signals."""
    return system_path("generated", f"{day:%Y}", f"{day:%m}", f"{day.isoformat()}.md")


_DAY_PATH_RE = re.compile(r"^(\d{4})/(\d{2})/(\d{4})-(\d{2})-(\d{2})/(\d{4}-\d{2}-\d{2})\.md$")
_DAY_DIR_RE = re.compile(r"^(\d{4})/(\d{2})/(\d{4}-\d{2}-\d{2})/[^/]+$")


def parse_day_file_path(path: str) -> dt.date | None:
    """The date if ``path`` is a canonical day-file path, else ``None``."""
    m = _DAY_PATH_RE.match(path)
    if not m:
        return None
    year, month, y2, m2, d2, stem = m.groups()
    if (year, month) != (y2, m2) or stem != f"{y2}-{m2}-{d2}":
        return None
    try:
        return dt.date(int(y2), int(m2), int(d2))
    except ValueError:
        return None


def date_of_path(path: str) -> dt.date | None:
    """The day folder's date for any file inside a ``YYYY/MM/YYYY-MM-DD/`` folder."""
    m = _DAY_DIR_RE.match(path)
    if not m:
        return None
    try:
        day = dt.date.fromisoformat(m.group(3))
    except ValueError:
        return None
    return day if (f"{day:%Y}", f"{day:%m}") == (m.group(1), m.group(2)) else None


def classify_path(path: str) -> PathKind:
    if path == SYSTEM_DIR or path.startswith(SYSTEM_DIR + "/"):
        return "system"
    if parse_day_file_path(path):
        return "day"
    if date_of_path(path):
        name = path.rsplit("/", 1)[-1]
        if name.endswith(AUDIO_EXT):
            return "audio"
        if _PHOTO_RE.match(name):
            return "photo"
    return "other"


# --- Entry dates ----------------------------------------------------------------------------


def entry_date(
    captured_at: dt.datetime,
    tz: str | ZoneInfo = "America/Chicago",
    rollover_hour: int = 4,
) -> dt.date:
    """The journal day a capture belongs to. Before ``rollover_hour`` counts as the previous day.

    Naive datetimes are interpreted as local time in ``tz``.
    """
    zone = ZoneInfo(tz) if isinstance(tz, str) else tz
    local = captured_at.replace(tzinfo=zone) if captured_at.tzinfo is None else captured_at
    local = local.astimezone(zone)
    day = local.date()
    if local.hour < rollover_hour:
        day -= dt.timedelta(days=1)
    return day


def default_title(day: dt.date) -> str:
    """``Saturday, October 10, 2026``"""
    return f"{day:%A}, {day:%B} {day.day}, {day.year}"


# --- Models ---------------------------------------------------------------------------------


def _strip(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


StrippedStr = Annotated[str, BeforeValidator(_strip)]


NONE_TEXT = "not mentioned"
"""Written in place of an empty fact, so every day file has the same lines; read back as empty
(together with the format 2 spelling ``none``)."""
NONE_TEXTS: frozenset[str] = frozenset({NONE_TEXT, "none"})
NOT_LOOKED_UP = "not looked up"
"""Written in place of an empty weather; read back as empty (also with a city in brackets)."""
UNCERTAIN_MARK = "[uncertain:"
"""A fact the AI was not sure about ends with ``[uncertain: why]``; kept as text."""


def _is_none_text(value: Any) -> bool:
    return isinstance(value, str) and value.casefold() in NONE_TEXTS


def _one_line(value: Any) -> Any:
    """Collapse whitespace so a fact fits on one Markdown bullet line."""
    return " ".join(value.split()) if isinstance(value, str) else value


def _one_line_or_none(value: Any) -> Any:
    value = _one_line(value)
    if _is_none_text(value):
        return None
    return value or None if isinstance(value, str) else value


def _clean_list(value: Any, split: re.Pattern[str] | None = None) -> Any:
    """One-line strings, empty ones dropped; with ``split``, strings are also split into items."""
    if value is None:
        return []
    if not isinstance(value, list):
        return value
    out: list[Any] = []
    for item in value:
        item = _one_line(item)
        if isinstance(item, str):
            parts = split.split(item) if split else [item]
            out.extend(p for p in parts if p and not _is_none_text(p))
        else:
            out.append(item)
    return out


_COMMA_RE = re.compile(r"\s*,\s*")
_SEMICOLON_RE = re.compile(r"\s*;\s*")


def _split_outside_parens(value: str, sep: str = ",") -> list[str]:
    """Split on ``sep`` only outside parentheses, so ``oatmeal (Maya, Leo)`` stays one item."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for char in value:
        if char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        if char == sep and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(char)
    parts.append("".join(buf))
    return parts


def _comma_items(value: Any) -> Any:
    """Like :func:`_clean_list` with a comma split, but commas inside parentheses stay."""
    if value is None:
        return []
    if not isinstance(value, list):
        return value
    out: list[Any] = []
    for item in value:
        item = _one_line(item)
        if isinstance(item, str):
            out.extend(
                part.strip()
                for part in _split_outside_parens(item)
                if part.strip() and not _is_none_text(part.strip())
            )
        else:
            out.append(item)
    return out


def _semicolon_items(value: Any) -> Any:
    return _clean_list(value, _SEMICOLON_RE)


FactLine = Annotated[str, BeforeValidator(_one_line)]
OptionalFactLine = Annotated[str | None, BeforeValidator(_one_line_or_none)]
FactList = Annotated[list[str], BeforeValidator(_clean_list)]
CommaItems = Annotated[list[str], BeforeValidator(_comma_items)]
"""Rendered comma-separated on one line, so the items never contain commas."""
SemicolonItems = Annotated[list[str], BeforeValidator(_semicolon_items)]
"""Rendered semicolon-separated on one line, so the items never contain semicolons."""


MEAL_TYPES: tuple[str, ...] = ("breakfast", "lunch", "dinner", "snacks")
"""The only meal types, in render order. Every person has one Food line per type."""

MEAL_LABELS: dict[str, str] = {
    "breakfast": "Morning",
    "lunch": "Lunch",
    "dinner": "Dinner",
    "snacks": "Snacks / drinks / other",
}
"""The label of each meal type on a person's Food lines."""

_MEAL_TYPE_ALIASES: dict[str, str] = {
    **{label.casefold(): meal for meal, label in MEAL_LABELS.items()},
    "morning": "breakfast",
    "snack": "snacks",
    "drink": "snacks",
    "drinks": "snacks",
    "beverage": "snacks",
    "beverages": "snacks",
    "other": "snacks",
    "snacks/drinks/other": "snacks",
    "supper": "dinner",
    "brunch": "lunch",
}


class Meal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str
    """One of :data:`MEAL_TYPES`. A few synonyms are mapped ("morning", "drinks", "supper",
    "brunch"); anything else becomes "snacks"."""
    items: CommaItems = Field(default_factory=list)

    @field_validator("type", mode="before")
    @classmethod
    def _clean_type(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        key = " ".join(value.replace(":", " ").split()).lower()
        key = _MEAL_TYPE_ALIASES.get(key, key)
        return key if key in MEAL_TYPES else "snacks"


class Activity(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: FactLine
    """Never contains ";" (a family member's activities share one line, separated by "; ")."""
    minutes: int | None = None

    @field_validator("kind", mode="before")
    @classmethod
    def _no_semicolons(cls, value: Any) -> Any:
        if _is_none_text(_one_line(value)):
            return ""
        return value.replace(";", ",") if isinstance(value, str) else value


def _normalise_meals(meals: list[Meal]) -> list[Meal]:
    """One meal per type, in :data:`MEAL_TYPES` order; meals without items are dropped."""
    merged: dict[str, Meal] = {}
    for meal in meals:
        if meal.type in merged:
            _add_unique(merged[meal.type].items, meal.items)
        elif meal.items:
            merged[meal.type] = meal.model_copy(deep=True)
    return [merged[t] for t in MEAL_TYPES if t in merged]


class FamilyMember(BaseModel):
    """One family member's day: a ``#### name`` block in each per-person section of "At a
    glance" (Food, Health and fitness, Feelings, Memories). The Prism writes a block for every
    configured member (`secrets/family.md`), with nothing in it when the day says nothing about
    them; the owner may add others by hand."""

    model_config = ConfigDict(extra="ignore")
    name: FactLine
    meals: list[Meal] = Field(default_factory=list)
    """What they ate or drank, by meal."""
    health: SemicolonItems = Field(default_factory=list)
    """Sleep, sickness, doctor visits, medicine, workouts: only what was plainly said."""
    feelings: SemicolonItems = Field(default_factory=list)
    """How they felt, in the speaker's words."""
    moments: SemicolonItems = Field(default_factory=list)
    """Memories: firsts, quotes, milestones, e.g. "lost his first tooth"."""

    @field_validator("meals", mode="before")
    @classmethod
    def _none_is_empty(cls, value: Any) -> Any:
        return [] if value is None else value

    @model_validator(mode="after")
    def _normalise(self) -> FamilyMember:
        self.meals = _normalise_meals(self.meals)
        return self

    def has_facts(self) -> bool:
        return self.model_copy(update={"name": ""}) != FamilyMember(name="")


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value) if isinstance(value, list | tuple) else [value]


def _migrate_legacy_facts(data: dict[str, Any]) -> dict[str, Any]:
    """Facts in the format 1 and 2 shape, as a dict in the current shape.

    Format 2 family blocks had ``mood``, ``food``, ``places``, ``activities`` and ``school``.
    Mood becomes a feeling; places, activities and school move to the day's places and things
    we did with the person's name in brackets; food becomes meals: a person whose food holds all
    of the day's (top-level) meals gets those meals, the rest of the food goes under snacks.
    Top-level meals nobody could be given stay as the day's own "Everyone" meals. Current-shape
    data passes through unchanged."""
    data = dict(data)
    unassigned = _as_list(data.get("meals"))
    places = _as_list(data.get("places"))
    activities = _as_list(data.get("activities"))
    family: list[Any] = []
    for raw in _as_list(data.get("family")):
        if not isinstance(raw, dict):
            family.append(raw)
            continue
        member = dict(raw)
        name = str(member.get("name") or "").strip()
        feelings = _as_list(member.get("feelings"))
        mood = member.pop("mood", None)
        if isinstance(mood, str) and mood.strip() and not _is_none_text(mood.strip()):
            feelings.append(mood)
        member["feelings"] = feelings
        for place in _legacy_items(member.pop("places", None), _COMMA_RE):
            places.append(f"{place} ({name})" if name else place)
        for activity in _as_list(member.pop("activities", None)):
            if isinstance(activity, dict) and name:
                activity = {**activity, "kind": f"{activity.get('kind', '')} ({name})"}
            elif isinstance(activity, Activity) and name:
                activity = {"kind": f"{activity.kind} ({name})", "minutes": activity.minutes}
            activities.append(activity)
        for item in _legacy_items(member.pop("school", None), _SEMICOLON_RE):
            activities.append({"kind": f"school/work: {item} ({name})" if name else item})
        food = _legacy_items(member.pop("food", None), _COMMA_RE)
        meals = _as_list(member.get("meals"))
        if food:
            known = {str(i).casefold() for m in unassigned for i in _as_list(_item(m, "items"))}
            if unassigned and known and known <= {f.casefold() for f in food}:
                meals = [*meals, *unassigned]
                food = [f for f in food if f.casefold() not in known]
                unassigned = []
            if food:
                meals = [*meals, {"type": "snacks", "items": food}]
        member["meals"] = meals
        family.append(member)
    data["family"], data["places"], data["activities"], data["meals"] = (
        family,
        places,
        activities,
        unassigned,
    )
    return data


def _legacy_items(value: Any, split: re.Pattern[str]) -> list[str]:
    """Strings of a format 2 list, split into items, without empty or "none" items."""
    out: list[str] = []
    for raw in _as_list(value):
        for part in split.split(" ".join(str(raw).split())):
            if part and not _is_none_text(part):
                out.append(part)
    return out


def _item(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else getattr(value, key, None)


class DayFacts(BaseModel):
    """Structured facts about a day: the "At a glance" region of the day file. This is also the
    shape the fact-extraction step returns. Values are normalised (one line each, no empty or
    ``not mentioned`` items, one meal per type of :data:`MEAL_TYPES` in that order, family
    members kept even when empty) so that rendering and parsing them back gives the same facts.
    Facts in the older shape (format 1 and 2) are converted when validated."""

    model_config = ConfigDict(extra="ignore")
    mood: OptionalFactLine = None
    mood_score: int | None = Field(default=None, ge=1, le=5)
    city: OptionalFactLine = None
    weather: OptionalFactLine = None
    """From a lookup for the places visited, never guessed; empty when not looked up."""
    highlights: FactList = Field(default_factory=list)
    remember: OptionalFactLine = None
    """The one moment worth keeping (a first, a funny quote, a feeling)."""
    meals: list[Meal] = Field(default_factory=list)
    """Meals nobody in particular is named for (the "Everyone" block under Food)."""
    places: FactList = Field(default_factory=list)
    """Places someone went to, with who went in brackets: "Ravi's house (Maya, Leo)"."""
    people: FactList = Field(default_factory=list)
    """People met or visited: "Ravi, friend - at his house (Sam, Maya)"."""
    memories: FactList = Field(default_factory=list)
    """Memories the whole family shares ("Together")."""
    activities: list[Activity] = Field(default_factory=list)
    """Things we did, with who in brackets: "grocery shopping (Sam, Maya)"."""
    family: list[FamilyMember] = Field(default_factory=list)
    """Per family member: what they ate, health, feelings and memories."""

    @model_validator(mode="before")
    @classmethod
    def _migrate(cls, data: Any) -> Any:
        return _migrate_legacy_facts(data) if isinstance(data, dict) else data

    @field_validator("weather", mode="before")
    @classmethod
    def _not_looked_up(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip().casefold().startswith(NOT_LOOKED_UP):
            return None
        return value

    @field_validator("meals", "activities", "family", mode="before")
    @classmethod
    def _none_is_empty(cls, value: Any) -> Any:
        return [] if value is None else value

    @model_validator(mode="after")
    def _normalise_entries(self) -> DayFacts:
        self.meals = _normalise_meals(self.meals)
        self.activities = [a for a in self.activities if a.kind]
        self.family = [f for f in self.family if f.name]
        return self

    def is_empty(self) -> bool:
        return self == DayFacts()


FACT_FIELDS: tuple[str, ...] = tuple(DayFacts.model_fields)
FORMAT_1_FACT_KEYS: tuple[str, ...] = (
    "mood",
    "mood_score",
    "city",
    "weather",
    "people",
    "meals",
    "activities",
    "family_events",
    "highlights",
)
"""Front-matter keys that held the facts in format 1 (``family_events`` became highlights)."""


class FrontMatter(BaseModel):
    """YAML front matter: the date, media and provenance. The facts are not here (they are in
    the "At a glance" region). Unknown keys (for example Obsidian ``tags``) are preserved."""

    model_config = ConfigDict(extra="allow")
    date: dt.date
    audio: list[str] = Field(default_factory=list)
    """Audio file names in the day folder, oldest first."""
    photos: list[str] = Field(default_factory=list)
    """Photo file names in the day folder."""
    prompt_version: str | None = None
    models_used: dict[str, str] = Field(default_factory=dict)
    """Task -> LiteLLM model string, e.g. ``{"stt": ..., "extract_facts": ...}``."""
    generated_at: dt.datetime | None = None
    generated_hash: str | None = None
    generated_source_hash: str | None = None
    """Hash of the transcripts and My notes already incorporated into the journal."""
    lumitrace_format: int = FORMAT_VERSION

    @field_validator("audio", "photos", mode="before")
    @classmethod
    def _none_is_empty_list(cls, value: Any) -> Any:
        return [] if value is None else value

    @field_validator("models_used", mode="before")
    @classmethod
    def _none_is_empty_dict(cls, value: Any) -> Any:
        return {} if value is None else value


FRONT_MATTER_ORDER: tuple[str, ...] = (
    "date",
    "audio",
    "photos",
    "prompt_version",
    "models_used",
    "generated_at",
    "generated_hash",
    "generated_source_hash",
    "lumitrace_format",
)


class Capture(BaseModel):
    """One recording or quick note, shown in the Transcript section."""

    id: str
    """Unique within the day; merging a capture whose id already exists is a no-op."""
    kind: CaptureKind
    captured_at: dt.datetime
    """Timezone-aware, in the owner's local timezone (its wall clock is shown in the heading)."""
    text: StrippedStr = ""
    """Raw transcript (recording) or note text."""
    translation: StrippedStr = ""
    """English translation of the recording, when the speech-to-text provider made one."""
    audio: str | None = None
    photos: list[str] = Field(default_factory=list)
    location: str | None = None

    @field_validator("captured_at")
    @classmethod
    def _aware(cls, value: dt.datetime) -> dt.datetime:
        if value.tzinfo is None:
            raise ValueError("captured_at must be timezone-aware")
        return value

    @staticmethod
    def make_id(kind: str, captured_at: dt.datetime) -> str:
        return f"{captured_at:%Y%m%dT%H%M%S}-{kind}"


def _hash_generated(facts: dict[str, Any], title: str, journal: str) -> str:
    payload = {"facts": facts, "title": title, "journal": journal}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _format_1_facts(raw: dict[str, Any]) -> dict[str, Any]:
    """The facts exactly as format 1 hashed them (raw front-matter values, format 1 fields)."""

    def dicts(key: str) -> list[dict[str, Any]]:
        return [v for v in raw.get(key) or [] if isinstance(v, dict)]

    return {
        "mood": raw.get("mood"),
        "mood_score": raw.get("mood_score"),
        "city": raw.get("city"),
        "weather": raw.get("weather"),
        "people": raw.get("people") or [],
        "meals": [{"type": m.get("type"), "items": m.get("items") or []} for m in dicts("meals")],
        "activities": [
            {"kind": a.get("kind"), "minutes": a.get("minutes")} for a in dicts("activities")
        ],
        "family_events": raw.get("family_events") or [],
        "highlights": raw.get("highlights") or [],
    }


class DayFile(BaseModel):
    meta: FrontMatter
    title: StrippedStr = ""
    facts: DayFacts = Field(default_factory=DayFacts)
    """The "At a glance" region (mood, food, places, people, ...)."""
    journal: StrippedStr = ""
    """Generated journal Markdown (``##`` sections), between the journal markers."""
    notes: StrippedStr = ""
    """The owner's notes. The system never modifies this."""
    captures: list[Capture] = Field(default_factory=list)

    @model_validator(mode="after")
    def _default_title(self) -> DayFile:
        if not self.title:
            self.title = default_title(self.meta.date)
        return self

    @property
    def date(self) -> dt.date:
        return self.meta.date

    @classmethod
    def new(cls, day: dt.date) -> DayFile:
        return cls(meta=FrontMatter(date=day))

    def compute_generated_hash(self) -> str:
        return _hash_generated(self.facts.model_dump(mode="json"), self.title, self.journal)

    def compute_source_hash(self) -> str:
        """Hash the owner-provided material that can feed journal generation."""
        payload = {
            "notes": self.notes,
            "captures": [
                {
                    "id": capture.id,
                    "kind": capture.kind,
                    "captured_at": capture.captured_at.isoformat(),
                    "text": capture.text,
                    "location": capture.location,
                }
                for capture in self.captures
            ],
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def is_user_edited(self) -> bool:
        """True if facts, title or journal differ from what the system last generated."""
        stored = self.meta.generated_hash
        return stored is not None and stored != self.compute_generated_hash()

    def capture_ids(self) -> set[str]:
        return {c.id for c in self.captures}


# --- Rendering ------------------------------------------------------------------------------


def _front_matter_dict(meta: FrontMatter) -> dict[str, Any]:
    data = meta.model_dump(mode="python")
    out: dict[str, Any] = {}
    for key in FRONT_MATTER_ORDER:
        value = data[key]
        if key == "generated_source_hash" and value is None:
            continue
        if key == "generated_at" and value is not None:
            value = value.isoformat()
        out[key] = value
    for key, value in (meta.model_extra or {}).items():
        out[key] = value
    return out


def _capture_comment(capture: Capture) -> str:
    meta = {
        "id": capture.id,
        "kind": capture.kind,
        "captured_at": capture.captured_at.isoformat(),
        "audio": capture.audio,
        "photos": capture.photos,
        "location": capture.location,
    }
    raw = json.dumps(meta, ensure_ascii=False, separators=(", ", ": "))
    safe = raw.replace(">", "\\u003e")
    return f"<!-- {CAPTURE_MARKER} {safe} -->"


def _render_capture(capture: Capture) -> str:
    label = CAPTURE_LABELS.get(capture.kind, capture.kind)
    lines = [_capture_comment(capture), f"### {capture.captured_at:%H:%M} · {label}"]
    if capture.audio:
        lines.append(f"![[{capture.audio}]]")
    lines.extend(f"![[{p}]]" for p in capture.photos)
    if capture.text:
        lines.extend(["", capture.text])
    return "\n".join(lines) + "\n"


def _region(start: str, content: str, end: str) -> str:
    return f"{start}\n{content}\n{end}\n" if content else f"{start}\n{end}\n"


FACT_SECTIONS: tuple[tuple[str, str], ...] = (
    ("Highlight", "highlights"),
    ("Food", "meals"),
    ("Places visited", "places"),
    ("People we met or visited", "people"),
    ("Health and fitness", "health"),
    ("Feelings", "feelings"),
    ("Memories", "memories"),
    ("Weather", "weather"),
    ("Things we did", "activities"),
)
"""``(heading, topic)`` of the ``###`` sections in "At a glance", in render order. Food, Health
and fitness, Feelings and Memories are per person (a ``#### name`` block each)."""

PERSON_SECTIONS: tuple[str, ...] = ("meals", "health", "feelings", "memories")
TOGETHER = "Together"
"""The ``####`` block under Memories for memories the whole family shares."""
EVERYONE = "Everyone"
"""The ``####`` block under Food for meals nobody in particular is named for."""
REMEMBER_LABEL = "Remember"
"""The last line under Highlight: the one moment worth keeping."""

_SECTION_ALIASES: dict[str, str] = {
    **{heading.casefold(): name for heading, name in FACT_SECTIONS},
    "highlights": "highlights",
    "meals": "meals",
    "places": "places",
    "people": "people",
    "health": "health",
    "memory": "memories",
    "activities": "activities",
    "things": "activities",
}
_PERSON_FIELD = {"health": "health", "feelings": "feelings", "memories": "moments"}


def _mood_text(facts: DayFacts) -> str | None:
    if facts.mood and facts.mood_score:
        return f"{facts.mood} ({facts.mood_score}/5)"
    if facts.mood_score:
        return f"{facts.mood_score}/5"
    return facts.mood


def _activity_text(activity: Activity) -> str:
    return f"{activity.kind} ({activity.minutes} min)" if activity.minutes else activity.kind


def _meal_lines(meals: list[Meal], include_empty: bool) -> list[str]:
    items = {m.type: ", ".join(m.items) for m in meals}
    return [
        f"- **{MEAL_LABELS[t]}:** {items.get(t) or NONE_TEXT}"
        for t in MEAL_TYPES
        if t in items or include_empty
    ]


def _person_blocks(facts: DayFacts, topic: str, include_empty: bool) -> list[str]:
    """The ``#### name`` blocks of a per-person section (Together and Everyone included)."""
    blocks: list[tuple[str, list[str]]] = []
    if topic == "memories":
        blocks.append((TOGETHER, [f"- {m}" for m in facts.memories]))
    if topic == "meals" and facts.meals:
        blocks.append((EVERYONE, _meal_lines(facts.meals, include_empty=False)))
    for member in facts.family:
        if topic == "meals":
            lines = _meal_lines(member.meals, include_empty)
        else:
            lines = [f"- {i}" for i in getattr(member, _PERSON_FIELD[topic])]
        blocks.append((member.name, lines))
    out = []
    for name, lines in blocks:
        if not lines and include_empty:
            lines = [f"- {NONE_TEXT}"]
        if lines:
            out.append(f"#### {name}\n\n" + "\n".join(lines))
    return out


def render_facts_section(facts: DayFacts, *, include_empty: bool = True) -> str:
    """The Markdown inside the facts markers.

    Every day file has the same lines in the same order: Mood and City; then each ``###
    heading`` of :data:`FACT_SECTIONS`. The per-person sections (Food, Health and fitness,
    Feelings, Memories) have a ``#### name`` block for every family member (Food has one line per
    :data:`MEAL_TYPES`; Memories starts with ``Together``). Empty facts are written as ``not
    mentioned`` (``not looked up`` for the weather). With ``include_empty=False`` (the index's
    view) empty lines, sections and people are left out, and no facts at all give an empty
    string."""
    blocks: list[str] = []
    scalars = [
        f"- **{label}:** {value or NONE_TEXT}"
        for label, value in (("Mood", _mood_text(facts)), ("City", facts.city))
        if value or include_empty
    ]
    if scalars:
        blocks.append("\n".join(scalars))
    for heading, topic in FACT_SECTIONS:
        lines: list[str]
        if topic == "highlights":
            lines = [f"- {item}" for item in facts.highlights]
            if facts.remember or include_empty:
                lines.append(f"- **{REMEMBER_LABEL}:** {facts.remember or NONE_TEXT}")
            if not facts.highlights and include_empty:
                lines.insert(0, f"- {NONE_TEXT}")
        elif topic in PERSON_SECTIONS:
            lines = ["\n\n".join(_person_blocks(facts, topic, include_empty))]
            lines = [lines[0]] if lines[0] else []
        elif topic == "weather":
            lines = (
                [f"- {facts.weather or NOT_LOOKED_UP}"] if facts.weather or include_empty else []
            )
        elif topic == "activities":
            lines = [f"- {_activity_text(a)}" for a in facts.activities]
        else:
            lines = [f"- {item}" for item in getattr(facts, topic)]
        if not lines and include_empty:
            lines = [f"- {NONE_TEXT}"]
        if lines:
            blocks.append(f"### {heading}\n\n" + "\n".join(lines))
    return "\n\n".join(blocks)


JOURNAL_SECTIONS: tuple[str, ...] = (
    "Summary",
    "Morning",
    "Afternoon",
    "Evening",
    "Thoughts",
)
"""The only ``##`` headings of a system-written journal, in order."""

_JOURNAL_ALIASES: dict[str, str] = {
    **{name.casefold(): name for name in JOURNAL_SECTIONS},
    "overview": "Summary",
    "night": "Evening",
    "tonight": "Evening",
    "reflection": "Thoughts",
    "reflections": "Thoughts",
    "plans": "Thoughts",
    "thoughts and plans": "Thoughts",
    "later": "Evening",
}


_JOURNAL_HEADING_RE = re.compile(r"^##[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)


def normalize_journal(markdown: str) -> str:
    """Give a generated journal the fixed ``##`` headings of :data:`JOURNAL_SECTIONS`.

    Known headings (any level, a few aliases such as "Night") become their section; sections
    come out in the fixed order, repeated ones merged, empty ones left out. Text before the
    first heading belongs to Summary. Any other heading is kept as a bold line inside the
    section it appears in, so no words are lost. Idempotent."""
    sections: dict[str, list[str]] = {}
    current = JOURNAL_SECTIONS[0]
    in_fence = False
    for line in markdown.strip().split("\n"):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
        heading = None if in_fence else _FACT_HEADING_RE.match(stripped)
        if heading:
            title = heading.group(1).strip().rstrip(":").strip()
            known = _JOURNAL_ALIASES.get(title.casefold())
            if known:
                current = known
                continue
            line = f"**{title}**"
        sections.setdefault(current, []).append(line)
    blocks = []
    for name in JOURNAL_SECTIONS:
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(sections.get(name, [])).strip())
        if text:
            blocks.append(f"## {name}\n\n{text}")
    return "\n\n".join(blocks)


def merge_journal_sections(markdown: str, additions: dict[str, list[str]]) -> str:
    """Insert new bullets into their journal sections without changing existing words.

    Sections already on the page keep their exact heading and content. A missing section is
    inserted in :data:`JOURNAL_SECTIONS` order. A legacy ``Later`` heading becomes ``Evening``;
    its content is preserved and ``Later`` is deliberately not a target.
    """
    result = _JOURNAL_HEADING_RE.sub(
        lambda match: (
            "## Evening"
            if match.group(1).strip().casefold() == "later"
            else match.group(0)
        ),
        markdown.strip(),
    )
    by_section: dict[str, list[str]] = {name: [] for name in JOURNAL_SECTIONS}
    for raw_name, items in additions.items():
        name = _JOURNAL_ALIASES.get(raw_name.strip().casefold())
        if name not in JOURNAL_SECTIONS:
            raise ValueError(f"unknown journal section: {raw_name!r}")
        for item in items:
            text = " ".join(str(item).split()).strip()
            if not text:
                continue
            by_section[name].append(text if text.startswith("- ") else f"- {text}")

    for name in JOURNAL_SECTIONS:
        if not by_section[name]:
            continue
        block = "\n".join(by_section[name])
        matches = list(_JOURNAL_HEADING_RE.finditer(result))
        target_index = next(
            (
                index
                for index, match in enumerate(matches)
                if _JOURNAL_ALIASES.get(match.group(1).strip().casefold()) == name
            ),
            None,
        )
        if target_index is not None:
            end = (
                matches[target_index + 1].start()
                if target_index + 1 < len(matches)
                else len(result)
            )
            before = result[:end].rstrip()
            after = result[end:].lstrip()
            result = f"{before}\n\n{block}" + (f"\n\n{after}" if after else "")
            continue

        order = JOURNAL_SECTIONS.index(name)
        insert_at = len(result)
        for match in matches:
            existing = _JOURNAL_ALIASES.get(match.group(1).strip().casefold())
            if existing in JOURNAL_SECTIONS and JOURNAL_SECTIONS.index(existing) > order:
                insert_at = match.start()
                break
        new_section = f"## {name}\n\n{block}"
        before = result[:insert_at].rstrip()
        after = result[insert_at:].lstrip()
        result = (f"{before}\n\n" if before else "") + new_section
        if after:
            result += f"\n\n{after}"
    return result


def render(day: DayFile) -> str:
    """Render a day file: title, journal, notes and transcripts.

    Format 4 does not write ``## At a glance`` or an English translation (ADR 0057).
    ``parse`` still reads both from older files. Dropping them on an unedited day refreshes
    ``generated_hash`` so that drop is not itself an edit.
    """
    written = day.model_copy(deep=True)
    written.facts = DayFacts()
    for capture in written.captures:
        capture.translation = ""
    if written.meta.generated_hash is not None and not day.is_user_edited():
        written.meta.generated_hash = written.compute_generated_hash()
    front = yaml.safe_dump(
        _front_matter_dict(written.meta),
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=4096,
    )
    transcript = "\n".join(_render_capture(c) for c in written.captures)
    return "".join(
        [
            "---\n",
            front,
            "---\n\n",
            f"# {written.title}\n\n",
            _region(JOURNAL_START, written.journal, JOURNAL_END),
            "\n",
            f"{NOTES_HEADING}\n\n",
            _region(NOTES_START, written.notes, NOTES_END),
            "\n",
            f"{TRANSCRIPT_HEADING}\n\n",
            f"{TRANSCRIPT_START}\n",
            transcript,
            f"{TRANSCRIPT_END}\n",
        ]
    )


# --- Parsing --------------------------------------------------------------------------------

_FRONT_RE = re.compile(r"\A---[ \t]*\n(.*?)^---[ \t]*$\n?", re.DOTALL | re.MULTILINE)
_PREFIX_RE = "(?:" + "|".join(MARKER_PREFIXES) + ")"
_CAPTURE_RE = re.compile(
    r"^[ \t]*<!--\s*" + _PREFIX_RE + r":capture\s+(\{.*?\})\s*-->[ \t]*$", re.MULTILINE
)
_TRANSLATION_RE = re.compile(
    r"^[ \t]*<!--\s*" + _PREFIX_RE + r":translation\b.*?-->[ \t]*$", re.MULTILINE
)
_TRANSLATION_HEADING_RE = re.compile(r"\A#{1,6}[ \t]+English translation[ \t]*(?:\n|\Z)", re.I)
_TITLE_RE = re.compile(r"^#[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_EMBED_RE = re.compile(r"^!\[\[([^\]]+)\]\]$")


def _marker_re(name: str, edge: str) -> re.Pattern[str]:
    return re.compile(r"<!--\s*" + _PREFIX_RE + ":" + name + ":" + edge + r"\b.*?-->", re.DOTALL)


def _take_region(body: str, name: str) -> tuple[str | None, str]:
    """Return (inner content or None if markers are missing, body with the region removed)."""
    start = _marker_re(name, "start").search(body)
    if not start:
        return None, body
    end = _marker_re(name, "end").search(body, start.end())
    if not end:
        return None, body
    inner = body[start.end() : end.start()]
    return inner.strip(), body[: start.start()] + "\n" + body[end.end() :]


def _remove_line(text: str, line: str) -> str:
    pattern = re.compile(r"^" + re.escape(line) + r"[ \t]*$\n?", re.MULTILINE)
    return pattern.sub("", text, count=1)


def _parse_captures(region: str) -> tuple[list[Capture], str]:
    """Return captures and any stray text that appeared before the first capture marker."""
    matches = list(_CAPTURE_RE.finditer(region))
    stray = region[: matches[0].start()] if matches else region
    captures: list[Capture] = []
    for i, m in enumerate(matches):
        block_end = matches[i + 1].start() if i + 1 < len(matches) else len(region)
        block = region[m.end() : block_end]
        try:
            meta = json.loads(m.group(1))
        except json.JSONDecodeError as exc:
            raise DayFileParseError(f"bad capture metadata: {m.group(1)!r}") from exc
        embeds = {meta.get("audio"), *(meta.get("photos") or [])} - {None}
        lines = block.split("\n")
        idx = 0
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
        if idx < len(lines) and lines[idx].startswith("### "):
            idx += 1
        while idx < len(lines):
            line = lines[idx].strip()
            embed = _EMBED_RE.match(line)
            if not line or (embed and embed.group(1) in embeds):
                idx += 1
                continue
            break
        meta["text"], meta["translation"] = _split_translation("\n".join(lines[idx:]))
        try:
            captures.append(Capture.model_validate(meta))
        except ValidationError as exc:
            raise DayFileParseError(f"invalid capture {meta.get('id')!r}: {exc}") from exc
    return captures, stray.strip()


def _split_translation(body: str) -> tuple[str, str]:
    """``(text, translation)`` of a capture body: the translation follows the translation marker,
    under an optional "English translation" heading."""
    marker = _TRANSLATION_RE.search(body)
    if not marker:
        return body, ""
    translation = body[marker.end() :].strip()
    heading = _TRANSLATION_HEADING_RE.match(translation)
    if heading:
        translation = translation[heading.end() :]
    return body[: marker.start()], translation


_FACT_HEADING_RE = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$")
_BULLET_RE = re.compile(r"^(?:[-*+][ \t]+)?(.*)$")
_LABEL_RE = re.compile(r"^(?:\*\*)?[ \t]*([^:*]+?)[ \t]*(?:\*\*)?[ \t]*:[ \t]*(?:\*\*)?[ \t]*(.*)$")
_MOOD_RE = re.compile(r"^(.*?)[ \t]*\(?[ \t]*([1-5])[ \t]*/[ \t]*5[ \t]*\)?$")
_MINUTES_RE = re.compile(r"^(.*?)[ \t]*\([ \t]*(\d+)[ \t]*min(?:ute)?s?[ \t]*\)$", re.IGNORECASE)


def _parse_scalar(text: str, data: dict[str, Any]) -> bool:
    """A ``Mood``, ``City`` or ``Weather`` line before any section. False if it is none of them."""
    label = _LABEL_RE.match(text)
    key = label.group(1).casefold() if label else None
    if label and key == "mood":
        mood = _MOOD_RE.match(label.group(2))
        if mood:
            data["mood"] = mood.group(1) or None
            data["mood_score"] = int(mood.group(2))
        else:
            data["mood"] = label.group(2)
    elif label and key in ("city", "weather"):
        data[key] = label.group(2)
    else:
        return False
    return True


_LEVELED_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")


def parse_facts_section(
    markdown: str, *, source_format: int = FORMAT_VERSION
) -> tuple[DayFacts, str]:
    """Parse the Markdown inside the facts markers. Returns ``(facts, stray)``.

    ``source_format`` is the file's format: 3 is the current layout (:func:`render_facts_section`),
    older files are read with :func:`_parse_facts_v2` and converted. Tolerates hand edits:
    bullets are optional, labels may or may not be bold, headings may use any level and the
    aliases in :data:`_SECTION_ALIASES`. Under a per-person section, any heading that is not a
    section name starts a person's block. Lines that fit nowhere (an unknown label or heading,
    and everything under an unknown heading) are returned as ``stray`` text, which :func:`parse`
    moves into the notes so nothing is lost.
    """
    if source_format < 3:
        return _parse_facts_v2(markdown)
    data: dict[str, Any] = {n: [] for n in ("people", "places", "highlights", "memories")}
    unassigned: list[dict[str, Any]] = []
    activities: list[dict[str, Any]] = []
    members: dict[str, dict[str, Any]] = {}
    stray: list[str] = []
    section: str | None = None
    person: str | None = None
    unknown_section = False
    for raw in markdown.split("\n"):
        line = raw.strip()
        if not line:
            continue
        heading = _LEVELED_HEADING_RE.match(line)
        if heading:
            title = heading.group(2).strip()
            known = _SECTION_ALIASES.get(title.casefold())
            if known is None and section in PERSON_SECTIONS and not unknown_section:
                person = title
                key = title.casefold()
                if key not in (TOGETHER.casefold(), EVERYONE.casefold()) and key not in members:
                    members[key] = {"name": title, "meals": [], "health": [], "feelings": []}
                    members[key]["moments"] = []
                continue
            section, person, unknown_section = known, None, known is None
            if unknown_section:
                stray.append(line)
            continue
        if unknown_section:
            stray.append(line)
            continue
        text = _BULLET_RE.match(line).group(1).strip()  # type: ignore[union-attr]
        if _is_none_text(text):
            continue
        member = members.get((person or "").casefold())
        if section is None:
            if not _parse_scalar(text, data):
                stray.append(line)
        elif section == "highlights":
            label = _LABEL_RE.match(text)
            if label and label.group(1).casefold() == REMEMBER_LABEL.casefold():
                if not _is_none_text(label.group(2)):
                    data["remember"] = label.group(2)
            else:
                data["highlights"].append(text)
        elif section == "meals":
            label = _LABEL_RE.match(text)
            meal_type, items = (label.group(1), label.group(2)) if label else ("snacks", text)
            target = member["meals"] if member else unassigned
            target.append({"type": meal_type, "items": [items]})
        elif section == "memories":
            if member:
                member["moments"].append(text)
            elif person is None or person.casefold() == TOGETHER.casefold():
                data["memories"].append(text)
            else:
                stray.append(line)
        elif section in ("health", "feelings"):
            if member:
                member[_PERSON_FIELD[section]].append(text)
            else:
                stray.append(line)
        elif section == "weather":
            data["weather"] = text
        elif section == "activities":
            activities.append(_parse_activity(text))
        else:
            data[section].append(text)
    try:
        facts = DayFacts.model_validate(
            {
                **data,
                "meals": unassigned,
                "activities": activities,
                "family": list(members.values()),
            }
        )
    except ValidationError as exc:
        raise DayFileParseError(f"invalid facts: {exc}") from exc
    return facts, "\n".join(stray)


_V2_SECTION_ALIASES: dict[str, str] = {
    "food": "meals",
    "meals": "meals",
    "places": "places",
    "places visited": "places",
    "people": "people",
    "activities": "activities",
    "family": "family",
    "family events": "family",
    "highlights": "highlights",
}
_V2_FAMILY_ALIASES: dict[str, str] = {
    "mood": "mood",
    "ate": "food",
    "food": "food",
    "meals": "food",
    "went to": "places",
    "places": "places",
    "did": "activities",
    "activities": "activities",
    "moments": "moments",
    "moment": "moments",
    "milestones": "moments",
    "health": "health",
    "school/work": "school",
    "school": "school",
    "work": "school",
    "school / work": "school",
}


def _parse_facts_v2(markdown: str) -> tuple[DayFacts, str]:
    """Parse the facts of a format 2 file (Food lines, Places, People, Activities, Family
    blocks, Highlights) and convert them to the current shape (see
    :func:`_migrate_legacy_facts`). Same tolerance and stray handling as the current parser."""
    data: dict[str, Any] = {n: [] for n in ("people", "places", "highlights")}
    meals: list[dict[str, Any]] = []
    activities: list[dict[str, Any]] = []
    family: list[dict[str, Any]] = []
    stray: list[str] = []
    section: str | None = None
    unknown_section = False
    for raw in markdown.split("\n"):
        line = raw.strip()
        if not line:
            continue
        heading = _FACT_HEADING_RE.match(line)
        if heading:
            title = heading.group(1).strip()
            known = _V2_SECTION_ALIASES.get(title.casefold())
            if known is None and section == "family" and not unknown_section:
                family.append({"name": title, "activities": []})
                continue
            section, unknown_section = known, known is None
            if unknown_section:
                stray.append(line)
            continue
        if unknown_section:
            stray.append(line)
            continue
        text = _BULLET_RE.match(line).group(1).strip()  # type: ignore[union-attr]
        if _is_none_text(text):
            continue
        if section == "family":
            label = _LABEL_RE.match(text)
            field = _V2_FAMILY_ALIASES.get(label.group(1).casefold()) if label else None
            if not family or label is None or field is None:
                stray.append(line)
            elif field == "mood":
                family[-1]["mood"] = label.group(2)
            elif field == "activities":
                family[-1]["activities"].extend(
                    _parse_activity(a) for a in _SEMICOLON_RE.split(label.group(2)) if a
                )
            else:
                family[-1].setdefault(field, []).append(label.group(2))
        elif section is None:
            if not _parse_scalar(text, data):
                stray.append(line)
        elif section == "meals":
            label = _LABEL_RE.match(text)
            meal_type, items = (label.group(1), label.group(2)) if label else ("snacks", text)
            meals.append({"type": meal_type, "items": [items]})
        elif section == "activities":
            activities.append(_parse_activity(text))
        else:
            data[section].append(text)
    try:
        facts = DayFacts.model_validate(
            {**data, "meals": meals, "activities": activities, "family": family}
        )
    except ValidationError as exc:
        raise DayFileParseError(f"invalid facts: {exc}") from exc
    return facts, "\n".join(stray)


def _parse_activity(text: str) -> dict[str, Any]:
    minutes = _MINUTES_RE.match(text)
    if minutes:
        return {"kind": minutes.group(1), "minutes": int(minutes.group(2))}
    return {"kind": text}


def parse(markdown: str, *, fallback_date: dt.date | None = None) -> DayFile:
    """Parse a day file. Tolerates edits: text outside the known regions becomes notes.

    ``fallback_date`` is used if the front matter has no ``date`` (pass the date from the path).
    Raises :class:`DayFileParseError` if the front matter is missing or invalid.
    """
    text = markdown.replace("\r\n", "\n").lstrip("\ufeff")
    fm = _FRONT_RE.match(text)
    if not fm:
        raise DayFileParseError("missing YAML front matter")
    try:
        data = yaml.safe_load(fm.group(1)) or {}
    except yaml.YAMLError as exc:
        raise DayFileParseError(f"invalid YAML front matter: {exc}") from exc
    if not isinstance(data, dict):
        raise DayFileParseError("front matter must be a mapping")
    fm_data = dict(data)
    if data.get("date") is None and fallback_date is not None:
        data["date"] = fallback_date
    for legacy_key in LEGACY_FORMAT_KEYS:
        if legacy_key in data:
            data.setdefault(FORMAT_KEY, data.pop(legacy_key))

    body = text[fm.end() :]
    facts_region, body = _take_region(body, "facts")
    journal, body = _take_region(body, "journal")
    notes, body = _take_region(body, "notes")
    transcript, body = _take_region(body, "transcript")

    stray_parts: list[str] = []
    legacy_facts: dict[str, Any] | None = None
    if facts_region is None:
        # Format 1 kept the facts in the front matter. With a facts region, any fact-named keys
        # the owner adds to the front matter are left alone as ordinary extra keys.
        legacy_facts = {k: data.pop(k) for k in FORMAT_1_FACT_KEYS if k in data}
        family_events = legacy_facts.pop("family_events", None) or []
        try:
            facts = DayFacts.model_validate(legacy_facts)
        except ValidationError as exc:
            raise DayFileParseError(f"invalid facts in front matter: {exc}") from exc
        _add_unique(facts.highlights, _clean_list(family_events))
    else:
        try:
            source_format = int(data.get(FORMAT_KEY) or 2)
        except (TypeError, ValueError):
            source_format = 2
        facts, facts_stray = parse_facts_section(facts_region, source_format=source_format)
        if facts_stray:
            stray_parts.append(facts_stray)
    data[FORMAT_KEY] = FORMAT_VERSION
    try:
        meta = FrontMatter.model_validate(data)
    except ValidationError as exc:
        raise DayFileParseError(f"invalid front matter: {exc}") from exc

    captures: list[Capture] = []
    if transcript is not None:
        captures, transcript_stray = _parse_captures(transcript)
        if transcript_stray:
            stray_parts.append(transcript_stray)

    title = ""
    title_match = _TITLE_RE.search(body)
    if title_match:
        title = title_match.group(1)
        body = body[: title_match.start()] + body[title_match.end() :]
    body = _remove_line(body, FACTS_HEADING)
    body = _remove_line(body, NOTES_HEADING)
    body = _remove_line(body, TRANSCRIPT_HEADING)
    if body.strip():
        stray_parts.insert(0, body.strip())

    notes_text = "\n\n".join(p for p in [notes or "", *stray_parts] if p)
    day = DayFile(
        meta=meta,
        title=title,
        facts=facts,
        journal=journal or "",
        notes=notes_text,
        captures=captures,
    )
    if legacy_facts is not None and meta.generated_hash == _hash_generated(
        _format_1_facts(fm_data), day.title, day.journal
    ):
        # An unedited format 1 day stays unedited under the format 2 hash; an edited one keeps
        # its old hash and therefore stays marked as edited.
        day.meta.generated_hash = day.compute_generated_hash()
    return day


# --- Merging --------------------------------------------------------------------------------


def merge_capture(day: DayFile | None, capture: Capture, day_date: dt.date) -> DayFile:
    """Add a capture to a day (creating the day if ``day`` is None). Returns a new DayFile.

    * Idempotent: a capture whose ``id`` is already present is ignored.
    * Captures stay sorted by ``captured_at``; audio and photos are added to the front matter.
    * Never touches title, journal, notes, facts or ``generated_hash``.

    Compute ``day_date`` with :func:`entry_date`.
    """
    result = DayFile.new(day_date) if day is None else day.model_copy(deep=True)
    if result.date != day_date:
        raise ValueError(f"capture for {day_date} cannot merge into {result.date}")
    if capture.id in result.capture_ids():
        return result
    result.captures.append(capture.model_copy(deep=True))
    result.captures.sort(key=lambda c: c.captured_at)
    if capture.audio and capture.audio not in result.meta.audio:
        result.meta.audio.append(capture.audio)
    for photo in capture.photos:
        if photo not in result.meta.photos:
            result.meta.photos.append(photo)
    return result


def _set_provenance(
    day: DayFile,
    prompt_version: str | None,
    models_used: dict[str, str] | None,
    generated_at: dt.datetime | None,
) -> None:
    if prompt_version is not None:
        day.meta.prompt_version = prompt_version
    if models_used is not None:
        day.meta.models_used = dict(models_used)
    day.meta.generated_at = generated_at or dt.datetime.now(dt.UTC)


def apply_generation(
    day: DayFile,
    *,
    facts: DayFacts,
    journal: str,
    title: str | None = None,
    prompt_version: str | None = None,
    models_used: dict[str, str] | None = None,
    generated_at: dt.datetime | None = None,
    generated_source_hash: str | None = None,
    force: bool = False,
) -> DayFile:
    """Replace facts, title and journal with freshly generated content.

    The journal gets the fixed headings (:func:`normalize_journal`). Raises
    :class:`UserEditsDetected` if the owner edited generated content, unless ``force``. Never
    touches notes or captures. Updates provenance and ``generated_hash``.
    """
    if day.is_user_edited() and not force:
        raise UserEditsDetected(day.date)
    result = day.model_copy(deep=True)
    result.facts = facts.model_copy(deep=True)
    result.journal = normalize_journal(journal)
    result.title = (title or "").strip() or result.title
    _set_provenance(result, prompt_version, models_used, generated_at)
    if generated_source_hash is not None:
        result.meta.generated_source_hash = generated_source_hash
    result.meta.generated_hash = result.compute_generated_hash()
    return result


def _add_unique(target: list[str], items: Iterable[str]) -> None:
    seen = {t.casefold() for t in target}
    for item in items:
        if item.casefold() not in seen:
            target.append(item)
            seen.add(item.casefold())


def _add_activities(target: list[Activity], new: Iterable[Activity]) -> None:
    kinds = {a.kind.casefold() for a in target}
    for activity in new:
        if activity.kind.casefold() not in kinds:
            target.append(activity.model_copy(deep=True))
            kinds.add(activity.kind.casefold())


def _add_meals(target: list[Meal], new: Iterable[Meal]) -> None:
    for meal in new:
        existing = next((m for m in target if m.type == meal.type), None)
        if existing is None:
            target.append(meal.model_copy(deep=True))
        else:
            _add_unique(existing.items, meal.items)


def merge_generation_additive(
    day: DayFile,
    *,
    facts: DayFacts,
    journal_sections: dict[str, list[str]] | None = None,
    prompt_version: str | None = None,
    models_used: dict[str, str] | None = None,
    generated_at: dt.datetime | None = None,
    generated_source_hash: str | None = None,
) -> DayFile:
    """Add new information without changing anything that is already there.

    Safe on user-edited days: empty scalar facts are filled, list facts gain new items, meals
    with the same ``type`` gain new items, activities with a new ``kind`` are added, family
    members are matched by name (new ones are added, known ones gain new items the same way),
    and journal bullets are inserted into the requested existing sections. If the day was not
    user-edited, ``generated_hash`` is refreshed; otherwise it is left alone so the day stays
    marked as edited.
    """
    was_edited = day.is_user_edited()
    result = day.model_copy(deep=True)
    current = result.facts
    for name in ("mood", "mood_score", "city", "weather", "remember"):
        if getattr(current, name) is None and getattr(facts, name) is not None:
            setattr(current, name, getattr(facts, name))
    for name in ("people", "places", "highlights", "memories"):
        _add_unique(getattr(current, name), getattr(facts, name))
    _add_meals(current.meals, facts.meals)
    for member in facts.family:
        existing_member = next(
            (f for f in current.family if f.name.casefold() == member.name.casefold()), None
        )
        if existing_member is None:
            current.family.append(member.model_copy(deep=True))
            continue
        for name in ("health", "feelings", "moments"):
            _add_unique(getattr(existing_member, name), getattr(member, name))
        _add_meals(existing_member.meals, member.meals)
    _add_activities(current.activities, facts.activities)
    result.facts = DayFacts.model_validate(current.model_dump())
    if journal_sections is not None:
        result.journal = merge_journal_sections(result.journal, journal_sections)
    _set_provenance(result, prompt_version, models_used, generated_at)
    if generated_source_hash is not None:
        result.meta.generated_source_hash = generated_source_hash
    if not was_edited:
        result.meta.generated_hash = result.compute_generated_hash()
    return result
