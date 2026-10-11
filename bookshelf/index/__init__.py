"""The SQLite index. The schema contract lives in :mod:`bookshelf.index.schema`."""

from bookshelf.index.schema import SCHEMA_VERSION, connect

__all__ = ["SCHEMA_VERSION", "connect"]
