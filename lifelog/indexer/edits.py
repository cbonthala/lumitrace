"""Edit signals: what the owner changed compared with what LifeLog last wrote.

The recording API writes the exact day file it produced to ``generated_snapshot_path(date)``.
The indexer compares the live day file with that snapshot, field by field:

* ``facts``: one comparison per fact field (``field`` = the fact name), JSON values, no diff.
* ``title``, ``journal``, ``notes``: the whole text, with a unified diff.
* ``transcript``: one comparison per capture in the snapshot (``field`` = the capture id).
  Captures that exist only in the live file are new system captures, not edits; a capture
  removed from the live file is an edit with an empty ``after``.

Rules (see ``docs/decisions/0022-edit-signal-baseline-and-supersede.md``):

* Compare only when both files carry the same ``generated_at``; otherwise the snapshot and the
  day file belong to different system writes (for example the indexer read between the API's
  two writes), and a diff would blame the owner for the system's change.
* One row per (date, section, field, before): while the owner keeps editing, the newest version
  replaces the older ones; reverting the edit removes the row. Rows whose ``before`` belongs to an
  older snapshot are never touched, so history survives later system writes and rebuilds.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import Any

from lifelog.dayfile import FACT_FIELDS, DayFile

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FieldComparison:
    section: str
    field: str | None
    before: str
    after: str

    @property
    def changed(self) -> bool:
        return self.before != self.after


def comparable(live: DayFile, snapshot: DayFile) -> bool:
    """True if ``snapshot`` is the system write the live file was edited from."""
    return live.date == snapshot.date and live.meta.generated_at == snapshot.meta.generated_at


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def compare_day(live: DayFile, snapshot: DayFile) -> list[FieldComparison]:
    out: list[FieldComparison] = []
    live_facts = live.meta.facts().model_dump(mode="json")
    snap_facts = snapshot.meta.facts().model_dump(mode="json")
    for name in FACT_FIELDS:
        out.append(FieldComparison("facts", name, _json(snap_facts[name]), _json(live_facts[name])))
    out.append(FieldComparison("title", None, snapshot.title, live.title))
    out.append(FieldComparison("journal", None, snapshot.journal, live.journal))
    out.append(FieldComparison("notes", None, snapshot.notes, live.notes))
    live_text = {c.id: c.text for c in live.captures}
    for capture in snapshot.captures:
        out.append(
            FieldComparison("transcript", capture.id, capture.text, live_text.get(capture.id, ""))
        )
    return out


def text_diff(before: str, after: str) -> str:
    lines = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile="generated",
        tofile="edited",
        n=2,
        lineterm="",
    )
    return "\n".join(lines)


def signal_hash(date: str, section: str, field: str | None, before: str, after: str) -> str:
    raw = "|".join([date, section, field or "", before, after])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def store_edit_signals(
    conn: sqlite3.Connection,
    *,
    path: str,
    live: DayFile,
    snapshot: DayFile,
    detected_at: str,
) -> int:
    """Record the owner's edits; returns the number of new rows. Call inside a transaction."""
    if not comparable(live, snapshot):
        log.debug("%s: snapshot is from a different system write; skipping edit signals", path)
        return 0
    date = live.date.isoformat()
    models_used = _json(snapshot.meta.models_used)
    added = 0
    for cmp in compare_day(live, snapshot):
        key = (date, cmp.section, cmp.field, cmp.before)
        if not cmp.changed:
            conn.execute(
                "DELETE FROM edit_signals"
                " WHERE date = ? AND section = ? AND field IS ? AND before IS ?",
                key,
            )
            continue
        digest = signal_hash(date, cmp.section, cmp.field, cmp.before, cmp.after)
        diff = None if cmp.section == "facts" else text_diff(cmp.before, cmp.after)
        cur = conn.execute(
            "INSERT OR IGNORE INTO edit_signals(date, path, detected_at, section, field, before,"
            " after, diff, prompt_version, models_used_json, signal_hash)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                date,
                path,
                detected_at,
                cmp.section,
                cmp.field,
                cmp.before,
                cmp.after,
                diff,
                snapshot.meta.prompt_version,
                models_used,
                digest,
            ),
        )
        added += max(cur.rowcount, 0)
        conn.execute(
            "DELETE FROM edit_signals WHERE date = ? AND section = ? AND field IS ?"
            " AND before IS ? AND signal_hash <> ?",
            (*key, digest),
        )
    return added
