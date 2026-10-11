"""Copy the SQLite index to storage (``_system/index-backup/bookshelf.sqlite``).

Uses SQLite's online backup API, so the copy is consistent even while the MCP server writes
feedback. The copy is switched to rollback-journal mode so it is one self-contained file.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from bookshelf.books.dayfile import system_path
from bookshelf.books.storage.base import FileInfo, Storage

BACKUP_PATH = system_path("index-backup", "bookshelf.sqlite")


def backup_index(conn: sqlite3.Connection, storage: Storage, path: str = BACKUP_PATH) -> FileInfo:
    with tempfile.TemporaryDirectory(prefix="bookshelf-backup-") as tmp:
        target = Path(tmp) / "bookshelf.sqlite"
        dest = sqlite3.connect(target)
        try:
            conn.backup(dest)
            dest.execute("PRAGMA journal_mode = DELETE")
        finally:
            dest.close()
        return storage.write_bytes(path, target.read_bytes(), "application/vnd.sqlite3")
