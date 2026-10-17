"""The MCP tools as plain Python: ``search``, ``get_day``, ``query_facts``, ``on_this_day`` and
``feedback``. ``server.py`` registers them with descriptions; tests call them directly.

Every result is a JSON-ready dict with dates as ``YYYY-MM-DD`` so the AI client can cite them.
Journal text is never logged.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import secrets
import sqlite3
from dataclasses import dataclass
from typing import Any, Literal

from lumitrace.config import Settings
from lumitrace.frames.dayfile import (
    DayFileParseError,
    day_dir,
    day_file_path,
    parse,
    system_path,
)
from lumitrace.frames.storage import Storage, StorageError, get_storage
from lumitrace.lens.dates import (
    DateArgumentError,
    parse_date,
    parse_month_day,
    parse_range,
    today,
)
from lumitrace.lens.index import (
    INDEX_EMPTY_NOTE,
    INDEX_MISSING_NOTE,
    is_empty,
    open_index,
    open_index_for_write,
)
from lumitrace.lens.search import hybrid_search, make_snippet, query_terms

logger = logging.getLogger(__name__)

FactKind = Literal["meals", "activities", "people", "places", "family", "mood", "highlights"]
FACT_KINDS: tuple[str, ...] = (
    "meals",
    "activities",
    "people",
    "places",
    "family",
    "mood",
    "highlights",
)
Rating = Literal["wrong", "incomplete", "good", "other"]
RATINGS: tuple[str, ...] = ("wrong", "incomplete", "good", "other")

MAX_SEARCH_LIMIT = 50
MAX_FACT_LIMIT = 500
MAX_YEARS_BACK = 100
MAX_FEEDBACK_CHARS = 20_000
TOP_GROUPS = 20
SUMMARY_CHARS = 500

_ISO_DATE_IN_TEXT = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


class ToolInputError(ValueError):
    """Bad tool arguments; the message is returned to the AI client."""


@dataclass(frozen=True)
class _FactSpec:
    table: str
    columns: tuple[str, ...]
    match_columns: tuple[str, ...]
    order: str
    base_where: str = ""


_FACT_SPECS: dict[str, _FactSpec] = {
    "meals": _FactSpec(
        "meals",
        ("person", "meal_type", "item"),
        ("item", "meal_type"),
        "date DESC, position",
    ),
    "activities": _FactSpec("activities", ("kind", "minutes"), ("kind",), "date DESC, position"),
    "people": _FactSpec("people", ("name",), ("name",), "date DESC, position"),
    "places": _FactSpec("places", ("name",), ("name",), "date DESC, position"),
    "family": _FactSpec(
        "family_facts",
        ("person", "category", "text", "minutes"),
        ("text", "category"),
        "date DESC, position",
    ),
    "highlights": _FactSpec("highlights", ("text",), ("text",), "date DESC, position"),
    "mood": _FactSpec(
        "days",
        ("mood", "mood_score"),
        ("mood",),
        "date DESC",
        base_where="(mood IS NOT NULL OR mood_score IS NOT NULL)",
    ),
}


def _clamp(value: int | None, default: int, low: int, high: int) -> int:
    if value is None:
        return default
    return max(low, min(high, int(value)))


def _like_pattern(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _rows(conn: sqlite3.Connection, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params)]


class LensTools:
    """Tool implementations bound to settings and (lazily) a storage backend."""

    def __init__(self, settings: Settings, storage: Storage | None = None) -> None:
        self.settings = settings
        self._storage = storage

    @property
    def storage(self) -> Storage:
        if self._storage is None:
            self._storage = get_storage(self.settings)
        return self._storage

    # --- search -----------------------------------------------------------------------------

    def search(
        self,
        query: str,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int | None = 10,
    ) -> dict[str, Any]:
        query = (query or "").strip()
        if not query:
            raise ToolInputError("query must not be empty")
        start, end = parse_range(from_date, to_date, self.settings)
        limit = _clamp(limit, 10, 1, MAX_SEARCH_LIMIT)
        result: dict[str, Any] = {
            "query": query,
            "from_date": start.isoformat() if start else None,
            "to_date": end.isoformat() if end else None,
            "results": [],
        }
        with open_index(self.settings) as conn:
            if conn is None:
                result["note"] = INDEX_MISSING_NOTE
                return result
            if is_empty(conn):
                result["note"] = INDEX_EMPTY_NOTE
                return result
            outcome = hybrid_search(conn, self.settings, query, start=start, end=end, limit=limit)
        terms = query_terms(query)
        result["results"] = [
            {
                "date": hit.date,
                "section": hit.section,
                "heading": hit.heading,
                "snippet": make_snippet(hit.text, terms),
                "path": hit.path,
                "score": hit.score,
                "matched_by": hit.matched_by,
            }
            for hit in outcome.hits
        ]
        result["search_modes"] = outcome.modes
        notes = list(outcome.notes)
        if not outcome.hits:
            notes.append("No matching entries found.")
        if notes:
            result["note"] = " ".join(notes)
        return result

    # --- get_day ----------------------------------------------------------------------------

    def get_day(self, date: str) -> dict[str, Any]:
        day_date = parse_date(date, self.settings)
        path = day_file_path(day_date)
        result: dict[str, Any] = {"date": day_date.isoformat(), "path": path, "found": False}
        try:
            markdown = self.storage.read_text(path)
        except FileNotFoundError:
            result["note"] = f"There is no journal entry for {day_date.isoformat()}."
            return result
        try:
            day = parse(markdown, fallback_date=day_date)
        except DayFileParseError as exc:
            raise ToolInputError(
                f"The day file for {day_date.isoformat()} could not be read: {exc}"
            ) from exc

        audio_names = list(
            dict.fromkeys([*day.meta.audio, *(c.audio for c in day.captures if c.audio)])
        )
        photo_names = list(
            dict.fromkeys([*day.meta.photos, *(p for c in day.captures for p in c.photos)])
        )
        result.update(
            found=True,
            title=day.title,
            facts=day.facts.model_dump(mode="json"),
            journal=day.journal,
            notes=day.notes,
            transcript=[
                {
                    "time": capture.captured_at.isoformat(),
                    "kind": capture.kind,
                    "location": capture.location,
                    "audio": capture.audio,
                    "photos": capture.photos,
                    "text": capture.text,
                    "translation": capture.translation or None,
                }
                for capture in day.captures
            ],
            audio=[self._media_link(day_date, name) for name in audio_names],
            photos=[self._media_link(day_date, name) for name in photo_names],
            user_edited=day.is_user_edited(),
        )
        return result

    def _media_link(self, day_date: dt.date, name: str) -> dict[str, Any]:
        path = f"{day_dir(day_date)}/{name}"
        item: dict[str, Any] = {"name": name, "path": path, "link": None}
        try:
            item["link"] = self.storage.get_share_link(path)
        except FileNotFoundError:
            item["error"] = "file not found in storage"
        except (StorageError, OSError):
            logger.warning("share link failed for %s", path, exc_info=True)
            item["error"] = "link unavailable"
        return item

    # --- query_facts ------------------------------------------------------------------------

    def query_facts(
        self,
        kind: str,
        contains: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int | None = 50,
        person: str | None = None,
    ) -> dict[str, Any]:
        spec = _FACT_SPECS.get((kind or "").strip().lower())
        if spec is None:
            raise ToolInputError(f"kind must be one of: {', '.join(FACT_KINDS)}; got {kind!r}")
        kind = kind.strip().lower()
        person = (person or "").strip() or None
        if person and kind not in ("family", "meals"):
            raise ToolInputError("person only applies to kind 'family' or 'meals'")
        start, end = parse_range(from_date, to_date, self.settings)
        limit = _clamp(limit, 50, 1, MAX_FACT_LIMIT)
        contains = (contains or "").strip() or None
        result: dict[str, Any] = {
            "kind": kind,
            "person": person,
            "contains": contains,
            "from_date": start.isoformat() if start else None,
            "to_date": end.isoformat() if end else None,
            "rows": [],
            "counts": {"rows": 0, "days": 0, "first_date": None, "last_date": None},
            "aggregates": {},
        }

        where: list[str] = [spec.base_where] if spec.base_where else []
        params: list[Any] = []
        if person:
            where.append("person = ? COLLATE NOCASE")
            params.append(person)
        if start:
            where.append("date >= ?")
            params.append(start.isoformat())
        if end:
            where.append("date <= ?")
            params.append(end.isoformat())
        if contains:
            where.append(
                "(" + " OR ".join(f"{c} LIKE ? ESCAPE '\\'" for c in spec.match_columns) + ")"
            )
            params.extend([_like_pattern(contains)] * len(spec.match_columns))
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""

        with open_index(self.settings) as conn:
            if conn is None:
                result["note"] = INDEX_MISSING_NOTE
                return result
            cols = ", ".join(("date", *spec.columns))
            result["rows"] = _rows(
                conn,
                f"SELECT {cols} FROM {spec.table}{where_sql} ORDER BY {spec.order} LIMIT ?",
                [*params, limit],
            )
            counts = conn.execute(
                f"SELECT COUNT(*) AS rows, COUNT(DISTINCT date) AS days, MIN(date) AS first_date, "
                f"MAX(date) AS last_date FROM {spec.table}{where_sql}",
                params,
            ).fetchone()
            result["counts"] = dict(counts)
            result["aggregates"] = _fact_aggregates(conn, kind, spec, where_sql, params)

        result["truncated"] = result["counts"]["rows"] > len(result["rows"])
        if not result["rows"]:
            result["note"] = "No matching facts found."
        return result

    # --- on_this_day ------------------------------------------------------------------------

    def on_this_day(self, date: str | None = None, years_back: int | None = 10) -> dict[str, Any]:
        years_back = _clamp(years_back, 10, 1, MAX_YEARS_BACK)
        text = (date or "").strip()
        month_day = parse_month_day(text) if text else None
        if month_day is not None:
            reference_year = today(self.settings).year
            month, day = month_day
        else:
            ref = parse_date(text, self.settings) if text else today(self.settings)
            reference_year, month, day = ref.year, ref.month, ref.day
        mmdd = f"{month:02d}-{day:02d}"
        result: dict[str, Any] = {
            "month_day": mmdd,
            "reference_year": reference_year,
            "years_back": years_back,
            "days": [],
        }
        with open_index(self.settings) as conn:
            if conn is None:
                result["note"] = INDEX_MISSING_NOTE
                return result
            rows = _rows(
                conn,
                "SELECT date, title, mood, mood_score, city, weather, path FROM days "
                "WHERE substr(date, 6) = ? AND date >= ? AND date < ? ORDER BY date DESC",
                [mmdd, f"{reference_year - years_back:04d}-01-01", f"{reference_year:04d}-01-01"],
            )
            for row in rows:
                row["years_ago"] = reference_year - int(row["date"][:4])
                row["highlights"] = _column(conn, "highlights", "text", row["date"])
                row["family"] = _rows(
                    conn,
                    "SELECT person, category, text, minutes FROM family_facts WHERE date = ? "
                    "ORDER BY position",
                    [row["date"]],
                )
                row["people"] = _column(conn, "people", "name", row["date"])
                row["places"] = _column(conn, "places", "name", row["date"])
                summary = conn.execute(
                    "SELECT text FROM passages WHERE date = ? AND section = 'journal' "
                    "ORDER BY ordinal LIMIT 1",
                    (row["date"],),
                ).fetchone()
                row["summary"] = make_snippet(summary[0], [], SUMMARY_CHARS) if summary else None
        result["days"] = rows
        if not rows:
            result["note"] = (
                f"No entries on {mmdd} in the {years_back} years before {reference_year}."
            )
        return result

    # --- feedback ---------------------------------------------------------------------------

    def feedback(
        self,
        question: str,
        answer: str,
        comment: str,
        rating: str | None = "wrong",
        dates: list[str] | None = None,
        tool: str | None = None,
        client: str | None = None,
    ) -> dict[str, Any]:
        rating = (rating or "wrong").strip().lower()
        if rating not in RATINGS:
            raise ToolInputError(f"rating must be one of: {', '.join(RATINGS)}; got {rating!r}")
        question = (question or "")[:MAX_FEEDBACK_CHARS]
        answer = (answer or "")[:MAX_FEEDBACK_CHARS]
        comment = (comment or "")[:MAX_FEEDBACK_CHARS]
        if not (question or answer or comment):
            raise ToolInputError("feedback needs at least a question, an answer or a comment")
        cited = _cited_dates(dates, answer, self.settings)

        now = dt.datetime.now(dt.UTC).replace(microsecond=0)
        record = {
            "created_at": now.isoformat(),
            "rating": rating,
            "question": question,
            "answer": answer,
            "comment": comment,
            "dates": cited,
            "tool": tool,
            "client": client,
        }
        storage_path: str | None = system_path(
            "feedback",
            f"{now:%Y}",
            f"{now:%m}",
            f"{now:%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}.json",
        )
        try:
            self.storage.write_text(
                storage_path,
                json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                content_type="application/json",
            )
        except Exception:
            logger.warning("could not write the feedback copy to storage", exc_info=True)
            storage_path = None

        row_id: int | None = None
        try:
            with open_index_for_write(self.settings) as conn, conn:
                cur = conn.execute(
                    "INSERT INTO feedback(created_at, rating, question, answer, comment, "
                    "dates_json, tool, client, storage_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        record["created_at"],
                        rating,
                        question,
                        answer,
                        comment,
                        json.dumps(cited),
                        tool,
                        client,
                        storage_path,
                    ),
                )
                row_id = cur.lastrowid
        except Exception:
            logger.warning("could not write feedback to the index", exc_info=True)
            if storage_path is None:
                raise
        logger.info("feedback saved (rating=%s, id=%s)", rating, row_id)
        return {
            "saved": True,
            "id": row_id,
            "rating": rating,
            "dates": cited,
            "storage_path": storage_path,
            "message": "Feedback saved. Thank you; it is used to improve Lumitrace.",
        }


def _column(conn: sqlite3.Connection, table: str, column: str, date: str) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            f"SELECT {column} FROM {table} WHERE date = ? ORDER BY position", (date,)
        )
    ]


def _cited_dates(dates: list[str] | None, answer: str, settings: Settings) -> list[str]:
    found: list[str] = []
    if dates:
        for value in dates:
            try:
                found.append(parse_date(value, settings, name="dates").isoformat())
            except DateArgumentError as exc:
                raise ToolInputError(str(exc)) from exc
    else:
        for value in _ISO_DATE_IN_TEXT.findall(answer):
            try:
                found.append(dt.date.fromisoformat(value).isoformat())
            except ValueError:
                continue
    return sorted(set(found))


def _fact_aggregates(
    conn: sqlite3.Connection,
    kind: str,
    spec: _FactSpec,
    where_sql: str,
    params: list[Any],
) -> dict[str, Any]:
    table = spec.table
    if kind == "meals":
        return {
            "top_items": _rows(
                conn,
                f"SELECT lower(item) AS item, COUNT(*) AS times, COUNT(DISTINCT date) AS days "
                f"FROM {table}{where_sql} GROUP BY lower(item) ORDER BY times DESC, item LIMIT ?",
                [*params, TOP_GROUPS],
            ),
            "by_meal_type": _rows(
                conn,
                f"SELECT lower(meal_type) AS meal_type, COUNT(*) AS items, "
                f"COUNT(DISTINCT date) AS days FROM {table}{where_sql} "
                f"GROUP BY lower(meal_type) ORDER BY items DESC, meal_type",
                params,
            ),
        }
    if kind == "activities":
        totals = conn.execute(
            f"SELECT SUM(minutes) AS total_minutes FROM {table}{where_sql}", params
        ).fetchone()
        return {
            "total_minutes": totals["total_minutes"],
            "by_kind": _rows(
                conn,
                f"SELECT lower(kind) AS kind, COUNT(*) AS times, COUNT(DISTINCT date) AS days, "
                f"SUM(minutes) AS total_minutes, ROUND(AVG(minutes), 1) AS avg_minutes "
                f"FROM {table}{where_sql} GROUP BY lower(kind) ORDER BY times DESC, kind LIMIT ?",
                [*params, TOP_GROUPS],
            ),
        }
    if kind in ("people", "places"):
        return {
            "by_person" if kind == "people" else "by_place": _rows(
                conn,
                f"SELECT name, COUNT(DISTINCT date) AS days, MIN(date) AS first_date, "
                f"MAX(date) AS last_date FROM {table}{where_sql} "
                f"GROUP BY name COLLATE NOCASE ORDER BY days DESC, name LIMIT ?",
                [*params, TOP_GROUPS],
            )
        }
    if kind == "family":
        return {
            "by_person_and_category": _rows(
                conn,
                f"SELECT person, category, COUNT(*) AS times, COUNT(DISTINCT date) AS days, "
                f"SUM(minutes) AS total_minutes FROM {table}{where_sql} "
                f"GROUP BY person COLLATE NOCASE, category ORDER BY person, times DESC",
                params,
            ),
            "top_items": _rows(
                conn,
                f"SELECT person, category, lower(text) AS item, COUNT(*) AS times, "
                f"COUNT(DISTINCT date) AS days FROM {table}{where_sql} "
                f"GROUP BY person COLLATE NOCASE, category, lower(text) "
                f"ORDER BY times DESC, person, item LIMIT ?",
                [*params, TOP_GROUPS],
            ),
        }
    if kind == "mood":
        stats = conn.execute(
            f"SELECT ROUND(AVG(mood_score), 2) AS average_score, MIN(mood_score) AS min_score, "
            f"MAX(mood_score) AS max_score, COUNT(mood_score) AS days_with_score "
            f"FROM {table}{where_sql}",
            params,
        ).fetchone()
        return {
            **dict(stats),
            "by_mood": _rows(
                conn,
                f"SELECT lower(mood) AS mood, COUNT(*) AS days FROM {table}{where_sql} "
                f"{'AND' if where_sql else 'WHERE'} mood IS NOT NULL "
                f"GROUP BY lower(mood) ORDER BY days DESC, mood LIMIT ?",
                [*params, TOP_GROUPS],
            ),
        }
    return {}
