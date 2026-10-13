"""``lumitrace-prism`` / ``python -m lumitrace.prism``: serve the recording API with
uvicorn."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import uvicorn

from lumitrace.config import get_settings
from lumitrace.logging_setup import setup_logging


def main(argv: Sequence[str] | None = None) -> None:
    argparse.ArgumentParser(
        prog="lumitrace-prism",
        description="Lumitrace Prism: the recording API (settings come from LUMITRACE_* "
        "environment variables and .env).",
    ).parse_args(argv)
    settings = get_settings()
    setup_logging(settings.log_level)
    uvicorn.run(
        "lumitrace.prism.app:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
