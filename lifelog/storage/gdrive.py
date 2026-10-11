"""Google Drive storage using the ``drive.file`` scope.

``drive.file`` only grants access to files this app created (or the user explicitly opened with
it), so the app creates the ``LifeLog`` root folder itself, in the root of My Drive. Files written
by other tools (for example a brand-new note created in Obsidian through Drive for desktop) are
invisible to this backend; edits to app-created files *are* visible. See
``docs/decisions/0002-google-drive-storage.md``.

One-time sign-in: ``lifelog-gdrive-login`` (see ``docs/runbook.md``).
"""

from __future__ import annotations

import argparse
import logging
import os
import threading
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lifelog.storage.base import (
    Change,
    FileInfo,
    Storage,
    StorageError,
    guess_type,
    is_hidden,
    normalize_path,
)

if TYPE_CHECKING:
    from lifelog.config import Settings

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
FOLDER_MIME = "application/vnd.google-apps.folder"
_FILE_FIELDS = "id,name,mimeType,parents,size,modifiedTime,webViewLink,trashed"
_RESUMABLE_THRESHOLD = 5 * 1024 * 1024
_NUM_RETRIES = 3


def _q_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _parse_time(value: str | None) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, tz=UTC)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _join(folder: str, name: str) -> str:
    return f"{folder}/{name}" if folder else name


class GDriveStorage(Storage):
    """Drive-backed :class:`Storage`. Pass ``service`` to inject a fake Drive client in tests."""

    def __init__(
        self,
        root_folder_name: str = "LifeLog",
        *,
        credentials: Any = None,
        service: Any = None,
    ) -> None:
        if service is None:
            from googleapiclient.discovery import build

            service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        self._svc = service
        self._root_name = root_folder_name
        self._lock = threading.RLock()
        self._root_id: str | None = None
        self._folder_ids: dict[str, str] = {}
        self._folder_paths: dict[str, str] = {}
        self._file_paths: dict[str, str] | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> GDriveStorage:
        return cls(settings.gdrive_root_folder, credentials=load_credentials(settings))

    # --- low-level helpers --------------------------------------------------------------

    def _exec(self, request: Any) -> Any:
        from googleapiclient.errors import HttpError

        try:
            return request.execute(num_retries=_NUM_RETRIES)
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            if status == 404:
                raise FileNotFoundError(str(exc)) from exc
            raise StorageError(f"Google Drive error ({status}): {exc}") from exc

    def _remember_folder(self, path: str, folder_id: str) -> None:
        self._folder_ids[path] = folder_id
        self._folder_paths[folder_id] = path

    def root_id(self) -> str:
        """Id of the LifeLog root folder, creating it in My Drive if needed."""
        with self._lock:
            if self._root_id is None:
                found = self._find_child("root", self._root_name, folder=True)
                if found is None:
                    found = self._exec(
                        self._svc.files().create(
                            body={
                                "name": self._root_name,
                                "mimeType": FOLDER_MIME,
                                "parents": ["root"],
                            },
                            fields=_FILE_FIELDS,
                        )
                    )
                    log.info("created Drive folder %s (%s)", self._root_name, found["id"])
                self._root_id = found["id"]
                self._remember_folder("", found["id"])
            return self._root_id

    def _find_child(self, parent_id: str, name: str, *, folder: bool) -> dict[str, Any] | None:
        mime = f"mimeType = '{FOLDER_MIME}'" if folder else f"mimeType != '{FOLDER_MIME}'"
        q = (
            f"name = '{_q_escape(name)}' and '{_q_escape(parent_id)}' in parents"
            f" and {mime} and trashed = false"
        )
        resp = self._exec(
            self._svc.files().list(
                q=q,
                spaces="drive",
                orderBy="modifiedTime desc",
                pageSize=10,
                fields=f"files({_FILE_FIELDS})",
            )
        )
        files = resp.get("files", [])
        return files[0] if files else None

    def _list_children(self, parent_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            resp = self._exec(
                self._svc.files().list(
                    q=f"'{_q_escape(parent_id)}' in parents and trashed = false",
                    spaces="drive",
                    pageSize=1000,
                    pageToken=page_token,
                    fields=f"nextPageToken,files({_FILE_FIELDS})",
                )
            )
            out.extend(resp.get("files", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                return out

    def _folder_id(self, folder: str, *, create: bool) -> str | None:
        folder = normalize_path(folder, allow_root=True)
        current_id = self.root_id()
        current_path = ""
        for part in folder.split("/") if folder else []:
            current_path = _join(current_path, part)
            cached = self._folder_ids.get(current_path)
            if cached:
                current_id = cached
                continue
            found = self._find_child(current_id, part, folder=True)
            if found is None:
                if not create:
                    return None
                found = self._exec(
                    self._svc.files().create(
                        body={"name": part, "mimeType": FOLDER_MIME, "parents": [current_id]},
                        fields=_FILE_FIELDS,
                    )
                )
            current_id = found["id"]
            self._remember_folder(current_path, current_id)
        return current_id

    def _file_meta(self, path: str) -> dict[str, Any] | None:
        rel = normalize_path(path)
        folder, _, name = rel.rpartition("/")
        parent_id = self._folder_id(folder, create=False)
        if parent_id is None:
            return None
        return self._find_child(parent_id, name, folder=False)

    def _to_info(self, path: str, meta: dict[str, Any]) -> FileInfo:
        return FileInfo(
            path=path,
            size=int(meta.get("size") or 0),
            modified=_parse_time(meta.get("modifiedTime")),
            id=meta.get("id"),
        )

    # --- Storage API --------------------------------------------------------------------

    def read_bytes(self, path: str) -> bytes:
        with self._lock:
            meta = self._file_meta(path)
            if meta is None:
                raise FileNotFoundError(path)
            data = self._exec(self._svc.files().get_media(fileId=meta["id"]))
        return data if isinstance(data, bytes) else bytes(data)

    def write_bytes(self, path: str, data: bytes, content_type: str | None = None) -> FileInfo:
        from googleapiclient.http import MediaInMemoryUpload

        rel = normalize_path(path)
        folder, _, name = rel.rpartition("/")
        media = MediaInMemoryUpload(
            data,
            mimetype=content_type or guess_type(rel),
            resumable=len(data) > _RESUMABLE_THRESHOLD,
        )
        with self._lock:
            parent_id = self._folder_id(folder, create=True)
            assert parent_id is not None
            existing = self._find_child(parent_id, name, folder=False)
            if existing is not None:
                meta = self._exec(
                    self._svc.files().update(
                        fileId=existing["id"], media_body=media, fields=_FILE_FIELDS
                    )
                )
            else:
                meta = self._exec(
                    self._svc.files().create(
                        body={"name": name, "parents": [parent_id]},
                        media_body=media,
                        fields=_FILE_FIELDS,
                    )
                )
            if self._file_paths is not None:
                self._file_paths[meta["id"]] = rel
        return self._to_info(rel, meta)

    def exists(self, path: str) -> bool:
        with self._lock:
            return self._file_meta(path) is not None

    def stat(self, path: str) -> FileInfo:
        with self._lock:
            meta = self._file_meta(path)
        if meta is None:
            raise FileNotFoundError(path)
        return self._to_info(normalize_path(path), meta)

    def _walk(self, prefix: str = "") -> list[FileInfo]:
        prefix = normalize_path(prefix, allow_root=True)
        start = self._folder_id(prefix, create=False)
        if start is None:
            return []
        out: list[FileInfo] = []
        queue: deque[tuple[str, str]] = deque([(prefix, start)])
        while queue:
            folder_path, folder_id = queue.popleft()
            for child in self._list_children(folder_id):
                child_path = _join(folder_path, child["name"])
                if child["name"].startswith("."):
                    continue
                if child.get("mimeType") == FOLDER_MIME:
                    self._remember_folder(child_path, child["id"])
                    queue.append((child_path, child["id"]))
                else:
                    out.append(self._to_info(child_path, child))
        out.sort(key=lambda f: f.path)
        return out

    def list(self, prefix: str = "") -> list[FileInfo]:
        with self._lock:
            return self._walk(prefix)

    def delete(self, path: str, missing_ok: bool = False) -> None:
        with self._lock:
            meta = self._file_meta(path)
            if meta is None:
                if missing_ok:
                    return
                raise FileNotFoundError(path)
            self._exec(
                self._svc.files().update(fileId=meta["id"], body={"trashed": True}, fields="id")
            )

    def _build_id_index(self) -> list[FileInfo]:
        files = self._walk("")
        self._file_paths = {f.id: f.path for f in files if f.id}
        return files

    def _folder_path_of(self, folder_id: str, _depth: int = 0) -> str | None:
        """Path of a folder relative to the root, or None if it is outside the LifeLog tree."""
        if folder_id in self._folder_paths:
            return self._folder_paths[folder_id]
        if _depth > 64:
            return None
        try:
            meta = self._exec(
                self._svc.files().get(fileId=folder_id, fields="id,name,parents,trashed")
            )
        except FileNotFoundError:
            return None
        if meta.get("trashed"):
            return None
        parents = meta.get("parents") or []
        if not parents:
            return None
        parent_path = self._folder_path_of(parents[0], _depth + 1)
        if parent_path is None:
            return None
        path = _join(parent_path, meta["name"])
        self._remember_folder(path, folder_id)
        return path

    def list_changes(self, since_token: str | None) -> tuple[list[Change], str]:
        with self._lock:
            self.root_id()
            if since_token is None:
                start = self._exec(self._svc.changes().getStartPageToken())["startPageToken"]
                files = self._build_id_index()
                return [Change(f.path, "upserted", f.modified) for f in files], start
            if self._file_paths is None:
                self._build_id_index()
            assert self._file_paths is not None
            result: dict[str, Change] = {}
            page_token = since_token
            while True:
                resp = self._exec(
                    self._svc.changes().list(
                        pageToken=page_token,
                        spaces="drive",
                        includeRemoved=True,
                        pageSize=1000,
                        fields=(
                            "nextPageToken,newStartPageToken,"
                            f"changes(fileId,removed,file({_FILE_FIELDS}))"
                        ),
                    )
                )
                for change in resp.get("changes", []):
                    self._apply_change(change, result)
                if resp.get("nextPageToken"):
                    page_token = resp["nextPageToken"]
                    continue
                new_token = resp.get("newStartPageToken") or page_token
                break
            changes = [c for c in result.values() if not is_hidden(c.path)]
            return sorted(changes, key=lambda c: c.path), new_token

    def _apply_change(self, change: dict[str, Any], result: dict[str, Change]) -> None:
        assert self._file_paths is not None
        file_id = change.get("fileId")
        meta = change.get("file") or {}
        gone = change.get("removed") or meta.get("trashed")
        is_folder = meta.get("mimeType") == FOLDER_MIME or file_id in self._folder_paths

        if is_folder:
            if not file_id or file_id == self._root_id:
                return
            old = self._folder_paths.get(file_id)
            new: str | None = None
            if not gone and meta.get("parents"):
                parent_path = self._folder_path_of(meta["parents"][0])
                if parent_path is not None:
                    new = _join(parent_path, meta["name"])
            if old == new:
                return
            if old is not None:
                for fid, fpath in list(self._file_paths.items()):
                    if fpath.startswith(old + "/"):
                        result[fpath] = Change(fpath, "deleted")
                        del self._file_paths[fid]
                for fpath in [p for p in self._folder_ids if p == old or p.startswith(old + "/")]:
                    self._folder_paths.pop(self._folder_ids.pop(fpath), None)
            if new is not None:
                self._remember_folder(new, file_id)
                if old is not None:
                    for info in self._walk(new):
                        if info.id:
                            self._file_paths[info.id] = info.path
                        result[info.path] = Change(info.path, "upserted", info.modified)
            return

        old_path = self._file_paths.get(file_id) if file_id else None
        meta_path: str | None = None
        if meta.get("parents") and meta.get("name"):
            parent_path = self._folder_path_of(meta["parents"][0])
            if parent_path is not None:
                meta_path = _join(parent_path, meta["name"])
        if gone:
            if file_id:
                self._file_paths.pop(file_id, None)
            if old_path or meta_path:
                path = old_path or meta_path
                assert path is not None
                result[path] = Change(path, "deleted")
            return
        new_path = meta_path
        if old_path is not None and old_path != new_path:
            result[old_path] = Change(old_path, "deleted")
            del self._file_paths[file_id]
        if new_path is not None and file_id:
            self._file_paths[file_id] = new_path
            result[new_path] = Change(new_path, "upserted", _parse_time(meta.get("modifiedTime")))

    def get_share_link(self, path: str) -> str:
        with self._lock:
            meta = self._file_meta(path)
            if meta is None:
                raise FileNotFoundError(path)
            link = meta.get("webViewLink")
            if not link:
                link = self._exec(
                    self._svc.files().get(fileId=meta["id"], fields="webViewLink")
                ).get("webViewLink")
        if not link:
            raise StorageError(f"Drive returned no webViewLink for {path}")
        return link


# --- credentials and one-time login ----------------------------------------------------------


def load_credentials(settings: Settings) -> Any:
    """Load (and refresh if needed) the saved OAuth token written by ``lifelog-gdrive-login``."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token_file = Path(settings.gdrive_token_file)
    if not token_file.exists():
        raise StorageError(
            f"No Google Drive token at {token_file}. Run `lifelog-gdrive-login` first "
            "(see docs/runbook.md)."
        )
    creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _save_token(token_file, creds.to_json())
        else:
            raise StorageError("Google Drive token is invalid; run `lifelog-gdrive-login` again.")
    return creds


def _save_token(path: Path, token_json: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(token_json)


def login_main(argv: list[str] | None = None) -> None:
    """``lifelog-gdrive-login``: run the OAuth consent flow once and save the token file."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    from lifelog.config import get_settings

    parser = argparse.ArgumentParser(description="Sign in to Google Drive for LifeLog.")
    parser.add_argument("--port", type=int, default=8085, help="local redirect port")
    parser.add_argument(
        "--no-browser", action="store_true", help="print the sign-in URL instead of opening it"
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    secrets_file = Path(settings.gdrive_client_secrets_file)
    if not secrets_file.exists():
        raise SystemExit(
            f"OAuth client file not found: {secrets_file}. Download it from Google Cloud Console "
            "(OAuth client ID, type 'Desktop app') and set LIFELOG_GDRIVE_CLIENT_SECRETS_FILE."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets_file), SCOPES)
    creds = flow.run_local_server(
        port=args.port,
        open_browser=not args.no_browser,
        access_type="offline",
        prompt="consent",
    )
    _save_token(Path(settings.gdrive_token_file), creds.to_json())
    storage = GDriveStorage(settings.gdrive_root_folder, credentials=creds)
    print(f"Signed in. Token saved to {settings.gdrive_token_file}.")
    print(f"LifeLog root folder id: {storage.root_id()}")
