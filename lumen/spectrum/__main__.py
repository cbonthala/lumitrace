"""``lumen-spectrum`` / ``python -m lumen.spectrum``: the indexer.

Commands (details: docs/spectrum.md):

* ``run`` (default): serve ``POST /nudge`` and ``GET /health`` on ``indexer_host:indexer_port``,
  sync every ``indexer_poll_interval_seconds`` and back up the index every
  ``indexer_backup_interval_hours``.
* ``sync``: one incremental sync, then exit (``--full`` lists every file).
* ``rebuild``: empty the derived tables (keeping feedback and edit signals) and index everything.
* ``backup``: copy the index to ``_system/index-backup/lumen.sqlite`` now.

``sync`` and ``rebuild`` print a JSON summary (counts and paths) and exit with status 1 if any
file failed with a transient error.
"""

from __future__ import annotations

import argparse
import json
import logging

from lumen.config import Settings, get_settings
from lumen.logging_setup import setup_logging

log = logging.getLogger("lumen.spectrum")


def main(argv: list[str] | None = None, settings: Settings | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="lumen-spectrum",
        description="Lumen Spectrum: the indexer (details: docs/spectrum.md)",
    )
    parser.add_argument(
        "command", nargs="?", default="run", choices=["run", "sync", "rebuild", "backup"]
    )
    parser.add_argument(
        "--full", action="store_true", help="sync: list every file instead of using the token"
    )
    args = parser.parse_args(argv)
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    from lumen.spectrum.core import Indexer

    indexer = Indexer(settings)
    if args.command == "run":
        from lumen.spectrum.service import serve

        try:
            serve(indexer, settings.indexer_host, settings.indexer_port, settings.log_level)
        finally:
            indexer.close()
        return
    try:
        if args.command == "backup":
            info = indexer.backup()
            print(json.dumps({"backup": info.path, "bytes": info.size}))
            return
        result = indexer.rebuild() if args.command == "rebuild" else indexer.sync(full=args.full)
    finally:
        indexer.close()
    print(json.dumps(result.summary()))
    if result.failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
