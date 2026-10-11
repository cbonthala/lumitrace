"""The SQLite index. The schema contract lives in :mod:`lifelog.index.schema`."""

from lifelog.index.schema import SCHEMA_VERSION, connect

__all__ = ["SCHEMA_VERSION", "connect"]
