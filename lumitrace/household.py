"""The owner's family file: who is in the family, and notes for the prompts.

The file is ``secrets/family.md`` in a checkout and ``/secrets/family.md`` in Docker.
It is not an environment variable. A missing file means no family and no notes.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import yaml

import lumitrace

OWNER_RELATIONS = frozenset({"me", "self"})
"""Relations that mark the owner (the person who keeps the journal)."""

_REPO_ROOT = Path(lumitrace.__file__).resolve().parents[1]


def family_file_candidates() -> tuple[Path, ...]:
    """Checkout path first, then the Docker mount. The first file that exists is used."""
    return (_REPO_ROOT / "secrets" / "family.md", Path("/secrets/family.md"))


@dataclass(frozen=True)
class Person:
    """One family member from the file's ``family`` list."""

    name: str
    relation: str = ""
    born: dt.date | None = None


@dataclass(frozen=True)
class Household:
    """Parsed family file: the member list, plus the Markdown notes under the front matter."""

    people: tuple[Person, ...] = ()
    notes: str = ""

    @property
    def members(self) -> list[str]:
        """Names in file order."""
        return [person.name for person in self.people]

    @property
    def relations(self) -> dict[str, str]:
        """``{name: relation}`` in file order; ``""`` when no relation is given."""
        return {person.name: person.relation for person in self.people}

    @property
    def owner_name(self) -> str | None:
        """The member whose relation is ``me`` or ``self``."""
        for person in self.people:
            if person.relation.casefold() in OWNER_RELATIONS:
                return person.name
        return None

    def describe(self) -> str:
        """Prompt text: ``Sam (the author), Maya (the author's wife, born 1990-04-12), Leo``."""
        owner = self.owner_name
        parts: list[str] = []
        for person in self.people:
            bits: list[str] = []
            if person.name == owner:
                bits.append("the author")
            elif person.relation:
                bits.append(f"the author's {person.relation}")
            if person.born is not None:
                bits.append(f"born {person.born.isoformat()}")
            parts.append(f"{person.name} ({', '.join(bits)})" if bits else person.name)
        return ", ".join(parts)

    @property
    def glossary(self) -> str:
        """Notes sent to the prompts. ``(none)`` when the file has no body."""
        return self.notes or "(none)"


def load_household(path: Path | None = None) -> Household:
    """Read one family file. With no path, search :func:`family_file_candidates`.

    A missing searched file is an empty household. A path you pass in must exist.
    A file that exists but cannot be read as a family file raises ``ValueError``.
    """
    if path is None:
        path = next(
            (candidate for candidate in family_file_candidates() if candidate.is_file()),
            None,
        )
        if path is None:
            return Household()
    elif not path.is_file():
        raise ValueError(f"family file not found: {path}")
    try:
        return parse_household(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc


def parse_household(text: str) -> Household:
    """Split YAML front matter (the ``family`` list) from the Markdown notes below it.

    A file with no front matter is notes only. Blank names are skipped. The first
    spelling of a name wins; a later repeat (any case) is dropped.
    """
    text = text.lstrip("\ufeff")
    split = _split_front_matter(text)
    if split is None:
        return Household(notes=text.strip())
    raw_yaml, body = split
    return Household(people=_parse_family(raw_yaml), notes=body.strip())


def _split_front_matter(text: str) -> tuple[str, str] | None:
    """YAML between the opening ``---`` line and the next line that is only ``---``."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "".join(lines[1:index]), "".join(lines[index + 1 :])
    return None


def _parse_family(raw_yaml: str) -> tuple[Person, ...]:
    if not raw_yaml.strip():
        return ()
    try:
        data = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        raise ValueError("family front matter is not valid YAML") from exc
    if data is None:
        return ()
    if not isinstance(data, dict):
        raise ValueError("family front matter must be a mapping")
    family = data.get("family", [])
    if family is None:
        return ()
    if not isinstance(family, list):
        raise ValueError("family must be a list")
    people: list[Person] = []
    seen: set[str] = set()
    for index, item in enumerate(family, start=1):
        person = _parse_person(item, index)
        if person is None:
            continue
        key = person.name.casefold()
        if key in seen:
            continue
        seen.add(key)
        people.append(person)
    return tuple(people)


def _parse_person(item: object, index: int) -> Person | None:
    if not isinstance(item, dict):
        raise ValueError(f"family entry {index} must be a mapping with a name")
    name = " ".join(str(item.get("name") or "").split())
    if not name:
        return None
    relation = " ".join(str(item.get("relation") or "").split())
    return Person(name=name, relation=relation, born=_parse_born(item.get("born"), name))


def _parse_born(value: object, name: str) -> dt.date | None:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError(f"born for {name} must be YYYY-MM-DD") from exc
    raise ValueError(f"born for {name} must be YYYY-MM-DD")
