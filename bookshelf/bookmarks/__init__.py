"""Bookmarks: the indexer. Keeps the SQLite index in step with the day files in storage
(docs/bookmarks.md).

Modules: ``core`` (sync, rebuild, backup), ``passages`` (splitting day files), ``edits`` (edit
signals), ``backup`` (SQLite backup to storage), ``service`` (``run`` loop and HTTP server).
"""
