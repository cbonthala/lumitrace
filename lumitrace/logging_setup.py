"""Logging setup shared by the entry points."""

from __future__ import annotations

import logging

QUIET_LOGGERS = ("httpx", "httpcore")
"""Their INFO lines print full request URLs; Sarvam's presigned storage URLs carry access
signatures, so they only log warnings and errors."""


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
