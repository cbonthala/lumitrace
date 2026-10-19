"""Format 6 structured day content.

This module deliberately has no dependency on :mod:`lumitrace.frames.dayfile`.  It owns the
typed content returned by the Format 6 prompts, the Markdown representation of that content,
owner-safe three-way merging, and exact timeline patching.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable, Iterable
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

FORMAT_VERSION = 6
EMPTY = "—"
LIST_SEPARATOR = "<br>"

MealStatus = Literal["consumed", "skipped", "not_recorded"]
TimelineSection = Literal[
    "Morning",
    "Afternoon",
    "Evening",
    "Night",
    "Time not stated",
]


def _one_line(value: Any) -> Any:
    return " ".join(value.split()) if isinstance(value, str) else value


def _optional_line(value: Any) -> Any:
    value = _one_line(value)
    return value or None if isinstance(value, str) else value


def _text_list(value: Any) -> Any:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        return value
    return [cleaned for item in value if (cleaned := _one_line(item))]


OneLine = Annotated[str, BeforeValidator(_one_line)]
OptionalLine = Annotated[str | None, BeforeValidator(_optional_line)]
TextList = Annotated[list[str], BeforeValidator(_text_list)]


class _ContentModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class PlaceContext(_ContentModel):
    name: OneLine
    family_members: TextList = Field(default_factory=list)


class PersonContext(_ContentModel):
    name: OneLine
    relationship: OptionalLine = None
    context: OptionalLine = None
    family_members: TextList = Field(default_factory=list)


# Short aliases are convenient for callers and retain the vocabulary used by early Format 6
# drafts.
Place = PlaceContext
Person = PersonContext


class DayContext(_ContentModel):
    weather: OptionalLine = None
    places_visited: list[PlaceContext] = Field(default_factory=list)
    people_met: list[PersonContext] = Field(default_factory=list)
    special_occasions: TextList = Field(default_factory=list)
    media: TextList = Field(default_factory=list)

    @field_validator("places_visited", "people_met", mode="before")
    @classmethod
    def _empty_context_lists(cls, value: Any) -> Any:
        return [] if value is None else value


class Timeline(_ContentModel):
    highlight: OptionalLine = None
    context: DayContext = Field(default_factory=DayContext)
    morning: TextList = Field(default_factory=list)
    afternoon: TextList = Field(default_factory=list)
    evening: TextList = Field(default_factory=list)
    night: TextList = Field(default_factory=list)
    time_not_stated: TextList = Field(default_factory=list)
    remember: OptionalLine = None

    @field_validator("context", mode="before")
    @classmethod
    def _empty_context(cls, value: Any) -> Any:
        return {} if value is None else value


class Meal(_ContentModel):
    status: MealStatus = "not_recorded"
    items: TextList = Field(default_factory=list)

    @model_validator(mode="after")
    def _discard_items_when_not_recorded(self) -> Meal:
        # ``not_recorded`` means there is no meal information. Keeping items would make the
        # model impossible to render without either displaying them or changing the status.
        if self.status == "not_recorded":
            self.items = []
        return self


class FoodTracker(_ContentModel):
    breakfast: Meal = Field(default_factory=Meal)
    lunch: Meal = Field(default_factory=Meal)
    dinner: Meal = Field(default_factory=Meal)
    snacks_drinks: Meal = Field(default_factory=Meal)
    food_response: TextList = Field(default_factory=list)

    @field_validator("breakfast", "lunch", "dinner", "snacks_drinks", mode="before")
    @classmethod
    def _empty_meals(cls, value: Any) -> Any:
        return {} if value is None else value


class ExerciseMovement(_ContentModel):
    activity: OneLine
    minutes: int | None = Field(default=None, ge=0)


class Rating(_ContentModel):
    score: int | None = Field(default=None, ge=1, le=5)
    description: OptionalLine = None


# These names mirror the JSON concepts while Rating remains useful when treating them uniformly.
Energy = Rating
Mood = Rating


class HealthFitness(_ContentModel):
    sleep: TextList = Field(default_factory=list)
    exercise_movement: list[ExerciseMovement] = Field(default_factory=list)
    energy: Rating = Field(default_factory=Rating)
    mood: Rating = Field(default_factory=Rating)
    body_digestion: TextList = Field(default_factory=list)
    symptoms_medication: TextList = Field(default_factory=list)

    @field_validator("exercise_movement", mode="before")
    @classmethod
    def _empty_exercise(cls, value: Any) -> Any:
        return [] if value is None else value

    @field_validator("energy", "mood", mode="before")
    @classmethod
    def _empty_ratings(cls, value: Any) -> Any:
        return {} if value is None else value


class DailyRoutine(_ContentModel):
    work_daycare: TextList = Field(default_factory=list)
    responsibilities_activities: TextList = Field(default_factory=list)
    reading_learning: TextList = Field(default_factory=list)
    screen_media: TextList = Field(default_factory=list)


class InterestsPreferences(_ContentModel):
    enjoyed: TextList = Field(default_factory=list)
    disliked_avoided: TextList = Field(default_factory=list)
    current_interests: TextList = Field(default_factory=list)


class GrowthLearning(_ContentModel):
    learned_practiced: TextList = Field(default_factory=list)
    progress_change: TextList = Field(default_factory=list)
    new_skill_behavior: TextList = Field(default_factory=list)
    words_quotes: TextList = Field(default_factory=list)


# Compatibility names matching the prose headings used by the template.
Food = FoodTracker
HealthAndFitness = HealthFitness
Exercise = ExerciseMovement
DailyRoutineTracker = DailyRoutine
InterestsAndPreferences = InterestsPreferences
GrowthAndLearning = GrowthLearning


class FamilyTracker(_ContentModel):
    name: OneLine
    food: FoodTracker = Field(default_factory=FoodTracker)
    health_fitness: HealthFitness = Field(default_factory=HealthFitness)
    daily_routine: DailyRoutine = Field(default_factory=DailyRoutine)
    interests_preferences: InterestsPreferences = Field(default_factory=InterestsPreferences)
    growth_learning: GrowthLearning = Field(default_factory=GrowthLearning)

    @field_validator(
        "food",
        "health_fitness",
        "daily_routine",
        "interests_preferences",
        "growth_learning",
        mode="before",
    )
    @classmethod
    def _empty_tracker_groups(cls, value: Any) -> Any:
        return {} if value is None else value


class PregnancyBaby(_ContentModel):
    pregnant_person: OptionalLine = None
    gestational_age: OptionalLine = None
    maternal_symptoms: TextList = Field(default_factory=list)
    cravings_aversions: TextList = Field(default_factory=list)
    supplements_medication: TextList = Field(default_factory=list)
    rest_self_care: TextList = Field(default_factory=list)
    baby_movement: TextList = Field(default_factory=list)
    appointment_scan: TextList = Field(default_factory=list)
    heartbeat_growth: TextList = Field(default_factory=list)
    questions_concerns: TextList = Field(default_factory=list)


PregnancyAndBaby = PregnancyBaby
TimelineContext = DayContext


class DayContent(_ContentModel):
    timeline: Timeline = Field(default_factory=Timeline)
    family: list[FamilyTracker] = Field(default_factory=list)
    pregnancy_baby: PregnancyBaby = Field(default_factory=PregnancyBaby)
    tags: TextList = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _accept_prompt_envelope(cls, value: Any) -> Any:
        """Accept either this model's shape or the ``trackers`` envelope from ``fill_day.md``."""
        if not isinstance(value, dict) or not isinstance(value.get("trackers"), dict):
            return value
        data = dict(value)
        trackers = data.pop("trackers")
        data.setdefault("family", trackers.get("family"))
        data.setdefault("pregnancy_baby", trackers.get("pregnancy_baby"))
        data.setdefault("tags", trackers.get("tags"))
        return data

    @field_validator("family", mode="before")
    @classmethod
    def _empty_family(cls, value: Any) -> Any:
        return [] if value is None else value

    @field_validator("timeline", "pregnancy_baby", mode="before")
    @classmethod
    def _empty_top_level_models(cls, value: Any) -> Any:
        return {} if value is None else value

    @field_validator("tags", mode="after")
    @classmethod
    def _normalise_tags(cls, value: list[str]) -> list[str]:
        return [tag.removeprefix("#") for tag in value if tag.removeprefix("#")]

    def is_blank(self) -> bool:
        """True when the model returned no timeline, context, trackers or tags."""
        timeline = self.timeline
        context = timeline.context
        if (
            timeline.highlight
            or timeline.remember
            or timeline.morning
            or timeline.afternoon
            or timeline.evening
            or timeline.night
            or timeline.time_not_stated
            or context.weather
            or context.places_visited
            or context.people_met
            or context.special_occasions
            or context.media
            or self.tags
        ):
            return False
        if self.pregnancy_baby.model_dump(exclude_defaults=True):
            return False
        for member in self.family:
            dumped = member.model_dump(exclude_defaults=True)
            dumped.pop("name", None)
            if dumped:
                return False
        return True

    @classmethod
    def from_legacy(cls, data: dict[str, Any]) -> DayContent:
        return from_legacy_facts(data)


def from_fill_day(data: dict[str, Any]) -> DayContent:
    """Validate a complete response from ``fill_day.md`` (the optional headline is ignored)."""
    if not isinstance(data, dict):
        raise TypeError("fill-day content must be a dict")
    return DayContent.model_validate(data)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _item(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else default


def _legacy_meals(value: Any) -> FoodTracker:
    data: dict[str, Meal] = {}
    aliases = {
        "breakfast": "breakfast",
        "morning": "breakfast",
        "lunch": "lunch",
        "brunch": "lunch",
        "dinner": "dinner",
        "supper": "dinner",
        "snacks": "snacks_drinks",
        "snack": "snacks_drinks",
        "drinks": "snacks_drinks",
        "drink": "snacks_drinks",
    }
    for raw in _as_list(value):
        kind = str(_item(raw, "type", "snacks")).strip().casefold()
        field = aliases.get(kind, "snacks_drinks")
        items = [str(item) for item in _as_list(_item(raw, "items"))]
        previous = data.get(field, Meal())
        combined = [*previous.items, *items]
        data[field] = Meal(status="consumed" if combined else "not_recorded", items=combined)
    return FoodTracker(**data)


def from_legacy_facts(data: dict[str, Any]) -> DayContent:
    """Convert legacy ``DayFacts``-shaped data without importing the legacy model.

    Only mappings are accepted intentionally: callers should pass ``model_dump()`` for a Pydantic
    object.  This keeps Format 6 independent and avoids a circular import.
    """
    if not isinstance(data, dict):
        raise TypeError("legacy facts must be supplied as a dict")

    members: list[FamilyTracker] = []
    for raw in _as_list(data.get("family")):
        if not isinstance(raw, dict):
            continue
        feelings = [str(item) for item in _as_list(raw.get("feelings"))]
        members.append(
            FamilyTracker(
                name=str(raw.get("name") or ""),
                food=_legacy_meals(raw.get("meals")),
                health_fitness=HealthFitness(
                    body_digestion=[str(item) for item in _as_list(raw.get("health"))],
                    mood=Rating(description="; ".join(feelings) or None),
                ),
                growth_learning=GrowthLearning(
                    new_skill_behavior=[str(item) for item in _as_list(raw.get("moments"))]
                ),
            )
        )

    unassigned = _legacy_meals(data.get("meals"))
    if unassigned != FoodTracker():
        members.insert(0, FamilyTracker(name="Everyone", food=unassigned))

    activities = []
    for raw in _as_list(data.get("activities")):
        activity = _item(raw, "kind")
        if activity:
            minutes = _item(raw, "minutes")
            suffix = f" ({minutes} min)" if minutes is not None else ""
            activities.append(f"{activity}{suffix}")
    activities.extend(str(item) for item in _as_list(data.get("memories")))

    highlights = [str(item) for item in _as_list(data.get("highlights")) if str(item).strip()]
    return DayContent(
        timeline=Timeline(
            highlight=highlights[0] if highlights else None,
            context=DayContext(
                weather=data.get("weather"),
                places_visited=[
                    PlaceContext(name=str(item)) for item in _as_list(data.get("places"))
                ],
                people_met=[PersonContext(name=str(item)) for item in _as_list(data.get("people"))],
            ),
            time_not_stated=[*highlights[1:], *activities],
            remember=data.get("remember"),
        ),
        family=members,
    )


from_legacy_day_facts = from_legacy_facts


def from_legacy_day(data: dict[str, Any], journal: str) -> DayContent:
    """Convert Format 5 facts and journal sections to Format 6 content.

    The conversion is deliberately conservative. Unknown journal headings and text before the
    first heading become ``time_not_stated`` rather than receiving an invented time of day.
    A later full generation can replace this compatibility projection from the original sources.
    """
    content = from_legacy_facts(data)
    current: str | None = None
    sections: dict[str, list[str]] = {
        "morning": [],
        "afternoon": [],
        "evening": [],
        "night": [],
        "time_not_stated": [],
    }
    aliases = {
        "morning": "morning",
        "afternoon": "afternoon",
        "evening": "evening",
        "night": "night",
        "summary": "time_not_stated",
        "thoughts": "time_not_stated",
        "time not stated": "time_not_stated",
    }
    for raw in journal.splitlines():
        line = raw.strip()
        heading = re.match(r"^#{1,6}\s+(.+?)\s*#*$", line)
        if heading:
            current = aliases.get(heading.group(1).strip().rstrip(":").casefold())
            continue
        if not line:
            continue
        value = line.removeprefix("-").strip()
        if value:
            sections[current or "time_not_stated"].append(value)
    for name, values in sections.items():
        existing = getattr(content.timeline, name)
        setattr(content.timeline, name, [*existing, *values])
    return DayContent.model_validate(content.model_dump())


def to_legacy_facts(content: DayContent) -> dict[str, Any]:
    """Best-effort Format 5 projection for compatibility callers and old query surfaces."""
    value = DayContent.model_validate(content.model_dump())
    family: list[dict[str, Any]] = []
    activities: list[dict[str, Any]] = []
    for member in value.family:
        meals = []
        for meal_type, meal in (
            ("breakfast", member.food.breakfast),
            ("lunch", member.food.lunch),
            ("dinner", member.food.dinner),
            ("snacks", member.food.snacks_drinks),
        ):
            if meal.status == "consumed" and meal.items:
                meals.append({"type": meal_type, "items": list(meal.items)})
            elif meal.status == "skipped":
                meals.append({"type": meal_type, "items": ["Skipped"]})
        health = [
            *member.health_fitness.sleep,
            *(
                f"{item.activity} ({item.minutes} min)"
                if item.minutes is not None
                else item.activity
                for item in member.health_fitness.exercise_movement
            ),
            *member.health_fitness.body_digestion,
            *member.health_fitness.symptoms_medication,
        ]
        feelings = []
        if member.health_fitness.energy.description:
            feelings.append(f"Energy: {member.health_fitness.energy.description}")
        if member.health_fitness.mood.description:
            feelings.append(member.health_fitness.mood.description)
        moments = [
            *member.growth_learning.learned_practiced,
            *member.growth_learning.progress_change,
            *member.growth_learning.new_skill_behavior,
            *member.growth_learning.words_quotes,
        ]
        family.append(
            {
                "name": member.name,
                "meals": meals,
                "health": health,
                "feelings": feelings,
                "moments": moments,
            }
        )
        for item in member.daily_routine.responsibilities_activities:
            activities.append({"kind": f"{item} ({member.name})", "minutes": None})

    context = value.timeline.context
    return {
        "weather": context.weather,
        "highlights": [value.timeline.highlight] if value.timeline.highlight else [],
        "remember": value.timeline.remember,
        "places": [
            (
                f"{place.name} ({', '.join(place.family_members)})"
                if place.family_members
                else place.name
            )
            for place in context.places_visited
        ],
        "people": [
            " - ".join(
                part
                for part in (
                    person.name,
                    person.relationship,
                    person.context,
                )
                if part
            )
            + (f" ({', '.join(person.family_members)})" if person.family_members else "")
            for person in context.people_met
        ],
        "memories": list(context.special_occasions),
        "activities": activities,
        "family": family,
    }


# --- Markdown rendering --------------------------------------------------------------------


def _escape_text(value: str) -> str:
    """Escape raw HTML and the em dash reserved for an empty rendered value."""
    return html.escape(value, quote=False).replace(EMPTY, "&#8212;")


def _unescape_text(value: str) -> str:
    return html.unescape(value)


def _escape_cell(value: str) -> str:
    return _escape_text(value).replace("\\", "\\\\").replace("|", "\\|")


def _render_list(items: Iterable[str]) -> str:
    values = [_escape_cell(item) for item in items]
    return LIST_SEPARATOR.join(values) if values else EMPTY


def _render_scalar(value: str | None) -> str:
    return _escape_cell(value) if value else EMPTY


def _render_meal(meal: Meal) -> str:
    if meal.status == "not_recorded":
        return EMPTY
    if meal.status == "skipped":
        return LIST_SEPARATOR.join(["Skipped", *(_escape_cell(item) for item in meal.items)])
    if not meal.items:
        return "Consumed"
    rendered = [_escape_cell(item) for item in meal.items]
    if meal.items[0] in {"Skipped", "Consumed"}:
        rendered.insert(0, "Consumed")
    return LIST_SEPARATOR.join(rendered)


def _render_rating(value: Rating) -> str:
    if value.score is None:
        rendered = _render_scalar(value.description)
        if rendered != EMPTY and _RATING_RE.fullmatch(rendered):
            rendered = rendered.replace("/", "&#47;", 1)
        return rendered
    prefix = f"{value.score}/5"
    return f"{prefix} · {_escape_cell(value.description)}" if value.description else prefix


def _render_exercise(items: list[ExerciseMovement]) -> str:
    values: list[str] = []
    for item in items:
        if item.minutes is not None:
            values.append(_escape_cell(f"{item.activity} ({item.minutes} min)"))
            continue
        rendered = _escape_cell(item.activity)
        if _MINUTES_RE.fullmatch(rendered):
            suffix_start = rendered.rfind("(")
            rendered = rendered[:suffix_start] + "&#40;" + rendered[suffix_start + 1 :]
        values.append(rendered)
    return LIST_SEPARATOR.join(values) if values else EMPTY


def _table(headers: list[str], rows: Iterable[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def _context_place(place: PlaceContext) -> str:
    name = _escape_text(place.name).replace("(", "&#40;").replace(")", "&#41;")
    if not place.family_members:
        return name
    members = ", ".join(
        _escape_text(member).replace(",", "&#44;") for member in place.family_members
    )
    return f"{name} (Family: {members})"


def _context_person(person: PersonContext) -> str:
    parts = [_escape_text(person.name)]
    if person.relationship:
        parts.append(f"relationship: {_escape_text(person.relationship)}")
    if person.context:
        parts.append(f"context: {_escape_text(person.context)}")
    if person.family_members:
        members = ", ".join(
            _escape_text(member).replace(",", "&#44;") for member in person.family_members
        )
        parts.append(f"family: {members}")
    return " — ".join(parts)


def _timeline_bullets(items: list[str]) -> list[str]:
    return [f"- {_escape_text(item)}" for item in items] or [f"- {EMPTY}"]


def render(content: DayContent) -> str:
    """Render the canonical Format 6 content region."""
    value = DayContent.model_validate(content.model_dump())
    timeline = value.timeline
    lines = [
        "## Day timeline",
        "",
        "### Highlight",
        "",
        f"- {_escape_text(timeline.highlight) if timeline.highlight else EMPTY}",
        "",
        "### Day context",
        "",
        "- **Weather:** "
        + (_escape_text(timeline.context.weather) if timeline.context.weather else EMPTY),
        "- **Places visited:** "
        + (LIST_SEPARATOR.join(map(_context_place, timeline.context.places_visited)) or EMPTY),
        "- **People we met:** "
        + (LIST_SEPARATOR.join(map(_context_person, timeline.context.people_met)) or EMPTY),
        "- **Special occasion:** "
        + (
            LIST_SEPARATOR.join(_escape_text(item) for item in timeline.context.special_occasions)
            or EMPTY
        ),
        "- **Photos / videos:** "
        + (LIST_SEPARATOR.join(_escape_text(item) for item in timeline.context.media) or EMPTY),
    ]
    for heading, items in (
        ("Morning", timeline.morning),
        ("Afternoon", timeline.afternoon),
        ("Evening", timeline.evening),
        ("Night", timeline.night),
    ):
        lines.extend(["", f"### {heading}", "", *_timeline_bullets(items)])
    if timeline.time_not_stated:
        lines.extend(["", "### Time not stated", "", *_timeline_bullets(timeline.time_not_stated)])
    lines.extend(
        [
            "",
            "- **Remember:** " + (_escape_text(timeline.remember) if timeline.remember else EMPTY),
            "",
            "## Family trackers",
            "",
        ]
    )

    lines.extend(
        [
            "### Food",
            "",
            _table(
                [
                    "Person",
                    "Breakfast",
                    "Lunch",
                    "Dinner",
                    "Snacks / drinks",
                    "Food response",
                ],
                (
                    [
                        _escape_cell(member.name),
                        _render_meal(member.food.breakfast),
                        _render_meal(member.food.lunch),
                        _render_meal(member.food.dinner),
                        _render_meal(member.food.snacks_drinks),
                        _render_list(member.food.food_response),
                    ]
                    for member in value.family
                ),
            ),
            "",
            "### Health and fitness",
            "",
            _table(
                [
                    "Person",
                    "Sleep",
                    "Exercise / movement",
                    "Energy",
                    "Mood",
                    "Body / digestion",
                    "Symptoms / medication",
                ],
                (
                    [
                        _escape_cell(member.name),
                        _render_list(member.health_fitness.sleep),
                        _render_exercise(member.health_fitness.exercise_movement),
                        _render_rating(member.health_fitness.energy),
                        _render_rating(member.health_fitness.mood),
                        _render_list(member.health_fitness.body_digestion),
                        _render_list(member.health_fitness.symptoms_medication),
                    ]
                    for member in value.family
                ),
            ),
            "",
            "### Pregnancy and baby",
            "",
        ]
    )
    pregnant_label = (
        f"{value.pregnancy_baby.pregnant_person}’s symptoms"
        if value.pregnancy_baby.pregnant_person
        else "Maternal symptoms"
    )
    pregnancy = value.pregnancy_baby
    lines.extend(
        [
            _table(
                ["Tracker", "Details"],
                [
                    ["Gestational age", _render_scalar(pregnancy.gestational_age)],
                    [_escape_cell(pregnant_label), _render_list(pregnancy.maternal_symptoms)],
                    ["Cravings / aversions", _render_list(pregnancy.cravings_aversions)],
                    [
                        "Supplements / medication",
                        _render_list(pregnancy.supplements_medication),
                    ],
                    ["Rest / self-care", _render_list(pregnancy.rest_self_care)],
                    ["Baby movement", _render_list(pregnancy.baby_movement)],
                    ["Appointment / scan", _render_list(pregnancy.appointment_scan)],
                    ["Heartbeat / growth", _render_list(pregnancy.heartbeat_growth)],
                    ["Questions / concerns", _render_list(pregnancy.questions_concerns)],
                ],
            ),
            "",
            "### Daily routine",
            "",
            _table(
                [
                    "Person",
                    "Work / daycare",
                    "Responsibilities / activities",
                    "Reading / learning",
                    "Screen / media",
                ],
                (
                    [
                        _escape_cell(member.name),
                        _render_list(member.daily_routine.work_daycare),
                        _render_list(member.daily_routine.responsibilities_activities),
                        _render_list(member.daily_routine.reading_learning),
                        _render_list(member.daily_routine.screen_media),
                    ]
                    for member in value.family
                ),
            ),
            "",
            "### Interests and preferences",
            "",
            _table(
                ["Person", "Enjoyed", "Disliked / avoided", "Current interests"],
                (
                    [
                        _escape_cell(member.name),
                        _render_list(member.interests_preferences.enjoyed),
                        _render_list(member.interests_preferences.disliked_avoided),
                        _render_list(member.interests_preferences.current_interests),
                    ]
                    for member in value.family
                ),
            ),
            "",
            "### Growth and learning",
            "",
            _table(
                [
                    "Person",
                    "Learned / practiced",
                    "Progress or change",
                    "New skill / behavior",
                    "Words / quotes",
                ],
                (
                    [
                        _escape_cell(member.name),
                        _render_list(member.growth_learning.learned_practiced),
                        _render_list(member.growth_learning.progress_change),
                        _render_list(member.growth_learning.new_skill_behavior),
                        _render_list(member.growth_learning.words_quotes),
                    ]
                    for member in value.family
                ),
            ),
            "",
            "## Tags",
            "",
            (
                " ".join(f"#{_escape_text(tag).replace(' ', '&#32;')}" for tag in value.tags)
                if value.tags
                else EMPTY
            ),
        ]
    )
    return "\n".join(lines) + "\n"


render_day_content = render


# --- Markdown parsing ----------------------------------------------------------------------


_HEADING_RE = re.compile(r"^(#{2,3}) (.+)$", re.MULTILINE)
_LABEL_RE = re.compile(r"^- \*\*(.+?):\*\* (.*)$")
_MINUTES_RE = re.compile(r"^(.*) \((\d+) min\)$")
_RATING_RE = re.compile(r"^([1-5])/5(?: · (.*))?$")


def _heading_blocks(markdown: str, level: int) -> dict[str, str]:
    matches = [match for match in _HEADING_RE.finditer(markdown) if len(match.group(1)) == level]
    blocks: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        blocks[match.group(2)] = markdown[match.end() : end].strip()
    return blocks


def _bullet_values(block: str) -> list[str]:
    values = []
    for line in block.splitlines():
        if line.startswith("- ") and not line.startswith("- **Remember:**"):
            value = line[2:]
            if value != EMPTY:
                values.append(_unescape_text(value))
    return values


def _label_values(block: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in block.splitlines():
        if match := _LABEL_RE.match(line):
            values[match.group(1)] = match.group(2)
    return values


def _split_context(value: str) -> list[str]:
    return [] if not value or value == EMPTY else value.split(LIST_SEPARATOR)


def _parse_place(value: str) -> PlaceContext:
    marker = " (Family: "
    if value.endswith(")") and marker in value:
        name, members = value.rsplit(marker, 1)
        return PlaceContext(
            name=_unescape_text(name),
            family_members=[_unescape_text(part.strip()) for part in members[:-1].split(",")],
        )
    return PlaceContext(name=_unescape_text(value))


def _parse_person(value: str) -> PersonContext:
    parts = value.split(" — ")
    data: dict[str, Any] = {"name": _unescape_text(parts[0])}
    for part in parts[1:]:
        if part.startswith("relationship: "):
            data["relationship"] = _unescape_text(part.removeprefix("relationship: "))
        elif part.startswith("context: "):
            data["context"] = _unescape_text(part.removeprefix("context: "))
        elif part.startswith("family: "):
            data["family_members"] = [
                _unescape_text(item.strip()) for item in part.removeprefix("family: ").split(",")
            ]
    return PersonContext.model_validate(data)


def _split_table_row(line: str) -> list[str]:
    raw = line.strip()
    if not raw.startswith("|") or not raw.endswith("|"):
        raise ValueError(f"invalid table row: {line!r}")
    cells: list[str] = []
    cell: list[str] = []
    index = 1
    while index < len(raw) - 1:
        char = raw[index]
        if char == "\\" and index + 1 < len(raw) - 1 and raw[index + 1] in {"\\", "|"}:
            cell.append(raw[index + 1])
            index += 2
            continue
        if char == "|":
            cells.append("".join(cell).strip())
            cell = []
        else:
            cell.append(char)
        index += 1
    cells.append("".join(cell).strip())
    return cells


def _parse_table(block: str) -> list[list[str]]:
    rows = [_split_table_row(line) for line in block.splitlines() if line.strip().startswith("|")]
    return rows[2:] if len(rows) >= 2 else []


def _parse_list(value: str) -> list[str]:
    return [] if value == EMPTY else [_unescape_text(item) for item in value.split(LIST_SEPARATOR)]


def _parse_scalar(value: str) -> str | None:
    return None if value == EMPTY else _unescape_text(value)


def _parse_meal(value: str) -> Meal:
    if value == EMPTY:
        return Meal()
    values = value.split(LIST_SEPARATOR)
    if values[0] == "Skipped":
        return Meal(status="skipped", items=[_unescape_text(item) for item in values[1:]])
    if values[0] == "Consumed":
        return Meal(status="consumed", items=[_unescape_text(item) for item in values[1:]])
    return Meal(status="consumed", items=[_unescape_text(item) for item in values])


def _parse_rating(value: str) -> Rating:
    if value == EMPTY:
        return Rating()
    match = _RATING_RE.match(value)
    if match:
        return Rating(
            score=int(match.group(1)),
            description=_unescape_text(match.group(2)) if match.group(2) else None,
        )
    return Rating(description=_unescape_text(value))


def _parse_exercise(value: str) -> list[ExerciseMovement]:
    result = []
    items = [] if value == EMPTY else value.split(LIST_SEPARATOR)
    for item in items:
        match = _MINUTES_RE.match(item)
        result.append(
            ExerciseMovement(
                activity=_unescape_text(match.group(1) if match else item),
                minutes=int(match.group(2)) if match else None,
            )
        )
    return result


def _table_blocks(markdown: str) -> dict[str, str]:
    top = _heading_blocks(markdown, 2)
    return _heading_blocks(top.get("Family trackers", ""), 3)


def _named_rows(block: str, table: str, width: int) -> list[tuple[str, list[str]]]:
    result: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    for row in _parse_table(block):
        if len(row) != width:
            raise ValueError(f"{table} row has {len(row)} cells; expected {width}")
        name = _unescape_text(row[0])
        key = name.casefold()
        if not key:
            raise ValueError(f"{table} row has an empty person")
        if key in seen:
            raise ValueError(f"{table} has duplicate person {name!r}")
        seen.add(key)
        result.append((name, row))
    return result


def parse(markdown: str) -> DayContent:
    """Parse Markdown emitted by :func:`render`."""
    text = markdown.replace("\r\n", "\n").strip()
    top = _heading_blocks(text, 2)
    if "Day timeline" not in top or "Family trackers" not in top or "Tags" not in top:
        raise ValueError("not Format 6 day content")

    timeline_blocks = _heading_blocks(top["Day timeline"], 3)
    context_values = _label_values(timeline_blocks.get("Day context", ""))
    highlight = _bullet_values(timeline_blocks.get("Highlight", ""))
    remember = None
    for block in timeline_blocks.values():
        value = _label_values(block).get("Remember")
        if value is not None:
            remember = _parse_scalar(value)
            break
    timeline = Timeline(
        highlight=highlight[0] if highlight else None,
        context=DayContext(
            weather=_parse_scalar(context_values.get("Weather", EMPTY)),
            places_visited=[
                _parse_place(item)
                for item in _split_context(context_values.get("Places visited", EMPTY))
            ],
            people_met=[
                _parse_person(item)
                for item in _split_context(context_values.get("People we met", EMPTY))
            ],
            special_occasions=[
                _unescape_text(item)
                for item in _split_context(context_values.get("Special occasion", EMPTY))
            ],
            media=[
                _unescape_text(item)
                for item in _split_context(context_values.get("Photos / videos", EMPTY))
            ],
        ),
        morning=_bullet_values(timeline_blocks.get("Morning", "")),
        afternoon=_bullet_values(timeline_blocks.get("Afternoon", "")),
        evening=_bullet_values(timeline_blocks.get("Evening", "")),
        night=_bullet_values(timeline_blocks.get("Night", "")),
        time_not_stated=_bullet_values(timeline_blocks.get("Time not stated", "")),
        remember=remember,
    )

    tables = _table_blocks(text)
    family: list[FamilyTracker] = []
    by_name: dict[str, FamilyTracker] = {}

    def member_named(name: str) -> FamilyTracker:
        key = name.casefold()
        member = by_name.get(key)
        if member is None:
            member = FamilyTracker(name=name)
            by_name[key] = member
            family.append(member)
        return member

    food_rows = _named_rows(tables.get("Food", ""), "Food", 6)
    for name, row in food_rows:
        member = member_named(name)
        member.food = FoodTracker(
            breakfast=_parse_meal(row[1]),
            lunch=_parse_meal(row[2]),
            dinner=_parse_meal(row[3]),
            snacks_drinks=_parse_meal(row[4]),
            food_response=_parse_list(row[5]),
        )

    health_rows = _named_rows(tables.get("Health and fitness", ""), "Health and fitness", 7)
    for name, health in health_rows:
        member = member_named(name)
        member.health_fitness = HealthFitness(
            sleep=_parse_list(health[1]),
            exercise_movement=_parse_exercise(health[2]),
            energy=_parse_rating(health[3]),
            mood=_parse_rating(health[4]),
            body_digestion=_parse_list(health[5]),
            symptoms_medication=_parse_list(health[6]),
        )

    routine_rows = _named_rows(tables.get("Daily routine", ""), "Daily routine", 5)
    for name, routine in routine_rows:
        member = member_named(name)
        member.daily_routine = DailyRoutine(
            work_daycare=_parse_list(routine[1]),
            responsibilities_activities=_parse_list(routine[2]),
            reading_learning=_parse_list(routine[3]),
            screen_media=_parse_list(routine[4]),
        )

    interest_rows = _named_rows(
        tables.get("Interests and preferences", ""), "Interests and preferences", 4
    )
    for name, interests in interest_rows:
        member = member_named(name)
        member.interests_preferences = InterestsPreferences(
            enjoyed=_parse_list(interests[1]),
            disliked_avoided=_parse_list(interests[2]),
            current_interests=_parse_list(interests[3]),
        )

    growth_rows = _named_rows(tables.get("Growth and learning", ""), "Growth and learning", 5)
    for name, growth in growth_rows:
        member = member_named(name)
        member.growth_learning = GrowthLearning(
            learned_practiced=_parse_list(growth[1]),
            progress_change=_parse_list(growth[2]),
            new_skill_behavior=_parse_list(growth[3]),
            words_quotes=_parse_list(growth[4]),
        )

    pregnancy_rows = _parse_table(tables.get("Pregnancy and baby", ""))
    pregnancy_values: dict[str, str] = {}
    pregnant_person = None
    for row in pregnancy_rows:
        if len(row) != 2:
            raise ValueError(f"Pregnancy and baby row has {len(row)} cells; expected 2")
        label = _unescape_text(row[0])
        if label.endswith("’s symptoms"):
            pregnant_person = label.removesuffix("’s symptoms")
            label = "Maternal symptoms"
        pregnancy_values[label] = row[1]
    pregnancy = PregnancyBaby(
        pregnant_person=pregnant_person,
        gestational_age=_parse_scalar(pregnancy_values.get("Gestational age", EMPTY)),
        maternal_symptoms=_parse_list(pregnancy_values.get("Maternal symptoms", EMPTY)),
        cravings_aversions=_parse_list(pregnancy_values.get("Cravings / aversions", EMPTY)),
        supplements_medication=_parse_list(pregnancy_values.get("Supplements / medication", EMPTY)),
        rest_self_care=_parse_list(pregnancy_values.get("Rest / self-care", EMPTY)),
        baby_movement=_parse_list(pregnancy_values.get("Baby movement", EMPTY)),
        appointment_scan=_parse_list(pregnancy_values.get("Appointment / scan", EMPTY)),
        heartbeat_growth=_parse_list(pregnancy_values.get("Heartbeat / growth", EMPTY)),
        questions_concerns=_parse_list(pregnancy_values.get("Questions / concerns", EMPTY)),
    )

    raw_tags = top["Tags"].strip()
    tags = (
        []
        if raw_tags == EMPTY
        else [_unescape_text(part.removeprefix("#")) for part in raw_tags.split()]
    )
    return DayContent(timeline=timeline, family=family, pregnancy_baby=pregnancy, tags=tags)


parse_day_content = parse


# --- Three-way merge -----------------------------------------------------------------------


_FACT_PAREN_RE = re.compile(r"\s*\([^)]*\)")
_FACT_UNCERTAIN_RE = re.compile(r"\s*\[uncertain:[^\]]*\]", re.IGNORECASE)


def _text_key(value: str) -> str:
    cleaned = _FACT_UNCERTAIN_RE.sub("", value)
    cleaned = _FACT_PAREN_RE.sub("", cleaned)
    return " ".join(cleaned.casefold().split())


def _merge_list[T](
    base: list[T],
    current: list[T],
    incoming: list[T],
    key: Callable[[T], str],
    merge: Callable[[T | None, T, T | None], T] | None = None,
) -> list[T]:
    before = {key(item): item for item in base}
    local = {key(item): item for item in current}
    new = {key(item): item for item in incoming}
    removed = set(before) - set(local)
    result: list[T] = []
    handled: set[str] = set()
    for item in incoming:
        item_key = key(item)
        if not item_key or item_key in handled or item_key in removed:
            continue
        handled.add(item_key)
        local_item = local.get(item_key)
        result.append(
            item
            if merge is None or local_item is None
            else merge(before.get(item_key), local_item, item)
        )
    for item in current:
        item_key = key(item)
        if not item_key or item_key in handled:
            continue
        before_item = before.get(item_key)
        if before_item is None or item != before_item:
            result.append(item if merge is None else merge(before_item, item, new.get(item_key)))
    return result


def _merge_text(base: list[str], current: list[str], incoming: list[str]) -> list[str]:
    def keyed(items: list[str]) -> dict[str, str]:
        chosen: dict[str, str] = {}
        for item in items:
            key = _text_key(item)
            if key and (key not in chosen or len(item) > len(chosen[key])):
                chosen[key] = item
        return chosen

    before = keyed(base)
    local = keyed(current)
    new = keyed(incoming)
    removed = set(before) - set(local)
    result: list[str] = []
    for key, item in new.items():
        if key in removed:
            continue
        local_item = local.get(key)
        before_item = before.get(key)
        # A same-fact wording change is still an owner edit. Without this branch an incoming
        # parenthetical gloss would silently replace an owner's corrected wording.
        if local_item is not None and (before_item is None or local_item != before_item):
            result.append(local_item)
        else:
            result.append(item)
    result.extend(item for key, item in local.items() if key not in before and key not in new)
    return result


def _scalar[T](base: T, current: T, incoming: T) -> T:
    return incoming if current == base else current


def _merge_rating(base: Rating, current: Rating, incoming: Rating) -> Rating:
    return Rating(
        score=_scalar(base.score, current.score, incoming.score),
        description=_scalar(base.description, current.description, incoming.description),
    )


def _merge_meal(base: Meal, current: Meal, incoming: Meal) -> Meal:
    return Meal(
        status=_scalar(base.status, current.status, incoming.status),
        items=_merge_text(base.items, current.items, incoming.items),
    )


def _merge_place(
    base: PlaceContext | None, current: PlaceContext, incoming: PlaceContext | None
) -> PlaceContext:
    before = base or PlaceContext(name=current.name)
    new = incoming or PlaceContext(name=current.name)
    return PlaceContext(
        name=_scalar(before.name, current.name, new.name),
        family_members=_merge_text(
            before.family_members, current.family_members, new.family_members
        ),
    )


def _merge_person(
    base: PersonContext | None, current: PersonContext, incoming: PersonContext | None
) -> PersonContext:
    before = base or PersonContext(name=current.name)
    new = incoming or PersonContext(name=current.name)
    return PersonContext(
        name=_scalar(before.name, current.name, new.name),
        relationship=_scalar(before.relationship, current.relationship, new.relationship),
        context=_scalar(before.context, current.context, new.context),
        family_members=_merge_text(
            before.family_members, current.family_members, new.family_members
        ),
    )


def _merge_context(base: DayContext, current: DayContext, incoming: DayContext) -> DayContext:
    return DayContext(
        weather=_scalar(base.weather, current.weather, incoming.weather),
        places_visited=_merge_list(
            base.places_visited,
            current.places_visited,
            incoming.places_visited,
            lambda item: item.name.casefold(),
            _merge_place,
        ),
        people_met=_merge_list(
            base.people_met,
            current.people_met,
            incoming.people_met,
            lambda item: item.name.casefold(),
            _merge_person,
        ),
        special_occasions=_merge_text(
            base.special_occasions,
            current.special_occasions,
            incoming.special_occasions,
        ),
        media=_merge_text(base.media, current.media, incoming.media),
    )


def _merge_exercise(
    base: ExerciseMovement | None,
    current: ExerciseMovement,
    incoming: ExerciseMovement | None,
) -> ExerciseMovement:
    before = base or ExerciseMovement(activity=current.activity)
    new = incoming or ExerciseMovement(activity=current.activity)
    return ExerciseMovement(
        activity=_scalar(before.activity, current.activity, new.activity),
        minutes=_scalar(before.minutes, current.minutes, new.minutes),
    )


def _merge_food(base: FoodTracker, current: FoodTracker, incoming: FoodTracker) -> FoodTracker:
    return FoodTracker(
        breakfast=_merge_meal(base.breakfast, current.breakfast, incoming.breakfast),
        lunch=_merge_meal(base.lunch, current.lunch, incoming.lunch),
        dinner=_merge_meal(base.dinner, current.dinner, incoming.dinner),
        snacks_drinks=_merge_meal(
            base.snacks_drinks, current.snacks_drinks, incoming.snacks_drinks
        ),
        food_response=_merge_text(
            base.food_response, current.food_response, incoming.food_response
        ),
    )


def _merge_health(
    base: HealthFitness, current: HealthFitness, incoming: HealthFitness
) -> HealthFitness:
    return HealthFitness(
        sleep=_merge_text(base.sleep, current.sleep, incoming.sleep),
        exercise_movement=_merge_list(
            base.exercise_movement,
            current.exercise_movement,
            incoming.exercise_movement,
            lambda item: item.activity.casefold(),
            _merge_exercise,
        ),
        energy=_merge_rating(base.energy, current.energy, incoming.energy),
        mood=_merge_rating(base.mood, current.mood, incoming.mood),
        body_digestion=_merge_text(
            base.body_digestion, current.body_digestion, incoming.body_digestion
        ),
        symptoms_medication=_merge_text(
            base.symptoms_medication,
            current.symptoms_medication,
            incoming.symptoms_medication,
        ),
    )


def _merge_routine(
    base: DailyRoutine, current: DailyRoutine, incoming: DailyRoutine
) -> DailyRoutine:
    return DailyRoutine(
        work_daycare=_merge_text(base.work_daycare, current.work_daycare, incoming.work_daycare),
        responsibilities_activities=_merge_text(
            base.responsibilities_activities,
            current.responsibilities_activities,
            incoming.responsibilities_activities,
        ),
        reading_learning=_merge_text(
            base.reading_learning, current.reading_learning, incoming.reading_learning
        ),
        screen_media=_merge_text(base.screen_media, current.screen_media, incoming.screen_media),
    )


def _merge_interests(
    base: InterestsPreferences,
    current: InterestsPreferences,
    incoming: InterestsPreferences,
) -> InterestsPreferences:
    return InterestsPreferences(
        enjoyed=_merge_text(base.enjoyed, current.enjoyed, incoming.enjoyed),
        disliked_avoided=_merge_text(
            base.disliked_avoided, current.disliked_avoided, incoming.disliked_avoided
        ),
        current_interests=_merge_text(
            base.current_interests, current.current_interests, incoming.current_interests
        ),
    )


def _merge_growth(
    base: GrowthLearning, current: GrowthLearning, incoming: GrowthLearning
) -> GrowthLearning:
    return GrowthLearning(
        learned_practiced=_merge_text(
            base.learned_practiced, current.learned_practiced, incoming.learned_practiced
        ),
        progress_change=_merge_text(
            base.progress_change, current.progress_change, incoming.progress_change
        ),
        new_skill_behavior=_merge_text(
            base.new_skill_behavior, current.new_skill_behavior, incoming.new_skill_behavior
        ),
        words_quotes=_merge_text(base.words_quotes, current.words_quotes, incoming.words_quotes),
    )


def _merge_member(
    base: FamilyTracker | None,
    current: FamilyTracker,
    incoming: FamilyTracker | None,
) -> FamilyTracker:
    before = base or FamilyTracker(name=current.name)
    new = incoming or FamilyTracker(name=current.name)
    return FamilyTracker(
        name=_scalar(before.name, current.name, new.name),
        food=_merge_food(before.food, current.food, new.food),
        health_fitness=_merge_health(
            before.health_fitness, current.health_fitness, new.health_fitness
        ),
        daily_routine=_merge_routine(
            before.daily_routine, current.daily_routine, new.daily_routine
        ),
        interests_preferences=_merge_interests(
            before.interests_preferences,
            current.interests_preferences,
            new.interests_preferences,
        ),
        growth_learning=_merge_growth(
            before.growth_learning, current.growth_learning, new.growth_learning
        ),
    )


def _merge_pregnancy(
    base: PregnancyBaby, current: PregnancyBaby, incoming: PregnancyBaby
) -> PregnancyBaby:
    data: dict[str, Any] = {
        name: _scalar(getattr(base, name), getattr(current, name), getattr(incoming, name))
        for name in ("pregnant_person", "gestational_age")
    }
    for name in (
        "maternal_symptoms",
        "cravings_aversions",
        "supplements_medication",
        "rest_self_care",
        "baby_movement",
        "appointment_scan",
        "heartbeat_growth",
        "questions_concerns",
    ):
        data[name] = _merge_text(
            getattr(base, name), getattr(current, name), getattr(incoming, name)
        )
    return PregnancyBaby.model_validate(data)


def merge_three_way(base: DayContent, current: DayContent, incoming: DayContent) -> DayContent:
    """Merge a new complete model response while preserving owner edits."""
    timeline = Timeline(
        highlight=_scalar(
            base.timeline.highlight, current.timeline.highlight, incoming.timeline.highlight
        ),
        context=_merge_context(
            base.timeline.context, current.timeline.context, incoming.timeline.context
        ),
        morning=_merge_text(
            base.timeline.morning, current.timeline.morning, incoming.timeline.morning
        ),
        afternoon=_merge_text(
            base.timeline.afternoon, current.timeline.afternoon, incoming.timeline.afternoon
        ),
        evening=_merge_text(
            base.timeline.evening, current.timeline.evening, incoming.timeline.evening
        ),
        night=_merge_text(base.timeline.night, current.timeline.night, incoming.timeline.night),
        time_not_stated=_merge_text(
            base.timeline.time_not_stated,
            current.timeline.time_not_stated,
            incoming.timeline.time_not_stated,
        ),
        remember=_scalar(
            base.timeline.remember, current.timeline.remember, incoming.timeline.remember
        ),
    )
    family = _merge_list(
        base.family,
        current.family,
        incoming.family,
        lambda item: item.name.casefold(),
        _merge_member,
    )
    return DayContent(
        timeline=timeline,
        family=family,
        pregnancy_baby=_merge_pregnancy(
            base.pregnancy_baby, current.pregnancy_baby, incoming.pregnancy_baby
        ),
        tags=_merge_text(base.tags, current.tags, incoming.tags),
    )


merge_content_three_way = merge_three_way
merge_day_content_three_way = merge_three_way
merge_daycontent_three_way = merge_three_way


# --- Timeline patches ----------------------------------------------------------------------


class TimelineAddition(_ContentModel):
    section: TimelineSection
    text: OneLine


class TimelineDeletion(_ContentModel):
    find_section: TimelineSection
    find: OneLine


class TimelineReplacement(_ContentModel):
    find_section: TimelineSection
    find: OneLine
    replace_section: TimelineSection
    replace: OneLine


_SECTION_FIELDS: dict[str, str] = {
    "morning": "morning",
    "afternoon": "afternoon",
    "evening": "evening",
    "night": "night",
    "time not stated": "time_not_stated",
    "time_not_stated": "time_not_stated",
}


def _section_field(section: str) -> str:
    try:
        return _SECTION_FIELDS[section.strip().casefold()]
    except KeyError as exc:
        raise ValueError(f"unknown timeline section: {section!r}") from exc


def add_timeline_bullet(timeline: Timeline, section: str, text: str) -> Timeline:
    """Append one bullet unless that exact bullet is already present."""
    result = timeline.model_copy(deep=True)
    target = getattr(result, _section_field(section))
    value = _one_line(text)
    if value and value not in target:
        target.append(value)
    return Timeline.model_validate(result.model_dump())


def delete_timeline_bullet(timeline: Timeline, section: str, find: str) -> Timeline:
    """Delete the first exactly matching bullet; a missing bullet is a no-op."""
    result = timeline.model_copy(deep=True)
    target = getattr(result, _section_field(section))
    if find in target:
        target.remove(find)
    return result


def replace_timeline_bullet(
    timeline: Timeline,
    find_section: str,
    find: str,
    replace_section: str,
    replace: str,
) -> Timeline:
    """Replace and optionally move the first exactly matching bullet."""
    result = timeline.model_copy(deep=True)
    source = getattr(result, _section_field(find_section))
    if find not in source:
        return result
    index = source.index(find)
    target_field = _section_field(replace_section)
    value = _one_line(replace)
    if target_field == _section_field(find_section):
        if value:
            source[index] = value
        else:
            source.pop(index)
    else:
        source.pop(index)
        target = getattr(result, target_field)
        if value and value not in target:
            target.append(value)
    return Timeline.model_validate(result.model_dump())


def move_timeline_bullet(
    timeline: Timeline,
    find_section: str,
    find: str,
    replace_section: str,
) -> Timeline:
    return replace_timeline_bullet(timeline, find_section, find, replace_section, find)


def apply_timeline_patches(
    timeline: Timeline,
    *,
    replacements: Iterable[TimelineReplacement | dict[str, Any]] = (),
    deletions: Iterable[TimelineDeletion | dict[str, Any]] = (),
    additions: Iterable[TimelineAddition | dict[str, Any]] = (),
) -> Timeline:
    """Apply prompt patches in replacement, deletion, addition order."""
    result = timeline.model_copy(deep=True)
    for raw in replacements:
        patch = TimelineReplacement.model_validate(raw)
        result = replace_timeline_bullet(
            result,
            patch.find_section,
            patch.find,
            patch.replace_section,
            patch.replace,
        )
    for raw in deletions:
        patch = TimelineDeletion.model_validate(raw)
        result = delete_timeline_bullet(result, patch.find_section, patch.find)
    for raw in additions:
        patch = TimelineAddition.model_validate(raw)
        result = add_timeline_bullet(result, patch.section, patch.text)
    return result


timeline_add = add_timeline_bullet
timeline_delete = delete_timeline_bullet
timeline_replace = replace_timeline_bullet
timeline_move = move_timeline_bullet
