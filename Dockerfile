# One image for all three programs; docker-compose.yml picks the command per service.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tzdata ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY lifelog ./lifelog
COPY prompts ./prompts
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}" \
    LIFELOG_LOCAL_ROOT=/data/LifeLog \
    LIFELOG_INDEX_PATH=/data/index/lifelog.sqlite \
    LIFELOG_PROMPTS_DIR=/app/prompts \
    LIFELOG_GDRIVE_CLIENT_SECRETS_FILE=/secrets/gdrive_client_secret.json \
    LIFELOG_GDRIVE_TOKEN_FILE=/secrets/gdrive_token.json

RUN useradd --create-home --uid 10001 lifelog \
    && mkdir -p /data /secrets \
    && chown lifelog:lifelog /data /secrets
USER lifelog
VOLUME ["/data"]

EXPOSE 8000 8001 8002
CMD ["lifelog-api"]
