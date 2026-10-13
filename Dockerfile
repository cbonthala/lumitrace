# One Lumitrace image for all three programs (Prism, Spectrum, Lens);
# docker-compose.yml picks the command per service.
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

COPY lumitrace ./lumitrace
COPY prompts ./prompts
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}" \
    LUMITRACE_LOCAL_ROOT=/data/Lumitrace \
    LUMITRACE_INDEX_PATH=/data/index/lumitrace.sqlite \
    LUMITRACE_PROMPTS_DIR=/app/prompts \
    LUMITRACE_GDRIVE_CLIENT_SECRETS_FILE=/secrets/gdrive_client_secret.json \
    LUMITRACE_GDRIVE_TOKEN_FILE=/secrets/gdrive_token.json

RUN useradd --create-home --uid 10001 lumitrace \
    && mkdir -p /data /secrets \
    && chown lumitrace:lumitrace /data /secrets
USER lumitrace
VOLUME ["/data"]

EXPOSE 8000 8001 8002
CMD ["lumitrace-prism"]
