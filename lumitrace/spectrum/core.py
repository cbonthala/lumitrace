"""The indexer: keeps the SQLite index in step with the day files in storage.

* :meth:`Indexer.sync` asks storage for changes since ``meta.sync_token`` and (re)indexes changed
  day files, removes deleted ones, and refreshes edit signals when a generated snapshot changes.
* :meth:`Indexer.index_paths` does the same for an explicit list of paths (indexer nudges).
* :meth:`Indexer.rebuild` empties the derived tables (keeping ``feedback`` and ``edit_signals``)
  and re-indexes everything, also after an embedding model or dimension change.
* :meth:`Indexer.backup` copies the index to ``_system/index-backup/``.

Only canonical day files (``YYYY/MM/YYYY-MM-DD/YYYY-MM-DD.md``) are indexed. Audio, photos,
other files and everything under ``_system/`` are never downloaded; generated snapshots under
``_system/generated/`` are read only to compute edit signals.

Each day file is written in one transaction (files row, days and fact rows, passages and vectors,
edit signals), so the MCP server always sees either the old or the new version of a day.
Logging names paths and dates only, never journal or transcript text.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
import sqlite3
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lumitrace.config import Settings
from lumitrace.embeddings import embed_texts
from lumitrace.frames.dayfile import (
    DayFile,
    DayFileParseError,
    classify_path,
    day_file_path,
    generated_snapshot_path,
    parse,
    parse_day_file_path,
)
from lumitrace.frames.storage import get_storage
from lumitrace.frames.storage.base import (
    Change,
    FileInfo,
    InvalidPathError,
    Storage,
    normalize_path,
)
from lumitrace.index.schema import (
    META_EMBEDDING_MODEL,
    META_LAST_REBUILD_AT,
    META_LAST_SYNC_AT,
    META_SCHEMA_VERSION,
    META_SYNC_TOKEN,
    SCHEMA_VERSION,
    EmbeddingDimensionMismatch,
    connect,
    create_schema,
    get_meta,
    load_sqlite_vec,
    reset_derived,
    serialize_embedding,
    set_meta,
)
from lumitrace.spectrum.backup import backup_index
from lumitrace.spectrum.edits import store_edit_signals
from lumitrace.spectrum.passages import Passage, build_passages

log = logging.getLogger(__name__)

META_RETRY_PATHS = "indexer_retry_paths"
"""JSON list of paths that failed with a transient error; retried on the next sync."""
META_LAST_BACKUP_AT = "last_backup_at"
META_LAST_FULL_SCAN_AT = "last_full_scan_at"

FULL_SCAN_INTERVAL = dt.timedelta(hours=24)
"""How often ``run`` lists every file to catch changes the change feed missed."""
FILES_PER_EMBED_BATCH = 16
"""Day files prepared together so their new passages share embedding API calls."""

Embedder = Callable[[Sequence[str]], list[list[float]]]

_SNAPSHOT_RE = re.compile(r"^_system/generated/\d{4}/\d{2}/(\d{4}-\d{2}-\d{2})\.md$")


def snapshot_date(path: str) -> dt.date | None:
    """The date if ``path`` is a generated snapshot (``_system/generated/YYYY/MM/DATE.md``)."""
    m = _SNAPSHOT_RE.match(path)
    if not m:
        return None
    try:
        day = dt.date.fromisoformat(m.group(1))
    except ValueError:
        return None
    return day if generated_snapshot_path(day) == path else None


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(dt.UTC)
    return value.isoformat()


@dataclass
class SyncResult:
    kind: str
    """``sync`` | ``full-scan`` | ``rebuild`` | ``paths``"""
    indexed: int = 0
    skipped: int = 0
    deleted: int = 0
    edit_signals: int = 0
    malformed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    seconds: float = 0.0

    def summary(self) -> dict[str, Any]:
        """Counts and storage paths only (safe to log and to return from ``/health``)."""
        return {
            "kind": self.kind,
            "indexed": self.indexed,
            "skipped": self.skipped,
            "deleted": self.deleted,
            "edit_signals": self.edit_signals,
            "malformed": list(self.malformed),
            "failed": list(self.failed),
            "seconds": round(self.seconds, 3),
        }


@dataclass
class _Prepared:
    path: str
    date: dt.date
    content_hash: str
    size: int
    modified_at: str | None
    day: DayFile | None
    """``None`` when the file could not be parsed (recorded so it is not re-read until it
    changes; the day keeps its last good index)."""
    passages: list[Passage] = field(default_factory=list)
    snapshot: DayFile | None = None
    vectors: dict[str, bytes] = field(default_factory=dict)


def _open_unchecked(path: Path) -> sqlite3.Connection:
    """Open an existing index without the dimension check (only to rebuild it)."""
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    load_sqlite_vec(conn)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def open_index(settings: Settings) -> tuple[sqlite3.Connection, str | None]:
    """Open the index. Returns ``(conn, reason)`` where ``reason`` says why the index must be
    rebuilt before use (embedding model or dimension changed, or an older schema version), or
    ``None``."""
    model = settings.embedding_model
    try:
        conn = connect(settings.index_path, settings.embedding_dimension, embedding_model=model)
    except EmbeddingDimensionMismatch as exc:
        return _open_unchecked(Path(settings.index_path)), str(exc)
    stored = get_meta(conn, META_EMBEDDING_MODEL)
    if stored is None:
        with conn:
            set_meta(conn, META_EMBEDDING_MODEL, model)
    elif stored != model:
        return conn, f"index was built with embedding model {stored!r}, settings say {model!r}"
    version = get_meta(conn, META_SCHEMA_VERSION)
    if version != str(SCHEMA_VERSION):
        return conn, f"index has schema version {version}, Lumitrace now uses {SCHEMA_VERSION}"
    return conn, None


class Indexer:
    def __init__(
        self,
        settings: Settings,
        storage: Storage | None = None,
        *,
        embed: Embedder | None = None,
    ) -> None:
        self.settings = settings
        self.storage = storage if storage is not None else get_storage(settings)
        self._embed: Embedder = embed or (lambda texts: embed_texts(texts, settings))
        self.conn, self.rebuild_reason = open_index(settings)

    def close(self) -> None:
        self.conn.close()

    # --- Public operations -------------------------------------------------------------------

    def sync(self, *, full: bool = False) -> SyncResult:
        """Index what changed since the stored sync token (``full``: list every file and also
        drop index entries for day files that no longer exist)."""
        if self.rebuild_reason:
            log.warning("rebuilding the index: %s", self.rebuild_reason)
            return self.rebuild()
        started = time.monotonic()
        token = None if full else get_meta(self.conn, META_SYNC_TOKEN)
        try:
            changes, new_token = self.storage.list_changes(token)
        except ValueError:
            if token is None:
                raise
            log.warning("storage rejected the sync token; falling back to a full scan")
            token = None
            changes, new_token = self.storage.list_changes(None)
        full_scan = token is None
        result = SyncResult("full-scan" if full_scan else "sync")

        listed = {c.path for c in changes}
        retry = [p for p in self._retry_paths() if p not in listed]
        self._apply([*changes, *self._changes_for_paths(retry, result)], result)
        if full_scan:
            seen = {c.path for c in changes if c.kind == "upserted"}
            self._reconcile(seen, result)

        now = _iso(_now())
        with self.conn:
            set_meta(self.conn, META_SYNC_TOKEN, new_token)
            set_meta(self.conn, META_LAST_SYNC_AT, now)
            set_meta(self.conn, META_RETRY_PATHS, json.dumps(sorted(set(result.failed))))
            if full_scan:
                set_meta(self.conn, META_LAST_FULL_SCAN_AT, now)
        result.seconds = time.monotonic() - started
        self._log_result(result)
        return result

    def index_paths(self, paths: Iterable[str]) -> SyncResult:
        """Index specific paths now (used for nudges). Missing day files are removed from the
        index; paths that are neither day files nor snapshots are ignored."""
        started = time.monotonic()
        result = SyncResult("paths")
        wanted: list[str] = []
        for raw in paths:
            try:
                path = normalize_path(raw)
            except InvalidPathError:
                log.warning("ignoring invalid path in nudge")
                continue
            if path not in wanted:
                wanted.append(path)
        self._apply(self._changes_for_paths(wanted, result), result)
        if result.failed:
            retry = sorted({*self._retry_paths(), *result.failed})
            with self.conn:
                set_meta(self.conn, META_RETRY_PATHS, json.dumps(retry))
        result.seconds = time.monotonic() - started
        if wanted:
            self._log_result(result)
        return result

    def rebuild(self) -> SyncResult:
        """Empty the derived tables (keeping feedback and edit signals) and index everything."""
        started = time.monotonic()
        dim, model = self.settings.embedding_dimension, self.settings.embedding_model
        log.info("rebuild: clearing derived tables (model %s, dimension %d)", model, dim)
        reset_derived(self.conn, embedding_dimension=dim, embedding_model=model)
        create_schema(self.conn, dim, embedding_model=model)
        with self.conn:
            self.conn.execute(
                "DELETE FROM meta WHERE key IN (?, ?)", (META_RETRY_PATHS, META_LAST_FULL_SCAN_AT)
            )
            set_meta(self.conn, META_SCHEMA_VERSION, str(SCHEMA_VERSION))
        self.rebuild_reason = None
        result = self.sync(full=True)
        result.kind = "rebuild"
        result.seconds = time.monotonic() - started
        with self.conn:
            set_meta(self.conn, META_LAST_REBUILD_AT, _iso(_now()))
        return result

    def backup(self) -> FileInfo:
        info = backup_index(self.conn, self.storage)
        with self.conn:
            set_meta(self.conn, META_LAST_BACKUP_AT, _iso(_now()))
        log.info("index backed up to %s (%d bytes)", info.path, info.size)
        return info

    def backup_due(self, now: dt.datetime | None = None) -> bool:
        hours = self.settings.indexer_backup_interval_hours
        if hours <= 0:
            return False
        return self._older_than(META_LAST_BACKUP_AT, dt.timedelta(hours=hours), now)

    def full_scan_due(self, now: dt.datetime | None = None) -> bool:
        return self._older_than(META_LAST_FULL_SCAN_AT, FULL_SCAN_INTERVAL, now)

    # --- Change handling ---------------------------------------------------------------------

    def _apply(self, changes: Sequence[Change], result: SyncResult) -> None:
        upserts: list[Change] = []
        snapshot_dates: set[dt.date] = set()
        for change in changes:
            if classify_path(change.path) == "day":
                if change.kind == "deleted":
                    self._delete_day(change.path, result)
                else:
                    upserts.append(change)
            elif change.kind == "upserted" and (d := snapshot_date(change.path)) is not None:
                snapshot_dates.add(d)
        compared = self._upsert_days(upserts, result)
        for day in sorted(snapshot_dates - compared):
            self._refresh_edit_signals(day, result)

    def _changes_for_paths(self, paths: Iterable[str], result: SyncResult) -> list[Change]:
        changes: list[Change] = []
        for path in paths:
            if classify_path(path) != "day" and snapshot_date(path) is None:
                continue
            try:
                info = self.storage.stat(path)
            except FileNotFoundError:
                changes.append(Change(path, "deleted"))
            except Exception as exc:
                self._fail(path, exc, result)
            else:
                changes.append(Change(path, "upserted", info.modified))
        return changes

    def _upsert_days(self, changes: Sequence[Change], result: SyncResult) -> set[dt.date]:
        """Index changed day files; returns the dates whose edit signals were refreshed."""
        compared: set[dt.date] = set()
        for start in range(0, len(changes), FILES_PER_EMBED_BATCH):
            prepared: list[_Prepared] = []
            for change in changes[start : start + FILES_PER_EMBED_BATCH]:
                try:
                    item = self._prepare(change)
                except FileNotFoundError:
                    self._delete_day(change.path, result)
                    continue
                except Exception as exc:
                    self._fail(change.path, exc, result)
                    continue
                if item is None:
                    result.skipped += 1
                else:
                    prepared.append(item)
            try:
                self._attach_vectors(prepared)
            except Exception as exc:
                for item in prepared:
                    self._fail(item.path, exc, result)
                continue
            for item in prepared:
                try:
                    added = self._write(item)
                except Exception as exc:
                    self._fail(item.path, exc, result)
                    continue
                if item.day is None:
                    result.malformed.append(item.path)
                    continue
                result.indexed += 1
                result.edit_signals += added
                if item.snapshot is not None:
                    compared.add(item.date)
        return compared

    def _prepare(self, change: Change) -> _Prepared | None:
        """Read and parse a day file; ``None`` if it is unchanged since it was last indexed."""
        path = change.path
        day_date = parse_day_file_path(path)
        assert day_date is not None
        modified = _iso(change.modified)
        row = self.conn.execute(
            "SELECT content_hash, modified_at FROM files WHERE path = ?", (path,)
        ).fetchone()
        if row is not None and modified is not None and row["modified_at"] == modified:
            return None
        data = self.storage.read_bytes(path)
        content_hash = hashlib.sha256(data).hexdigest()
        if row is not None and row["content_hash"] == content_hash:
            if modified is not None:
                with self.conn:
                    self.conn.execute(
                        "UPDATE files SET modified_at = ? WHERE path = ?", (modified, path)
                    )
            return None
        item = _Prepared(path, day_date, content_hash, len(data), modified, day=None)
        try:
            item.day = self._parse(data.decode("utf-8"), day_date, path)
        except (UnicodeDecodeError, DayFileParseError) as exc:
            log.warning(
                "%s is not a valid day file (%s); search keeps its last good version",
                path,
                type(exc).__name__,
            )
            log.debug("%s parse error: %s", path, exc)
            return item
        item.passages = build_passages(item.day)
        item.snapshot = self._read_snapshot(day_date)
        return item

    @staticmethod
    def _parse(text: str, day_date: dt.date, path: str) -> DayFile:
        day = parse(text, fallback_date=day_date)
        if day.date != day_date:
            log.warning("%s: front matter date differs from its folder; using the folder", path)
            day = day.model_copy(update={"meta": day.meta.model_copy(update={"date": day_date})})
        return day

    def _read_snapshot(self, day_date: dt.date) -> DayFile | None:
        path = generated_snapshot_path(day_date)
        try:
            text = self.storage.read_text(path)
        except FileNotFoundError:
            return None
        try:
            return self._parse(text, day_date, path)
        except DayFileParseError as exc:
            log.warning(
                "%s is not a valid snapshot (%s); no edit signals", path, type(exc).__name__
            )
            return None

    def _attach_vectors(self, prepared: Sequence[_Prepared]) -> None:
        """Reuse stored vectors for unchanged passages; embed the rest in one call."""
        missing: dict[str, str] = {}
        for item in prepared:
            if item.day is None:
                continue
            wanted = {p.text_hash for p in item.passages}
            rows = self.conn.execute(
                "SELECT p.text_hash, v.embedding FROM passages p"
                " JOIN passages_vec v ON v.rowid = p.id WHERE p.path = ?",
                (item.path,),
            ).fetchall()
            item.vectors = {r[0]: bytes(r[1]) for r in rows if r[0] in wanted}
            for p in item.passages:
                if p.text_hash not in item.vectors:
                    missing.setdefault(p.text_hash, p.embed_input)
        if not missing:
            return
        keys = list(missing)
        vectors = self._embed([missing[k] for k in keys])
        if len(vectors) != len(keys):
            raise ValueError(f"embedder returned {len(vectors)} vectors for {len(keys)} texts")
        blobs = {k: serialize_embedding(v) for k, v in zip(keys, vectors, strict=True)}
        for item in prepared:
            for p in item.passages:
                if p.text_hash in blobs:
                    item.vectors.setdefault(p.text_hash, blobs[p.text_hash])

    def _write(self, item: _Prepared) -> int:
        """Write one day file in a single transaction; returns new edit signals."""
        now = _iso(_now())
        assert now is not None
        with self.conn:
            self.conn.execute(
                "INSERT INTO files(path, kind, date, content_hash, size, modified_at, indexed_at)"
                " VALUES (?, 'day', ?, ?, ?, ?, ?)"
                " ON CONFLICT(path) DO UPDATE SET kind = excluded.kind, date = excluded.date,"
                " content_hash = excluded.content_hash, size = excluded.size,"
                " modified_at = excluded.modified_at, indexed_at = excluded.indexed_at",
                (
                    item.path,
                    item.date.isoformat(),
                    item.content_hash,
                    item.size,
                    item.modified_at,
                    now,
                ),
            )
            if item.day is None:
                return 0
            self.conn.execute("DELETE FROM days WHERE date = ?", (item.date.isoformat(),))
            _insert_day(self.conn, item.path, item.day)
            self.conn.execute("DELETE FROM passages WHERE path = ?", (item.path,))
            for p in item.passages:
                cur = self.conn.execute(
                    "INSERT INTO passages(path, date, section, heading, capture_id, ordinal,"
                    " text, text_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item.path,
                        item.date.isoformat(),
                        p.section,
                        p.heading,
                        p.capture_id,
                        p.ordinal,
                        p.text,
                        p.text_hash,
                    ),
                )
                self.conn.execute(
                    "INSERT INTO passages_vec(rowid, embedding) VALUES (?, ?)",
                    (cur.lastrowid, item.vectors[p.text_hash]),
                )
            if item.snapshot is None:
                return 0
            return store_edit_signals(
                self.conn, path=item.path, live=item.day, snapshot=item.snapshot, detected_at=now
            )

    def _refresh_edit_signals(self, day_date: dt.date, result: SyncResult) -> None:
        """A snapshot changed but its day file did not: compare them again."""
        path = day_file_path(day_date)
        indexed = self.conn.execute(
            "SELECT 1 FROM days WHERE date = ?", (day_date.isoformat(),)
        ).fetchone()
        if indexed is None:
            return
        try:
            live = self._parse(self.storage.read_text(path), day_date, path)
            snapshot = self._read_snapshot(day_date)
        except FileNotFoundError:
            return
        except Exception as exc:
            log.warning("%s: could not compare with its snapshot (%s)", path, type(exc).__name__)
            return
        if snapshot is None:
            return
        now = _iso(_now())
        assert now is not None
        with self.conn:
            result.edit_signals += store_edit_signals(
                self.conn, path=path, live=live, snapshot=snapshot, detected_at=now
            )

    def _delete_day(self, path: str, result: SyncResult) -> None:
        with self.conn:
            days = self.conn.execute("DELETE FROM days WHERE path = ?", (path,)).rowcount
            files = self.conn.execute("DELETE FROM files WHERE path = ?", (path,)).rowcount
        if days or files:
            result.deleted += 1

    def _reconcile(self, seen: set[str], result: SyncResult) -> None:
        """After a full listing, drop indexed day files that no longer exist."""
        known = [r[0] for r in self.conn.execute("SELECT path FROM files WHERE kind = 'day'")]
        for path in known:
            if path not in seen:
                self._delete_day(path, result)
        orphans = self.conn.execute(
            "SELECT path FROM days WHERE path NOT IN (SELECT path FROM files)"
        ).fetchall()
        for row in orphans:
            self._delete_day(row[0], result)

    # --- Helpers -----------------------------------------------------------------------------

    def _fail(self, path: str, exc: BaseException, result: SyncResult) -> None:
        log.warning("%s: indexing failed (%s); will retry", path, type(exc).__name__)
        log.debug("%s: %s", path, exc, exc_info=exc)
        if path not in result.failed:
            result.failed.append(path)

    def _retry_paths(self) -> list[str]:
        raw = get_meta(self.conn, META_RETRY_PATHS)
        if not raw:
            return []
        try:
            paths = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return [p for p in paths if isinstance(p, str)]

    def _older_than(self, key: str, interval: dt.timedelta, now: dt.datetime | None) -> bool:
        last = get_meta(self.conn, key)
        if not last:
            return True
        try:
            last_at = dt.datetime.fromisoformat(last)
        except ValueError:
            return True
        return (now or _now()) - last_at >= interval

    @staticmethod
    def _log_result(result: SyncResult) -> None:
        level = logging.WARNING if result.failed or result.malformed else logging.INFO
        log.log(
            level,
            "%s: %d indexed, %d unchanged, %d deleted, %d edit signals, %d malformed, "
            "%d failed (%.1fs)",
            result.kind,
            result.indexed,
            result.skipped,
            result.deleted,
            result.edit_signals,
            len(result.malformed),
            len(result.failed),
            result.seconds,
        )


def _insert_day(conn: sqlite3.Connection, path: str, day: DayFile) -> None:
    m = day.meta
    f = day.facts
    date = day.date.isoformat()
    conn.execute(
        "INSERT INTO days(date, path, title, mood, mood_score, city, weather, audio_json,"
        " photos_json, prompt_version, models_used_json, generated_at, generated_hash,"
        " user_edited, capture_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            date,
            path,
            day.title,
            f.mood,
            f.mood_score,
            f.city,
            f.weather,
            json.dumps(m.audio, ensure_ascii=False),
            json.dumps(m.photos, ensure_ascii=False),
            m.prompt_version,
            json.dumps(m.models_used, ensure_ascii=False, sort_keys=True),
            _iso(m.generated_at),
            m.generated_hash,
            int(day.is_user_edited()),
            len(day.captures),
        ),
    )
    meal_rows = [
        (meal.type.strip().casefold(), item.strip())
        for meal in f.meals
        for item in meal.items
        if meal.type.strip() and item.strip()
    ]
    conn.executemany(
        "INSERT INTO meals(date, meal_type, item, position) VALUES (?, ?, ?, ?)",
        [(date, t, item, pos) for pos, (t, item) in enumerate(meal_rows)],
    )
    activities = [a for a in f.activities if a.kind.strip()]
    conn.executemany(
        "INSERT INTO activities(date, kind, minutes, position) VALUES (?, ?, ?, ?)",
        [(date, a.kind.strip(), a.minutes, pos) for pos, a in enumerate(activities)],
    )
    for table, column, values in (
        ("people", "name", f.people),
        ("places", "name", f.places),
        ("highlights", "text", f.highlights),
    ):
        clean = [v.strip() for v in values if v and v.strip()]
        conn.executemany(
            f"INSERT INTO {table}(date, {column}, position) VALUES (?, ?, ?)",
            [(date, v, pos) for pos, v in enumerate(clean)],
        )
    family_rows: list[tuple[str, str, str, int | None]] = []
    for member in f.family:
        if member.mood:
            family_rows.append((member.name, "mood", member.mood, None))
        for category in ("food", "places"):
            family_rows.extend((member.name, category, v, None) for v in getattr(member, category))
        family_rows.extend(
            (member.name, "activities", a.kind, a.minutes) for a in member.activities
        )
        for category in ("moments", "health", "school"):
            family_rows.extend((member.name, category, v, None) for v in getattr(member, category))
    conn.executemany(
        "INSERT INTO family_facts(date, person, category, text, minutes, position)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [(date, *row, pos) for pos, row in enumerate(family_rows)],
    )
