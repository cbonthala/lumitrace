"""``lifelog-indexer`` / ``python -m lifelog.indexer``. Placeholder until the indexer lands.

Planned commands (see docs/architecture.md):

* ``run`` (default): serve ``POST /nudge`` on ``indexer_host:indexer_port`` and sync every
  ``indexer_poll_interval_seconds``.
* ``sync``: one incremental sync, then exit.
* ``rebuild``: :func:`lifelog.index.schema.reset_derived`, then a full sync.
"""

from __future__ import annotations

import argparse
import logging
import time

from lifelog.config import get_settings
from lifelog.logging_setup import setup_logging

log = logging.getLogger("lifelog.indexer")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="lifelog-indexer")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "sync", "rebuild"])
    args = parser.parse_args(argv)
    settings = get_settings()
    setup_logging(settings.log_level)
    if args.command != "run":
        raise SystemExit(f"lifelog-indexer {args.command}: not implemented yet")
    log.warning("indexer placeholder: nothing is indexed yet")
    while True:
        time.sleep(settings.indexer_poll_interval_seconds)


if __name__ == "__main__":
    main()
