"""The SQLite index. The schema contract lives in :mod:`lumitrace.index.schema`."""

from lumitrace.index.schema import SCHEMA_VERSION, connect

__all__ = ["SCHEMA_VERSION", "connect"]
