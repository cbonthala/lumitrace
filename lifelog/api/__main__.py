"""``lifelog-api`` / ``python -m lifelog.api``: serve the recording API with uvicorn."""

from __future__ import annotations

import uvicorn

from lifelog.config import get_settings
from lifelog.logging_setup import setup_logging


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    uvicorn.run(
        "lifelog.api.app:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
