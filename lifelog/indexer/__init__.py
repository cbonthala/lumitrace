"""Indexer: keeps the SQLite index in step with the day files in storage (docs/indexer.md).

Modules: ``core`` (sync, rebuild, backup), ``passages`` (splitting day files), ``edits`` (edit
signals), ``backup`` (SQLite backup to storage), ``service`` (``run`` loop and HTTP server).
"""
