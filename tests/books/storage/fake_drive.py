"""A small in-memory stand-in for the Drive v3 client, covering what GDriveStorage uses."""

from __future__ import annotations

import itertools
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httplib2
from googleapiclient.errors import HttpError

FOLDER = "application/vnd.google-apps.folder"
_NAME_RE = re.compile(r"name = '((?:[^'\\]|\\.)*)'")
_PARENT_RE = re.compile(r"'((?:[^'\\]|\\.)*)' in parents")
_MIME_RE = re.compile(r"mimeType (=|!=) '([^']*)'")


def _unescape(value: str) -> str:
    return re.sub(r"\\(.)", r"\1", value)


class _Req:
    def __init__(self, fn: Any) -> None:
        self._fn = fn

    def execute(self, num_retries: int = 0) -> Any:
        return self._fn()


def _not_found(file_id: str) -> HttpError:
    return HttpError(httplib2.Response({"status": 404}), f"File not found: {file_id}".encode())


class FakeDrive:
    def __init__(self, changes_page_size: int = 3) -> None:
        self.root_id = "my-drive-root"
        self.items: dict[str, dict[str, Any]] = {}
        self.content: dict[str, bytes] = {}
        self.change_log: list[tuple[str, bool]] = []
        self.changes_page_size = changes_page_size
        self._ids = itertools.count(1)
        self._clock = datetime(2026, 10, 10, tzinfo=UTC)

    # helpers ----------------------------------------------------------------------------
    def _now(self) -> str:
        self._clock += timedelta(seconds=1)
        return self._clock.isoformat().replace("+00:00", "Z")

    def _resolve(self, file_id: str) -> str:
        return self.root_id if file_id == "root" else file_id

    def _public(self, item: dict[str, Any]) -> dict[str, Any]:
        out = dict(item)
        if item["mimeType"] != FOLDER:
            out["size"] = str(len(self.content.get(item["id"], b"")))
        return out

    def _touch(self, file_id: str, removed: bool = False) -> None:
        self.items[file_id]["modifiedTime"] = self._now()
        self.change_log.append((file_id, removed))

    # simulated owner actions ---------------------------------------------------------------
    def rename(self, file_id: str, new_name: str) -> None:
        self.items[file_id]["name"] = new_name
        self._touch(file_id)

    def id_of(self, name: str) -> str:
        return next(i for i, it in self.items.items() if it["name"] == name and not it["trashed"])

    # API surface ---------------------------------------------------------------------------
    def files(self) -> FakeDrive:
        return self

    def changes(self) -> _Changes:
        return _Changes(self)

    def list(
        self,
        q: str = "",
        pageSize: int = 100,
        pageToken: str | None = None,
        orderBy: str | None = None,
        **_: Any,
    ) -> _Req:
        def run() -> dict[str, Any]:
            items = [it for it in self.items.values() if not it["trashed"]]
            if m := _NAME_RE.search(q):
                items = [it for it in items if it["name"] == _unescape(m.group(1))]
            if m := _PARENT_RE.search(q):
                parent = self._resolve(_unescape(m.group(1)))
                items = [it for it in items if parent in it["parents"]]
            if m := _MIME_RE.search(q):
                op, mime = m.groups()
                items = [it for it in items if (it["mimeType"] == mime) == (op == "=")]
            if orderBy == "modifiedTime desc":
                items.sort(key=lambda it: it["modifiedTime"], reverse=True)
            start = int(pageToken or 0)
            page = items[start : start + pageSize]
            resp: dict[str, Any] = {"files": [self._public(it) for it in page]}
            if start + pageSize < len(items):
                resp["nextPageToken"] = str(start + pageSize)
            return resp

        return _Req(run)

    def create(self, body: dict[str, Any], media_body: Any = None, fields: str = "") -> _Req:
        def run() -> dict[str, Any]:
            file_id = f"id{next(self._ids)}"
            self.items[file_id] = {
                "id": file_id,
                "name": body["name"],
                "mimeType": body.get("mimeType", "application/octet-stream"),
                "parents": [self._resolve(p) for p in body.get("parents", ["root"])],
                "trashed": False,
                "modifiedTime": "",
                "webViewLink": f"https://drive.google.com/file/d/{file_id}/view",
            }
            if media_body is not None:
                self.content[file_id] = media_body.getbytes(0, media_body.size())
                self.items[file_id]["mimeType"] = media_body.mimetype()
            self._touch(file_id)
            return self._public(self.items[file_id])

        return _Req(run)

    def update(
        self,
        fileId: str,
        media_body: Any = None,
        body: dict[str, Any] | None = None,
        fields: str = "",
    ) -> _Req:
        def run() -> dict[str, Any]:
            if fileId not in self.items:
                raise _not_found(fileId)
            if media_body is not None:
                self.content[fileId] = media_body.getbytes(0, media_body.size())
            for key, value in (body or {}).items():
                self.items[fileId][key] = value
            self._touch(fileId)
            return self._public(self.items[fileId])

        return _Req(run)

    def get(self, fileId: str, fields: str = "") -> _Req:
        def run() -> dict[str, Any]:
            file_id = self._resolve(fileId)
            if file_id == self.root_id:
                return {"id": self.root_id, "name": "My Drive", "parents": [], "trashed": False}
            if file_id not in self.items:
                raise _not_found(fileId)
            return self._public(self.items[file_id])

        return _Req(run)

    def get_media(self, fileId: str) -> _Req:
        def run() -> bytes:
            if fileId not in self.content:
                raise _not_found(fileId)
            return self.content[fileId]

        return _Req(run)


class _Changes:
    def __init__(self, drive: FakeDrive) -> None:
        self.drive = drive

    def getStartPageToken(self) -> _Req:
        return _Req(lambda: {"startPageToken": str(len(self.drive.change_log))})

    def list(self, pageToken: str, **_: Any) -> _Req:
        def run() -> dict[str, Any]:
            start = int(pageToken)
            end = min(start + self.drive.changes_page_size, len(self.drive.change_log))
            changes = []
            for file_id, removed in self.drive.change_log[start:end]:
                change: dict[str, Any] = {"fileId": file_id, "removed": removed}
                if not removed:
                    change["file"] = self.drive._public(self.drive.items[file_id])
                changes.append(change)
            resp: dict[str, Any] = {"changes": changes}
            if end < len(self.drive.change_log):
                resp["nextPageToken"] = str(end)
            else:
                resp["newStartPageToken"] = str(end)
            return resp

        return _Req(run)
