"""SQLite index contract: tables, virtual tables and :func:`connect`.

The index is disposable (rebuilt from the Markdown files) *except* for ``feedback`` and
``edit_signals``, which hold signals that :func:`reset_derived` preserves. Full description:
``docs/index-schema.md``. Bump :data:`SCHEMA_VERSION` and document a migration for any change.

Writers: the indexer (everything derived + ``edit_signals``) and the MCP server (``feedback``
only). Both use :func:`connect`, which enables WAL and a busy timeout so they can share the file.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path

import sqlite_vec

SCHEMA_VERSION = 4

META_SCHEMA_VERSION = "schema_version"
META_EMBEDDING_MODEL = "embedding_model"
META_EMBEDDING_DIMENSION = "embedding_dimension"
META_SYNC_TOKEN = "sync_token"
META_LAST_SYNC_AT = "last_sync_at"
META_LAST_REBUILD_AT = "last_rebuild_at"

DERIVED_TABLES: tuple[str, ...] = (
    "passages",
    "passages_fts",
    "passages_vec",
    "meals",
    "activities",
    "people",
    "places",
    "family_facts",
    "highlights",
    "content_facts",
    "days",
    "files",
)
"""Tables cleared by :func:`reset_derived` (children before parents)."""

FACT_TABLES: tuple[str, ...] = (
    "meals",
    "activities",
    "people",
    "places",
    "family_facts",
    "highlights",
    "content_facts",
    "days",
)
"""Derived tables that :func:`reset_derived` drops and recreates (children before ``days``), so an
index made by an older schema version gets the current columns."""

PRESERVED_TABLES: tuple[str, ...] = ("feedback", "edit_signals")


class EmbeddingDimensionMismatch(RuntimeError):
    """The index was built with a different embedding dimension; rebuild it."""


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Every storage file the indexer has seen (day files, audio, photos, _system files...).
CREATE TABLE IF NOT EXISTS files (
    path          TEXT PRIMARY KEY,        -- storage path relative to the Lumitrace root
    kind          TEXT NOT NULL,           -- dayfile.classify_path(): day|audio|photo|system|other
    date          TEXT,                    -- YYYY-MM-DD of the day folder, if any
    content_hash  TEXT NOT NULL,           -- sha256 hex of the file bytes
    size          INTEGER,
    modified_at   TEXT,                    -- ISO-8601 UTC from storage
    indexed_at    TEXT NOT NULL            -- ISO-8601 UTC
);
CREATE INDEX IF NOT EXISTS files_date ON files(date);

-- One row per day file: scalar facts ("At a glance") and provenance (front matter).
CREATE TABLE IF NOT EXISTS days (
    date            TEXT PRIMARY KEY,      -- YYYY-MM-DD
    path            TEXT NOT NULL,
    title           TEXT,
    mood            TEXT,
    mood_score      INTEGER,               -- 1..5 or NULL
    city            TEXT,
    weather         TEXT,
    remember        TEXT,                  -- the one moment worth keeping (Highlight)
    audio_json      TEXT NOT NULL DEFAULT '[]',   -- JSON list of file names in the day folder
    photos_json     TEXT NOT NULL DEFAULT '[]',
    prompt_version  TEXT,
    models_used_json TEXT NOT NULL DEFAULT '{}',
    generated_at    TEXT,
    generated_hash  TEXT,
    user_edited     INTEGER NOT NULL DEFAULT 0,   -- DayFile.is_user_edited()
    capture_count   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meals (
    id         INTEGER PRIMARY KEY,
    date       TEXT NOT NULL REFERENCES days(date) ON DELETE CASCADE,
    person     TEXT NOT NULL DEFAULT '',   -- family member; '' = not named (the Everyone block)
    meal_type  TEXT NOT NULL,              -- breakfast|lunch|dinner|snacks
    item       TEXT NOT NULL,              -- one row per item
    position   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS meals_date ON meals(date);

CREATE TABLE IF NOT EXISTS activities (
    id        INTEGER PRIMARY KEY,
    date      TEXT NOT NULL REFERENCES days(date) ON DELETE CASCADE,
    kind      TEXT NOT NULL,
    minutes   INTEGER,
    position  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS activities_date ON activities(date);

CREATE TABLE IF NOT EXISTS people (
    id        INTEGER PRIMARY KEY,
    date      TEXT NOT NULL REFERENCES days(date) ON DELETE CASCADE,
    name      TEXT NOT NULL,
    position  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS people_date ON people(date);
CREATE INDEX IF NOT EXISTS people_name ON people(name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS places (
    id        INTEGER PRIMARY KEY,
    date      TEXT NOT NULL REFERENCES days(date) ON DELETE CASCADE,
    name      TEXT NOT NULL,
    position  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS places_date ON places(date);
CREATE INDEX IF NOT EXISTS places_name ON places(name COLLATE NOCASE);

-- One row per item in a person's block: person "Leo", category "feelings", text "tired".
-- Memories shared by everyone have person "Together" and category "moments".
CREATE TABLE IF NOT EXISTS family_facts (
    id        INTEGER PRIMARY KEY,
    date      TEXT NOT NULL REFERENCES days(date) ON DELETE CASCADE,
    person    TEXT NOT NULL,
    category  TEXT NOT NULL,               -- feelings|health|moments
    text      TEXT NOT NULL,               -- the item
    minutes   INTEGER,                     -- unused (kept for schema 2 compatibility)
    position  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS family_facts_date ON family_facts(date);
CREATE INDEX IF NOT EXISTS family_facts_person ON family_facts(person COLLATE NOCASE, category);

CREATE TABLE IF NOT EXISTS highlights (
    id        INTEGER PRIMARY KEY,
    date      TEXT NOT NULL REFERENCES days(date) ON DELETE CASCADE,
    text      TEXT NOT NULL,
    position  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS highlights_date ON highlights(date);

-- Canonical Format 6 values, flattened into logical rows. Legacy days are projected into
-- DayContent before insertion, so these query surfaces work across both file formats.
CREATE TABLE IF NOT EXISTS content_facts (
    id           INTEGER PRIMARY KEY,
    date         TEXT NOT NULL REFERENCES days(date) ON DELETE CASCADE,
    scope        TEXT NOT NULL,             -- timeline|family|pregnancy|tags
    person       TEXT,                      -- family tracker owner, otherwise NULL
    category     TEXT NOT NULL,             -- context|food|health_fitness|...
    field        TEXT NOT NULL,             -- exact field within the category
    text         TEXT,                      -- item/description/name when textual
    number       REAL,                      -- rating score or exercise minutes
    status       TEXT,                      -- meal status when applicable
    details_json TEXT,                      -- complete structured logical item, when useful
    position     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS content_facts_date ON content_facts(date);
CREATE INDEX IF NOT EXISTS content_facts_scope
    ON content_facts(scope, person COLLATE NOCASE, category, field);

-- Searchable chunks of text. FTS and vector rows share passages.id as their rowid.
CREATE TABLE IF NOT EXISTS passages (
    id          INTEGER PRIMARY KEY,
    path        TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
    date        TEXT,                      -- YYYY-MM-DD, NULL for non-day files
    section     TEXT NOT NULL,             -- title|content|journal|notes|transcript|facts
    heading     TEXT,                      -- nearest Markdown heading, if any
    capture_id  TEXT,                      -- Capture.id for transcript passages
    ordinal     INTEGER NOT NULL DEFAULT 0, -- order within (path, section)
    text        TEXT NOT NULL,
    text_hash   TEXT NOT NULL              -- sha256 hex of text (reuse embeddings when unchanged)
);
CREATE INDEX IF NOT EXISTS passages_path ON passages(path);
CREATE INDEX IF NOT EXISTS passages_date ON passages(date);

CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(
    text,
    section UNINDEXED,
    date UNINDEXED,
    content='passages',
    content_rowid='id',
    tokenize='porter unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS passages_ai AFTER INSERT ON passages BEGIN
    INSERT INTO passages_fts(rowid, text, section, date)
    VALUES (new.id, new.text, new.section, new.date);
END;
CREATE TRIGGER IF NOT EXISTS passages_ad AFTER DELETE ON passages BEGIN
    INSERT INTO passages_fts(passages_fts, rowid, text, section, date)
    VALUES ('delete', old.id, old.text, old.section, old.date);
    DELETE FROM passages_vec WHERE rowid = old.id;
END;
CREATE TRIGGER IF NOT EXISTS passages_au AFTER UPDATE ON passages BEGIN
    INSERT INTO passages_fts(passages_fts, rowid, text, section, date)
    VALUES ('delete', old.id, old.text, old.section, old.date);
    INSERT INTO passages_fts(rowid, text, section, date)
    VALUES (new.id, new.text, new.section, new.date);
END;

-- Owner edits: differences between what the system wrote and the current file.
CREATE TABLE IF NOT EXISTS edit_signals (
    id              INTEGER PRIMARY KEY,
    date            TEXT NOT NULL,
    path            TEXT NOT NULL,
    detected_at     TEXT NOT NULL,         -- ISO-8601 UTC
    section         TEXT NOT NULL,         -- content|facts|title|journal|notes|transcript
    field           TEXT,                  -- e.g. "timeline" for content, "places" for facts
    before          TEXT,                  -- system version (JSON for facts, text otherwise)
    after           TEXT,                  -- owner's version
    diff            TEXT,                  -- unified diff, for text sections
    prompt_version  TEXT,
    models_used_json TEXT,
    signal_hash     TEXT NOT NULL UNIQUE   -- sha256(date|section|field|before|after); dedupe
);
CREATE INDEX IF NOT EXISTS edit_signals_date ON edit_signals(date);

-- Feedback from the MCP `feedback` tool.
CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY,
    created_at  TEXT NOT NULL,             -- ISO-8601 UTC
    rating      TEXT NOT NULL,             -- wrong|incomplete|good|other
    question    TEXT,
    answer      TEXT,
    comment     TEXT,
    dates_json  TEXT NOT NULL DEFAULT '[]', -- JSON list of YYYY-MM-DD the answer cited
    tool        TEXT,                      -- MCP tool the feedback is about, if known
    client      TEXT,                      -- AI app name, if known
    storage_path TEXT                      -- copy written under _system/feedback/, if any
);
"""

_VEC_SQL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS passages_vec USING vec0("
    "embedding float[{dim}] distance_metric=cosine)"
)


def load_sqlite_vec(conn: sqlite3.Connection) -> None:
    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)


def connect(
    path: str | Path,
    embedding_dimension: int,
    *,
    embedding_model: str | None = None,
    read_only: bool = False,
) -> sqlite3.Connection:
    """Open the index, load sqlite-vec and create the schema if needed.

    * ``path`` may be ``":memory:"`` for tests. Parent folders are created.
    * Rows come back as :class:`sqlite3.Row`. Foreign keys are on; WAL mode; 5 s busy timeout.
    * Raises :class:`EmbeddingDimensionMismatch` if an existing index used a different
      dimension. ``embedding_model``, if given, is recorded in ``meta`` on creation.
    * ``read_only`` opens an existing file without creating or migrating anything.
    """
    target = str(path)
    if read_only:
        conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True, check_same_thread=False)
    else:
        if target != ":memory:":
            Path(target).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(target, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    load_sqlite_vec(conn)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    if read_only:
        _check_dimension(conn, embedding_dimension)
        return conn
    if target != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    create_schema(conn, embedding_dimension, embedding_model=embedding_model)
    return conn


def create_schema(
    conn: sqlite3.Connection, embedding_dimension: int, *, embedding_model: str | None = None
) -> None:
    if embedding_dimension <= 0:
        raise ValueError("embedding_dimension must be positive")
    _check_dimension(conn, embedding_dimension)
    with conn:
        conn.execute(_VEC_SQL.format(dim=int(embedding_dimension)))
        conn.executescript("BEGIN;" + _SCHEMA_SQL + "COMMIT;")
        if get_meta(conn, META_SCHEMA_VERSION) is None:
            set_meta(conn, META_SCHEMA_VERSION, str(SCHEMA_VERSION))
            set_meta(conn, META_EMBEDDING_DIMENSION, str(embedding_dimension))
            if embedding_model:
                set_meta(conn, META_EMBEDDING_MODEL, embedding_model)


def _check_dimension(conn: sqlite3.Connection, embedding_dimension: int) -> None:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'"
    ).fetchone()
    if not exists:
        return
    stored = get_meta(conn, META_EMBEDDING_DIMENSION)
    if stored is not None and int(stored) != int(embedding_dimension):
        raise EmbeddingDimensionMismatch(
            f"index uses dimension {stored}, settings say {embedding_dimension}; "
            "rebuild the index (see docs/runbook.md)"
        )


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else row[0]


def set_meta(conn: sqlite3.Connection, key: str, value: str | None) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def reset_derived(
    conn: sqlite3.Connection,
    *,
    embedding_dimension: int | None = None,
    embedding_model: str | None = None,
) -> None:
    """Empty every derived table and the sync token, keeping ``feedback`` and ``edit_signals``.
    The fact tables are dropped and recreated, so they get the current columns.

    Pass ``embedding_dimension`` to recreate the vector table with a new dimension (after
    changing the embedding model).
    """
    with conn:
        for table in DERIVED_TABLES:
            if table == "passages_vec" and embedding_dimension is not None:
                conn.execute("DROP TABLE IF EXISTS passages_vec")
                conn.execute(_VEC_SQL.format(dim=int(embedding_dimension)))
                set_meta(conn, META_EMBEDDING_DIMENSION, str(embedding_dimension))
            elif table == "passages_fts":
                conn.execute("INSERT INTO passages_fts(passages_fts) VALUES ('delete-all')")
            elif table in FACT_TABLES:
                conn.execute(f"DROP TABLE IF EXISTS {table}")
            else:
                conn.execute(f"DELETE FROM {table}")
        if embedding_model is not None:
            set_meta(conn, META_EMBEDDING_MODEL, embedding_model)
        conn.execute("DELETE FROM meta WHERE key = ?", (META_SYNC_TOKEN,))
    conn.executescript("BEGIN;" + _SCHEMA_SQL + "COMMIT;")


def serialize_embedding(vector: Sequence[float]) -> bytes:
    """Encode a vector for ``passages_vec.embedding`` (float32 little-endian)."""
    return sqlite_vec.serialize_float32(list(vector))
