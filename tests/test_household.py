"""Parser for secrets/family.md. Fictional names only."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from lumitrace.household import Household, Person, load_household, parse_household

SAMPLE = """---
family:
  - name: Sam
    relation: me
  - name:  Maya
    relation: wife
    born: 1990-04-12
  - name: Leo
    relation: son
    born: 2023-06-01
  - name: leo
    relation: duplicate
  - name: " "
  - name: Rose
---

## Other people
- Leon: Leo's daycare friend.
"""


def test_parse_household_reads_people_birth_dates_and_notes() -> None:
    household = parse_household(SAMPLE)
    assert household.people == (
        Person("Sam", "me"),
        Person("Maya", "wife", dt.date(1990, 4, 12)),
        Person("Leo", "son", dt.date(2023, 6, 1)),
        Person("Rose"),
    )
    assert household.owner_name == "Sam"
    assert household.members == ["Sam", "Maya", "Leo", "Rose"]
    assert household.describe() == (
        "Sam (the author), Maya (the author's wife, born 1990-04-12), "
        "Leo (the author's son, born 2023-06-01), Rose"
    )
    assert household.glossary.startswith("## Other people")
    assert "Leon" in household.glossary


def test_self_marks_the_owner_and_notes_only_files_have_no_members() -> None:
    marked = parse_household("---\nfamily:\n  - {name: Sam, relation: Self}\n---\n")
    assert marked.owner_name == "Sam"
    notes_only = parse_household("## Foods\n- thotakura = amaranth leaves\n")
    assert notes_only.people == ()
    assert notes_only.glossary == "## Foods\n- thotakura = amaranth leaves"
    assert parse_household("").glossary == "(none)"
    assert parse_household("---\n---\n").people == ()


def test_bad_family_file_is_refused() -> None:
    with pytest.raises(ValueError, match="not valid YAML"):
        parse_household("---\nfamily: [\n---\n")
    with pytest.raises(ValueError, match="must be a list"):
        parse_household("---\nfamily: Sam\n---\n")
    with pytest.raises(ValueError, match="must be a mapping"):
        parse_household("---\nfamily:\n  - Sam\n---\n")
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        parse_household("---\nfamily:\n  - {name: Leo, born: 2023}\n---\n")


def test_the_example_file_parses() -> None:
    example = Path(__file__).resolve().parents[1] / "docs" / "templates" / "family.example.md"
    household = load_household(example)
    assert household.members == ["Sam", "Maya", "Leo"]
    assert household.owner_name == "Sam"
    assert household.people[1].born == dt.date(1990, 4, 12)
    assert "Leon" in household.glossary


def test_load_household_reads_a_path_and_an_empty_search(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "family.md"
    path.write_text("---\nfamily:\n  - {name: Maya, relation: wife}\n---\n", encoding="utf-8")
    assert load_household(path).relations == {"Maya": "wife"}
    missing = tmp_path / "missing.md"
    with pytest.raises(ValueError, match="not found"):
        load_household(missing)
    monkeypatch.setattr("lumitrace.household.family_file_candidates", lambda: (missing,))
    assert load_household() == Household()
    broken = tmp_path / "broken.md"
    broken.write_text("---\nfamily: [\n---\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"broken\.md"):
        load_household(broken)
