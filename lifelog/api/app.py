"""Recording API application. Placeholder: only ``GET /health`` exists so far.

The recording-api work stream adds ``POST /recordings`` and ``POST /notes`` here.
"""

from __future__ import annotations

from fastapi import FastAPI

from lifelog import __version__
from lifelog.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="LifeLog Recording API", version=__version__)
    app.state.settings = settings

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "api", "version": __version__}

    return app


app = create_app()
