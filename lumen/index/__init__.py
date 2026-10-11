"""The SQLite index. The schema contract lives in :mod:`lumen.index.schema`."""

from lumen.index.schema import SCHEMA_VERSION, connect

__all__ = ["SCHEMA_VERSION", "connect"]
