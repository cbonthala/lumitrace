"""The storage contract every backend implements.

Paths
-----
All paths are *relative to the Bookshelf root folder* and use forward slashes, for example
``2026/10/2026-10-10/2026-10-10.md`` or ``_system/activity/2026/10.jsonl``. The root itself is
``Settings.local_root`` for the local backend and the Drive folder named
``Settings.gdrive_root_folder`` for Google Drive. Use :func:`normalize_path` to validate a path;
backends call it on every input. Hidden entries (any path component starting with ``.``, such as
Obsidian's ``.obsidian/`` folder) are never returned by :meth:`Storage.list` or
:meth:`Storage.list_changes`.

Errors
------
Reading, stat-ing or deleting a missing file raises :class:`FileNotFoundError`. Invalid paths
raise :class:`InvalidPathError` (a ``ValueError``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

ChangeKind = Literal["upserted", "deleted"]


class InvalidPathError(ValueError):
    """Raised for absolute paths, ``..`` segments, empty paths and similar."""


class StorageError(RuntimeError):
    """Backend failure that is not a missing file (network, auth, quota, ...)."""


@dataclass(frozen=True)
class FileInfo:
    path: str
    size: int
    modified: datetime
    """Last modification time, timezone-aware UTC."""
    id: str | None = None
    """Backend-specific identifier (the Drive file id); ``None`` for the local backend."""


@dataclass(frozen=True)
class Change:
    path: str
    kind: ChangeKind
    modified: datetime | None = None
    """Modification time (UTC) for ``upserted``; ``None`` for ``deleted``."""


def normalize_path(path: str, *, allow_root: bool = False) -> str:
    """Validate and canonicalise a storage path (``a//b/`` -> ``a/b``)."""
    if not isinstance(path, str):
        raise InvalidPathError(f"path must be a string, got {type(path).__name__}")
    if "\\" in path or "\x00" in path:
        raise InvalidPathError(f"invalid characters in path: {path!r}")
    if path.startswith("/"):
        raise InvalidPathError(f"path must be relative to the Bookshelf root: {path!r}")
    parts = [p for p in path.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise InvalidPathError(f"'..' is not allowed in paths: {path!r}")
    if not parts and not allow_root:
        raise InvalidPathError("empty path")
    return "/".join(parts)


def is_hidden(path: str) -> bool:
    return any(part.startswith(".") for part in path.split("/") if part)


class Storage(ABC):
    """A file store rooted at the Bookshelf folder. Implementations must be thread-safe."""

    @abstractmethod
    def read_bytes(self, path: str) -> bytes:
        """Return the file's content. Raises ``FileNotFoundError`` if missing."""

    @abstractmethod
    def write_bytes(self, path: str, data: bytes, content_type: str | None = None) -> FileInfo:
        """Create or replace a file, creating parent folders as needed. Atomic per file."""

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        return self.read_bytes(path).decode(encoding)

    def write_text(
        self,
        path: str,
        text: str,
        content_type: str | None = None,
        encoding: str = "utf-8",
    ) -> FileInfo:
        return self.write_bytes(path, text.encode(encoding), content_type or guess_type(path))

    @abstractmethod
    def exists(self, path: str) -> bool:
        """True if a *file* exists at ``path`` (folders return False)."""

    @abstractmethod
    def stat(self, path: str) -> FileInfo:
        """Metadata for a file. Raises ``FileNotFoundError`` if missing."""

    @abstractmethod
    def list(self, prefix: str = "") -> list[FileInfo]:
        """All files (recursively) under folder ``prefix`` ("" = whole root), sorted by path.

        ``prefix`` is a folder path, not a string prefix: ``list("2026/10")`` returns files in
        ``2026/10/**`` but not ``2026/100/...``. A missing folder returns ``[]``.
        """

    @abstractmethod
    def delete(self, path: str, missing_ok: bool = False) -> None:
        """Delete a file (Drive: move to trash). Raises ``FileNotFoundError`` unless
        ``missing_ok``."""

    @abstractmethod
    def list_changes(self, since_token: str | None) -> tuple[list[Change], str]:
        """Files changed since ``since_token``, plus a new token to pass next time.

        * ``since_token=None`` returns every existing file as ``upserted`` (a full scan) and a
          fresh token. The indexer uses this for its first run and for rebuilds.
        * Tokens are opaque strings; persist them verbatim (the indexer stores them in the
          index ``meta`` table under ``sync_token``).
        * A file that changed several times appears once, with its latest state. Order is
          unspecified. Folders are never reported.
        * A rename/move is reported as ``deleted`` (old path) + ``upserted`` (new path).
        """

    @abstractmethod
    def get_share_link(self, path: str) -> str:
        """A link the owner can open to view/play the file.

        Drive: the file's private ``webViewLink`` (opens only for the owner's Google login).
        Local: a ``file://`` URI. Raises ``FileNotFoundError`` if missing.
        """


_CONTENT_TYPES = {
    ".md": "text/markdown; charset=utf-8",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".txt": "text/plain; charset=utf-8",
    ".m4a": "audio/mp4",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".sqlite": "application/vnd.sqlite3",
}


def guess_type(path: str) -> str:
    dot = path.rfind(".")
    ext = path[dot:].lower() if dot != -1 else ""
    return _CONTENT_TYPES.get(ext, "application/octet-stream")
