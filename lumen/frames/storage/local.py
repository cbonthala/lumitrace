"""Filesystem storage. The root folder plays the role of the Drive ``Lumen`` folder and can be
opened directly as (part of) an Obsidian vault.

Change tracking is an mtime scan: the token is a compressed snapshot of ``{path: [mtime_ns,
size]}``, so it is stateless and also detects deletions. Tokens grow with the number of files
(roughly tens of KB for years of data), which is fine for local/dev use.
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import threading
import zlib
from datetime import UTC, datetime
from pathlib import Path

from lumen.frames.storage.base import (
    Change,
    FileInfo,
    InvalidPathError,
    Storage,
    is_hidden,
    normalize_path,
)

_TOKEN_PREFIX = "local1:"


class LocalStorage(Storage):
    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _abs(self, path: str, *, allow_root: bool = False) -> Path:
        rel = normalize_path(path, allow_root=allow_root)
        full = (self.root / rel) if rel else self.root
        if full != self.root and self.root not in full.parents:
            raise InvalidPathError(f"path escapes storage root: {path!r}")
        return full

    def _info(self, rel: str, full: Path) -> FileInfo:
        st = full.stat()
        return FileInfo(
            path=rel,
            size=st.st_size,
            modified=datetime.fromtimestamp(st.st_mtime, tz=UTC),
        )

    def read_bytes(self, path: str) -> bytes:
        full = self._abs(path)
        if not full.is_file():
            raise FileNotFoundError(path)
        return full.read_bytes()

    def write_bytes(self, path: str, data: bytes, content_type: str | None = None) -> FileInfo:
        rel = normalize_path(path)
        full = self._abs(rel)
        full.parent.mkdir(parents=True, exist_ok=True)
        if full.is_dir():
            raise InvalidPathError(f"a folder exists at {path!r}")
        fd, tmp = tempfile.mkstemp(prefix=f".{full.name}.", suffix=".tmp", dir=full.parent)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, full)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return self._info(rel, full)

    def exists(self, path: str) -> bool:
        return self._abs(path).is_file()

    def stat(self, path: str) -> FileInfo:
        rel = normalize_path(path)
        full = self._abs(rel)
        if not full.is_file():
            raise FileNotFoundError(path)
        return self._info(rel, full)

    def _walk(self, prefix: str = "") -> dict[str, os.stat_result]:
        base = self._abs(prefix, allow_root=True)
        found: dict[str, os.stat_result] = {}
        if not base.is_dir():
            return found
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                if name.startswith("."):
                    continue
                full = Path(dirpath) / name
                rel = full.relative_to(self.root).as_posix()
                if is_hidden(rel):
                    continue
                try:
                    found[rel] = full.stat()
                except FileNotFoundError:
                    continue
        return found

    def list(self, prefix: str = "") -> list[FileInfo]:
        entries = self._walk(prefix)
        return [
            FileInfo(
                path=rel,
                size=st.st_size,
                modified=datetime.fromtimestamp(st.st_mtime, tz=UTC),
            )
            for rel, st in sorted(entries.items())
        ]

    def delete(self, path: str, missing_ok: bool = False) -> None:
        full = self._abs(path)
        if not full.is_file():
            if missing_ok:
                return
            raise FileNotFoundError(path)
        full.unlink()
        parent = full.parent
        while parent != self.root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    def list_changes(self, since_token: str | None) -> tuple[list[Change], str]:
        with self._lock:
            current = {rel: [st.st_mtime_ns, st.st_size] for rel, st in self._walk().items()}
        previous = _decode_token(since_token) if since_token is not None else {}
        changes: list[Change] = []
        for rel, sig in sorted(current.items()):
            if previous.get(rel) != sig:
                modified = datetime.fromtimestamp(sig[0] / 1e9, tz=UTC)
                changes.append(Change(path=rel, kind="upserted", modified=modified))
        for rel in sorted(previous.keys() - current.keys()):
            changes.append(Change(path=rel, kind="deleted"))
        return changes, _encode_token(current)

    def get_share_link(self, path: str) -> str:
        full = self._abs(path)
        if not full.is_file():
            raise FileNotFoundError(path)
        return full.as_uri()


def _encode_token(snapshot: dict[str, list[int]]) -> str:
    raw = json.dumps(snapshot, separators=(",", ":"), sort_keys=True).encode()
    return _TOKEN_PREFIX + base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode()


def _decode_token(token: str) -> dict[str, list[int]]:
    if not token.startswith(_TOKEN_PREFIX):
        raise ValueError("not a local storage change token")
    raw = zlib.decompress(base64.urlsafe_b64decode(token[len(_TOKEN_PREFIX) :]))
    return {k: list(v) for k, v in json.loads(raw).items()}
