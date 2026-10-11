"""Swappable storage. Use :func:`get_storage` instead of constructing backends directly."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bookshelf.books.storage.base import (
    Change,
    ChangeKind,
    FileInfo,
    InvalidPathError,
    Storage,
    StorageError,
    normalize_path,
)

if TYPE_CHECKING:
    from bookshelf.config import Settings

__all__ = [
    "Change",
    "ChangeKind",
    "FileInfo",
    "InvalidPathError",
    "Storage",
    "StorageError",
    "get_storage",
    "normalize_path",
]


def get_storage(settings: Settings | None = None) -> Storage:
    """Build the storage backend selected by ``settings.storage_backend``."""
    if settings is None:
        from bookshelf.config import get_settings

        settings = get_settings()
    if settings.storage_backend == "local":
        from bookshelf.books.storage.local import LocalStorage

        return LocalStorage(settings.local_root)
    if settings.storage_backend == "gdrive":
        from bookshelf.books.storage.gdrive import GDriveStorage

        return GDriveStorage.from_settings(settings)
    raise ValueError(f"unknown storage backend: {settings.storage_backend!r}")
