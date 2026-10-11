"""The day-file contract: paths, entry dates, and the Markdown format of one day.

Full specification with an example: ``docs/frames-format.md``. Summary of the layout::

    ---
    <YAML front matter: FrontMatter>
    ---

    # <title>

    <!-- lumen:journal:start ... -->         generated journal (DayFile.journal)
    <!-- lumen:journal:end -->

    ## My notes

    <!-- lumen:notes:start ... -->           the owner's own notes (DayFile.notes); never changed
    <!-- lumen:notes:end -->

    ## Transcript

    <!-- lumen:transcript:start ... -->      one block per Capture, oldest first; append-only
    <!-- lumen:capture {json} -->
    ### 21:30 · Log My Day
    ![[2026-10-10-2130.m4a]]

    transcript text
    <!-- lumen:transcript:end -->

Edit protection: ``FrontMatter.generated_hash`` is a hash of the facts, title and journal as the
system last wrote them. If the current content no longer matches, the owner edited it
(:meth:`DayFile.is_user_edited`) and :func:`apply_generation` refuses to replace it; use
:func:`merge_generation_additive` instead. Text found outside the known regions is moved into
the notes region on the next render, so it is never lost.

Files written under the project's earlier names use ``lifelog:`` (LifeLog, 0.1.0) or
``bookshelf:`` (Bookshelf) markers and a ``lifelog_format`` or ``bookshelf_format`` key;
:func:`parse` still reads them and :func:`render` writes the current names.

All storage paths are relative to the Lumen root folder (see
``lumen.frames.storage.base``).
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

FORMAT_VERSION = 1
SYSTEM_DIR = "_system"
AUDIO_EXT = ".m4a"
PHOTO_EXT = ".jpg"

JOURNAL_START = (
    "<!-- lumen:journal:start (written by Lumen; if you edit it, your edits are kept) -->"
)
JOURNAL_END = "<!-- lumen:journal:end -->"
NOTES_START = "<!-- lumen:notes:start (your own notes; Lumen never changes this section) -->"
NOTES_END = "<!-- lumen:notes:end -->"
TRANSCRIPT_START = "<!-- lumen:transcript:start (raw transcripts, added by Lumen) -->"
TRANSCRIPT_END = "<!-- lumen:transcript:end -->"
CAPTURE_MARKER = "lumen:capture"
MARKER_PREFIXES: tuple[str, ...] = ("lumen", "bookshelf", "lifelog")
"""Marker prefixes :func:`parse` accepts; the first is written, the rest are legacy."""
FORMAT_KEY = "lumen_format"
LEGACY_FORMAT_KEYS: tuple[str, ...] = ("bookshelf_format", "lifelog_format")
"""Older names of :data:`FORMAT_KEY`; :func:`parse` reads them, newest first."""
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


class Meal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str
    """breakfast | lunch | dinner | snack | drink (free text is accepted)."""
    items: list[str] = Field(default_factory=list)


class Activity(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: str
    minutes: int | None = None


class DayFacts(BaseModel):
    """Structured facts about a day. This is also the shape the fact-extraction step returns."""

    model_config = ConfigDict(extra="ignore")
    mood: str | None = None
    mood_score: int | None = Field(default=None, ge=1, le=5)
    city: str | None = None
    weather: str | None = None
    people: list[str] = Field(default_factory=list)
    meals: list[Meal] = Field(default_factory=list)
    activities: list[Activity] = Field(default_factory=list)
    family_events: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)

    @field_validator("people", "family_events", "highlights", "meals", "activities", mode="before")
    @classmethod
    def _none_is_empty(cls, value: Any) -> Any:
        return [] if value is None else value


FACT_FIELDS: tuple[str, ...] = tuple(DayFacts.model_fields)


class FrontMatter(DayFacts):
    """YAML front matter. Unknown keys (for example Obsidian ``tags``) are preserved."""

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
    lumen_format: int = FORMAT_VERSION

    @field_validator("audio", "photos", mode="before")
    @classmethod
    def _none_is_empty_list(cls, value: Any) -> Any:
        return [] if value is None else value

    @field_validator("models_used", mode="before")
    @classmethod
    def _none_is_empty_dict(cls, value: Any) -> Any:
        return {} if value is None else value

    def facts(self) -> DayFacts:
        return DayFacts.model_validate(self.model_dump(include=set(FACT_FIELDS)))


FRONT_MATTER_ORDER: tuple[str, ...] = (
    "date",
    *FACT_FIELDS,
    "audio",
    "photos",
    "prompt_version",
    "models_used",
    "generated_at",
    "generated_hash",
    "lumen_format",
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


class DayFile(BaseModel):
    meta: FrontMatter
    title: StrippedStr = ""
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
        payload = {
            "facts": self.meta.facts().model_dump(mode="json"),
            "title": self.title,
            "journal": self.journal,
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


def render(day: DayFile) -> str:
    """Render a :class:`DayFile` to Markdown. ``parse(render(d)) == d`` always holds."""
    front = yaml.safe_dump(
        _front_matter_dict(day.meta),
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=4096,
    )
    transcript = "\n".join(_render_capture(c) for c in day.captures)
    return "".join(
        [
            "---\n",
            front,
            "---\n\n",
            f"# {day.title}\n\n",
            _region(JOURNAL_START, day.journal, JOURNAL_END),
            "\n",
            f"{NOTES_HEADING}\n\n",
            _region(NOTES_START, day.notes, NOTES_END),
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
        meta["text"] = "\n".join(lines[idx:])
        try:
            captures.append(Capture.model_validate(meta))
        except ValidationError as exc:
            raise DayFileParseError(f"invalid capture {meta.get('id')!r}: {exc}") from exc
    return captures, stray.strip()


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
    if data.get("date") is None and fallback_date is not None:
        data["date"] = fallback_date
    for legacy_key in LEGACY_FORMAT_KEYS:
        if legacy_key in data:
            data.setdefault(FORMAT_KEY, data.pop(legacy_key))
    try:
        meta = FrontMatter.model_validate(data)
    except ValidationError as exc:
        raise DayFileParseError(f"invalid front matter: {exc}") from exc

    body = text[fm.end() :]
    journal, body = _take_region(body, "journal")
    notes, body = _take_region(body, "notes")
    transcript, body = _take_region(body, "transcript")

    captures: list[Capture] = []
    stray_parts: list[str] = []
    if transcript is not None:
        captures, transcript_stray = _parse_captures(transcript)
        if transcript_stray:
            stray_parts.append(transcript_stray)

    title = ""
    title_match = _TITLE_RE.search(body)
    if title_match:
        title = title_match.group(1)
        body = body[: title_match.start()] + body[title_match.end() :]
    body = _remove_line(body, NOTES_HEADING)
    body = _remove_line(body, TRANSCRIPT_HEADING)
    if body.strip():
        stray_parts.insert(0, body.strip())

    notes_text = "\n\n".join(p for p in [notes or "", *stray_parts] if p)
    return DayFile(
        meta=meta,
        title=title,
        journal=journal or "",
        notes=notes_text,
        captures=captures,
    )


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
    force: bool = False,
) -> DayFile:
    """Replace facts, title and journal with freshly generated content.

    Raises :class:`UserEditsDetected` if the owner edited generated content, unless ``force``.
    Never touches notes or captures. Updates provenance and ``generated_hash``.
    """
    if day.is_user_edited() and not force:
        raise UserEditsDetected(day.date)
    result = day.model_copy(deep=True)
    for name in FACT_FIELDS:
        setattr(result.meta, name, getattr(facts, name))
    result.journal = journal.strip()
    result.title = (title or "").strip() or result.title
    _set_provenance(result, prompt_version, models_used, generated_at)
    result.meta.generated_hash = result.compute_generated_hash()
    return result


def _add_unique(target: list[str], items: Iterable[str]) -> None:
    seen = {t.casefold() for t in target}
    for item in items:
        if item.casefold() not in seen:
            target.append(item)
            seen.add(item.casefold())


def merge_generation_additive(
    day: DayFile,
    *,
    facts: DayFacts,
    journal_addendum: str | None = None,
    addendum_heading: str | None = None,
    prompt_version: str | None = None,
    models_used: dict[str, str] | None = None,
    generated_at: dt.datetime | None = None,
) -> DayFile:
    """Add new information without changing anything that is already there.

    Safe on user-edited days: empty scalar facts are filled, list facts gain new items, meals
    with the same ``type`` gain new items, activities with a new ``kind`` are added, and
    ``journal_addendum`` is appended (under ``### addendum_heading`` if given). If the day was
    not user-edited, ``generated_hash`` is refreshed; otherwise it is left alone so the day stays
    marked as edited.
    """
    was_edited = day.is_user_edited()
    result = day.model_copy(deep=True)
    meta = result.meta
    for name in ("mood", "mood_score", "city", "weather"):
        if getattr(meta, name) is None and getattr(facts, name) is not None:
            setattr(meta, name, getattr(facts, name))
    _add_unique(meta.people, facts.people)
    _add_unique(meta.family_events, facts.family_events)
    _add_unique(meta.highlights, facts.highlights)
    for meal in facts.meals:
        existing = next((m for m in meta.meals if m.type.casefold() == meal.type.casefold()), None)
        if existing is None:
            meta.meals.append(meal.model_copy(deep=True))
        else:
            _add_unique(existing.items, meal.items)
    kinds = {a.kind.casefold() for a in meta.activities}
    for activity in facts.activities:
        if activity.kind.casefold() not in kinds:
            meta.activities.append(activity.model_copy(deep=True))
            kinds.add(activity.kind.casefold())
    if journal_addendum and journal_addendum.strip():
        block = journal_addendum.strip()
        if addendum_heading:
            block = f"### {addendum_heading.strip()}\n\n{block}"
        result.journal = f"{result.journal}\n\n{block}".strip()
    _set_provenance(result, prompt_version, models_used, generated_at)
    if not was_edited:
        meta.generated_hash = result.compute_generated_hash()
    return result
