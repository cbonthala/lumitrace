"""Opening the SQLite index for the MCP tools.

Queries use a read-only connection opened per tool call, so the indexer can rebuild or replace
the file at any time. Only the ``feedback`` tool opens it for writing.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from lumitrace.config import Settings
from lumitrace.index.schema import EmbeddingDimensionMismatch, connect

logger = logging.getLogger(__name__)

INDEX_MISSING_NOTE = (
    "The Lumitrace index has not been built yet, so there is nothing to search. "
    "Tell the owner no entries were found and that the indexer may still be running."
)
INDEX_EMPTY_NOTE = "The Lumitrace index is empty: no journal entries have been indexed yet."


class IndexUnavailableError(RuntimeError):
    """The index exists but cannot be used as configured (message is shown to the AI client)."""


@contextmanager
def open_index(settings: Settings) -> Iterator[sqlite3.Connection | None]:
    """Yield a read-only connection, or ``None`` if the index is missing or has no schema."""
    path = Path(settings.index_path)
    if not path.is_file():
        yield None
        return
    try:
        conn = connect(path, settings.embedding_dimension, read_only=True)
    except EmbeddingDimensionMismatch as exc:
        raise IndexUnavailableError(
            f"{exc}. The owner needs to rebuild the index (docs/runbook.md)."
        ) from exc
    except sqlite3.DatabaseError:
        logger.warning("cannot open index at %s", path, exc_info=True)
        yield None
        return
    try:
        yield conn if has_table(conn, "days") and has_table(conn, "passages") else None
    finally:
        conn.close()


@contextmanager
def open_index_for_write(settings: Settings) -> Iterator[sqlite3.Connection]:
    """Writable connection (creates the index file and schema if needed). Feedback only."""
    conn = connect(
        settings.index_path,
        settings.embedding_dimension,
        embedding_model=settings.embedding_model,
    )
    try:
        yield conn
    finally:
        conn.close()


def has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?", (name,)
    ).fetchone()
    return row is not None


def is_empty(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM days LIMIT 1").fetchone() is None and (
        conn.execute("SELECT 1 FROM passages LIMIT 1").fetchone() is None
    )
