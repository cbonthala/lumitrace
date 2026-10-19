from __future__ import annotations

from lumitrace.frames import daycontent as C


def _content() -> C.DayContent:
    return C.DayContent(
        timeline=C.Timeline(
            highlight="  A sunny\npicnic  ",
            context=C.DayContext(
                weather="  Warm   and clear ",
                places_visited=[C.PlaceContext(name="River Park", family_members=["Alex", "Bo"])],
                people_met=[
                    C.PersonContext(
                        name="Dr. Rao",
                        relationship="pediatrician",
                        context="annual visit",
                        family_members=["Bo"],
                    )
                ],
                special_occasions=["Checkup"],
                media=["photo-01.jpg"],
            ),
            morning=["Packed lunch"],
            afternoon=["Played by the river"],
            evening=[],
            night=["Read “Moon | Stars”"],
            time_not_stated=["Found a smooth stone"],
            remember="Bo said, “Again!”",
        ),
        family=[
            C.FamilyTracker(
                name=r"Alex | Sr.\Parent",
                food=C.FoodTracker(
                    breakfast=C.Meal(status="consumed", items=[r"eggs | toast", "tea"]),
                    lunch=C.Meal(status="skipped"),
                    dinner=C.Meal(status="consumed", items=["Consumed", r"soup \ bread"]),
                    snacks_drinks=C.Meal(status="not_recorded"),
                    food_response=[r"liked A | B", r"no \ reaction"],
                ),
                health_fitness=C.HealthFitness(
                    sleep=["7 hours", r"woke at 6 | 30"],
                    exercise_movement=[
                        C.ExerciseMovement(activity=r"walk \ jog | hills", minutes=35)
                    ],
                    energy=C.Rating(score=4, description=r"steady | alert"),
                    mood=C.Rating(description=r"calm \ focused"),
                    body_digestion=["felt well"],
                    symptoms_medication=[r"vitamin D | B12"],
                ),
                daily_routine=C.DailyRoutine(
                    work_daycare=["worked from home"],
                    responsibilities_activities=[r"dishes | laundry"],
                    reading_learning=[r"read C:\notes"],
                    screen_media=["one episode"],
                ),
                interests_preferences=C.InterestsPreferences(
                    enjoyed=["river walk"],
                    disliked_avoided=[r"mud | puddles"],
                    current_interests=[r"maps \ trails"],
                ),
                growth_learning=C.GrowthLearning(
                    learned_practiced=["map reading"],
                    progress_change=["walked farther"],
                    new_skill_behavior=[r"used a compass | unaided"],
                    words_quotes=[r"“left \ right”"],
                ),
            ),
            C.FamilyTracker(
                name="Bo",
                food=C.FoodTracker(
                    breakfast=C.Meal(status="consumed", items=["oatmeal"]),
                    lunch=C.Meal(status="not_recorded"),
                    dinner=C.Meal(status="skipped", items=["said no"]),
                ),
            ),
        ],
        pregnancy_baby=C.PregnancyBaby(
            pregnant_person="Ya | Mini\\",
            gestational_age="18 weeks, 2 days",
            maternal_symptoms=[r"mild back | ache"],
            cravings_aversions=["mango"],
            supplements_medication=[r"prenatal \ iron"],
            rest_self_care=["nap"],
            baby_movement=["two kicks"],
            appointment_scan=["routine scan"],
            heartbeat_growth=[r"normal | update"],
            questions_concerns=["sleep position"],
        ),
        tags=["family", "#river-day"],
    )


def test_models_accept_fill_day_shape_and_normalise_values() -> None:
    content = C.DayContent.model_validate(
        {
            "headline": "ignored",
            "timeline": {
                "highlight": " one\n thing ",
                "context": None,
                "morning": [" woke   up ", "", "  "],
                "afternoon": None,
            },
            "trackers": {
                "family": [{"name": " Sam ", "food": None}],
                "pregnancy_baby": None,
                "tags": ["#family", "", " walk "],
            },
        }
    )
    assert content.timeline.highlight == "one thing"
    assert content.timeline.morning == ["woke up"]
    assert content.timeline.afternoon == []
    assert content.family[0].name == "Sam"
    assert content.tags == ["family", "walk"]


def test_markdown_round_trip_preserves_tricky_cells_and_dynamic_names() -> None:
    content = _content()
    markdown = C.render(content)

    assert "## Day timeline" in markdown
    assert "### Time not stated" in markdown
    assert "## Family trackers" in markdown
    assert markdown.count("| Alex \\| Sr.\\\\Parent |") == 5
    assert "eggs \\| toast<br>tea" in markdown
    assert "walk \\\\ jog \\| hills (35 min)" in markdown
    assert C.parse(markdown) == content
    assert C.render(C.parse(markdown)) == markdown


def test_reserved_markdown_values_and_literal_html_round_trip() -> None:
    content = C.DayContent(
        timeline=C.Timeline(
            highlight="—",
            context=C.DayContext(
                weather="<clear> & mild",
                places_visited=[
                    C.PlaceContext(name="A<br>B", family_members=["Last, First"]),
                    C.PlaceContext(name="Room (Family: sign)"),
                ],
                special_occasions=["Tea<br>cake", "A — B"],
            ),
            morning=["—", "<b>literal</b>"],
            remember="A & B",
        ),
        family=[
            C.FamilyTracker(
                name="Pat",
                food=C.FoodTracker(breakfast=C.Meal(status="consumed", items=["—", "<br>"])),
                health_fitness=C.HealthFitness(
                    exercise_movement=[C.ExerciseMovement(activity="walk (outside) (35 min)")],
                    mood=C.Rating(description="4/5"),
                ),
                daily_routine=C.DailyRoutine(reading_learning=[r"C:\notes"]),
            )
        ],
        tags=["a&b", "river day"],
    )

    markdown = C.render(content)

    assert "- &#8212;" in markdown
    assert "A&lt;br&gt;B" in markdown
    assert "Tea&lt;br&gt;cake<br>A &#8212; B" in markdown
    assert C.parse(markdown) == content

    # A hand-written backslash only escapes table syntax when followed by ``|`` or ``\``.
    edited = markdown.replace(r"C:\\notes", r"C:\notes")
    assert C.parse(edited).family[0].daily_routine.reading_learning == [r"C:\notes"]


def test_dynamic_family_tables_are_matched_by_name_not_row_position() -> None:
    content = C.DayContent(
        family=[
            C.FamilyTracker(name="Alex", health_fitness=C.HealthFitness(sleep=["Alex slept"])),
            C.FamilyTracker(name="Bo", health_fitness=C.HealthFitness(sleep=["Bo slept"])),
        ]
    )
    markdown = C.render(content)
    alex = "| Alex | Alex slept | — | — | — | — | — |"
    bo = "| Bo | Bo slept | — | — | — | — | — |"
    markdown = markdown.replace(f"{alex}\n{bo}", f"{bo}\n{alex}")
    markdown = markdown.replace(
        alex,
        f"{alex}\n| Owner row | 9 hours | — | — | — | — | — |",
    )

    parsed = C.parse(markdown)

    assert [member.name for member in parsed.family] == ["Alex", "Bo", "Owner row"]
    assert parsed.family[0].health_fitness.sleep == ["Alex slept"]
    assert parsed.family[1].health_fitness.sleep == ["Bo slept"]
    assert parsed.family[2].health_fitness.sleep == ["9 hours"]


def test_empty_time_not_stated_is_omitted_and_empty_cells_are_em_dashes() -> None:
    content = C.DayContent(family=[C.FamilyTracker(name="One")])
    markdown = C.render(content)
    assert "### Time not stated" not in markdown
    assert "| One | — | — | — | — | — |" in markdown
    assert C.parse(markdown) == content


def test_meal_statuses_survive_markdown_round_trip() -> None:
    family = C.FamilyTracker(
        name="Pat",
        food=C.FoodTracker(
            breakfast=C.Meal(status="consumed"),
            lunch=C.Meal(status="skipped"),
            dinner=C.Meal(status="not_recorded"),
            snacks_drinks=C.Meal(status="skipped", items=["explicitly refused"]),
        ),
    )
    content = C.DayContent(family=[family])
    markdown = C.render(content)
    assert "| Pat | Consumed | Skipped | — | Skipped<br>explicitly refused | — |" in markdown
    assert C.parse(markdown) == content


def test_not_recorded_meal_cannot_hide_items() -> None:
    assert C.Meal(status="not_recorded", items=["ambiguous"]) == C.Meal()


def test_three_way_merge_preserves_owner_scalar_list_and_table_edits() -> None:
    base = C.DayContent(
        timeline=C.Timeline(
            highlight="Park day",
            morning=["Ate eggs", "Walked"],
            context=C.DayContext(weather="sunny"),
        ),
        family=[
            C.FamilyTracker(
                name="Sam",
                food=C.FoodTracker(breakfast=C.Meal(status="consumed", items=["eggs", "toast"])),
                health_fitness=C.HealthFitness(mood=C.Rating(score=3, description="fine")),
            )
        ],
        tags=["family", "walk"],
    )
    current = base.model_copy(deep=True)
    current.timeline.highlight = "My park title"
    current.timeline.morning = ["Ate eggs", "Owner note"]
    current.family[0].food.breakfast = C.Meal(status="skipped", items=["owner explanation"])
    current.family[0].health_fitness.mood.description = "peaceful"
    current.tags = ["family", "owner-tag"]

    incoming = C.DayContent(
        timeline=C.Timeline(
            highlight="River day",
            morning=["Ate eggs", "Walked", "Found a stone"],
            context=C.DayContext(weather="cloudy"),
        ),
        family=[
            C.FamilyTracker(
                name="Sam",
                food=C.FoodTracker(
                    breakfast=C.Meal(status="consumed", items=["eggs", "toast", "berries"])
                ),
                health_fitness=C.HealthFitness(mood=C.Rating(score=4, description="happy")),
            ),
            C.FamilyTracker(name="Bo"),
        ],
        tags=["family", "walk", "river"],
    )

    merged = C.merge_three_way(base, current, incoming)

    assert merged.timeline.highlight == "My park title"
    assert merged.timeline.context.weather == "cloudy"
    assert merged.timeline.morning == ["Ate eggs", "Found a stone", "Owner note"]
    assert merged.family[0].food.breakfast == C.Meal(
        status="skipped", items=["berries", "owner explanation"]
    )
    assert merged.family[0].health_fitness.mood == C.Rating(score=4, description="peaceful")
    assert [member.name for member in merged.family] == ["Sam", "Bo"]
    assert merged.tags == ["family", "river", "owner-tag"]


def test_three_way_merge_keeps_owner_row_additions_and_removals() -> None:
    base = C.DayContent(family=[C.FamilyTracker(name="Removed"), C.FamilyTracker(name="Changed")])
    current = C.DayContent(
        family=[
            C.FamilyTracker(
                name="Changed",
                daily_routine=C.DailyRoutine(work_daycare=["owner edit"]),
            ),
            C.FamilyTracker(name="Owner row"),
        ]
    )
    incoming = C.DayContent(
        family=[
            C.FamilyTracker(
                name="Removed",
                daily_routine=C.DailyRoutine(work_daycare=["model update"]),
            ),
            C.FamilyTracker(
                name="Changed",
                daily_routine=C.DailyRoutine(work_daycare=["new model value"]),
            ),
            C.FamilyTracker(name="New row"),
        ]
    )
    merged = C.merge_three_way(base, current, incoming)
    assert [member.name for member in merged.family] == ["Changed", "New row", "Owner row"]
    assert merged.family[0].daily_routine.work_daycare == [
        "new model value",
        "owner edit",
    ]


def test_three_way_merge_keeps_owner_wording_for_the_same_list_fact() -> None:
    base = C.DayContent(tags=["tea"])
    current = C.DayContent(tags=["tea (owner wording)"])
    incoming = C.DayContent(tags=["tea (model gloss)", "new-tag"])

    merged = C.merge_three_way(base, current, incoming)

    assert merged.tags == ["tea (owner wording)", "new-tag"]


def test_timeline_patch_helpers_use_exact_matching_and_can_move() -> None:
    original = C.Timeline(
        morning=["Exact bullet", "Keep"],
        afternoon=["Delete me"],
        evening=["Already there"],
    )
    unchanged = C.delete_timeline_bullet(original, "Morning", "exact bullet")
    assert unchanged == original

    patched = C.apply_timeline_patches(
        original,
        replacements=[
            {
                "find_section": "Morning",
                "find": "Exact bullet",
                "replace_section": "Night",
                "replace": "Corrected bullet",
            }
        ],
        deletions=[{"find_section": "Afternoon", "find": "Delete me"}],
        additions=[
            {"section": "Evening", "text": "Already there"},
            {"section": "Time not stated", "text": "New detail"},
        ],
    )
    assert original.morning == ["Exact bullet", "Keep"]
    assert patched.morning == ["Keep"]
    assert patched.afternoon == []
    assert patched.evening == ["Already there"]
    assert patched.night == ["Corrected bullet"]
    assert patched.time_not_stated == ["New detail"]

    moved = C.move_timeline_bullet(patched, "Night", "Corrected bullet", "Morning")
    assert moved.night == []
    assert moved.morning == ["Keep", "Corrected bullet"]


def test_legacy_conversion_uses_only_mapping_data() -> None:
    content = C.from_legacy_facts(
        {
            "weather": "rain",
            "highlights": ["Main event", "Second detail"],
            "places": ["Library"],
            "family": [
                {
                    "name": "Sam",
                    "meals": [{"type": "breakfast", "items": ["eggs"]}],
                    "health": ["headache"],
                    "feelings": ["tired"],
                    "moments": ["first word"],
                }
            ],
        }
    )
    assert content.timeline.highlight == "Main event"
    assert content.timeline.time_not_stated == ["Second detail"]
    assert content.timeline.context.places_visited == [C.PlaceContext(name="Library")]
    assert content.family[0].food.breakfast == C.Meal(status="consumed", items=["eggs"])


def test_legacy_projection_keeps_compatible_tracker_facts() -> None:
    content = C.DayContent(
        timeline=C.Timeline(
            highlight="Main event",
            remember="Exact quote",
            context=C.DayContext(
                weather="rain",
                places_visited=[C.PlaceContext(name="Library", family_members=["Sam", "Bo"])],
                people_met=[
                    C.PersonContext(
                        name="Ravi",
                        relationship="friend",
                        context="at lunch",
                        family_members=["Sam"],
                    )
                ],
                special_occasions=["Birthday"],
            ),
        ),
        family=[
            C.FamilyTracker(
                name="Sam",
                food=C.FoodTracker(
                    breakfast=C.Meal(status="consumed", items=["eggs"]),
                    lunch=C.Meal(status="skipped"),
                ),
                health_fitness=C.HealthFitness(
                    exercise_movement=[C.ExerciseMovement(activity="walk", minutes=20)],
                    mood=C.Rating(description="happy"),
                ),
                daily_routine=C.DailyRoutine(responsibilities_activities=["school pickup"]),
            )
        ],
    )

    legacy = C.to_legacy_facts(content)

    assert legacy["highlights"] == ["Main event"]
    assert legacy["remember"] == "Exact quote"
    assert legacy["places"] == ["Library (Sam, Bo)"]
    assert legacy["people"] == ["Ravi - friend - at lunch (Sam)"]
    assert legacy["memories"] == ["Birthday"]
    assert legacy["family"][0]["meals"] == [
        {"type": "breakfast", "items": ["eggs"]},
        {"type": "lunch", "items": ["Skipped"]},
    ]
    assert legacy["family"][0]["health"] == ["walk (20 min)"]
    assert legacy["family"][0]["feelings"] == ["happy"]
    assert legacy["activities"] == [{"kind": "school pickup (Sam)", "minutes": None}]
