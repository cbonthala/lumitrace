"""Date arguments accepted by the MCP tools.

The AI client turns phrases like "last Tuesday" into dates; the tools only accept explicit
formats (plus ``today`` / ``yesterday``, resolved in the owner's timezone with the 4 a.m.
rollover, because the client may not know the owner's timezone).
"""

from __future__ import annotations

import datetime as dt
import re

from bookshelf.books.dayfile import entry_date
from bookshelf.config import Settings

DATE_HELP = "YYYY-MM-DD (e.g. 2026-10-10), or 'today' / 'yesterday'"
MONTH_DAY_HELP = "MM-DD (e.g. 10-10)"

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_DAY_RE = re.compile(r"^(?:--)?(\d{1,2})-(\d{1,2})$")


class DateArgumentError(ValueError):
    """A tool received a date it cannot read; the message is shown to the AI client."""


def today(settings: Settings) -> dt.date:
    """The owner's current journal day (before the rollover hour it is still yesterday)."""
    return entry_date(dt.datetime.now(settings.tz), settings.tz, settings.day_rollover_hour)


def parse_date(value: str, settings: Settings, *, name: str = "date") -> dt.date:
    text = value.strip().lower()
    if text == "today":
        return today(settings)
    if text == "yesterday":
        return today(settings) - dt.timedelta(days=1)
    if _ISO_DATE_RE.match(text):
        try:
            return dt.date.fromisoformat(text)
        except ValueError:
            pass
    raise DateArgumentError(f"{name} must be {DATE_HELP}; got {value!r}")


def parse_optional_date(value: str | None, settings: Settings, *, name: str) -> dt.date | None:
    if value is None or not value.strip():
        return None
    return parse_date(value, settings, name=name)


def parse_range(
    from_date: str | None, to_date: str | None, settings: Settings
) -> tuple[dt.date | None, dt.date | None]:
    """Inclusive date range; either end may be open."""
    start = parse_optional_date(from_date, settings, name="from_date")
    end = parse_optional_date(to_date, settings, name="to_date")
    if start and end and start > end:
        raise DateArgumentError(
            f"from_date ({start.isoformat()}) is after to_date ({end.isoformat()})"
        )
    return start, end


def parse_month_day(value: str) -> tuple[int, int] | None:
    """``(month, day)`` for ``MM-DD`` (or ``--MM-DD``), else ``None``."""
    m = _MONTH_DAY_RE.match(value.strip())
    if not m:
        return None
    month, day = int(m.group(1)), int(m.group(2))
    try:
        dt.date(2000, month, day)  # leap year, so 02-29 is accepted
    except ValueError as exc:
        raise DateArgumentError(f"invalid month-day {value!r}; use {MONTH_DAY_HELP}") from exc
    return month, day
