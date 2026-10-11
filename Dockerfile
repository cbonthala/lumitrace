# One Lumen image for all three programs (Prism, Spectrum, Lens);
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

COPY lumen ./lumen
COPY prompts ./prompts
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}" \
    LUMEN_LOCAL_ROOT=/data/Lumen \
    LUMEN_INDEX_PATH=/data/index/lumen.sqlite \
    LUMEN_PROMPTS_DIR=/app/prompts \
    LUMEN_GDRIVE_CLIENT_SECRETS_FILE=/secrets/gdrive_client_secret.json \
    LUMEN_GDRIVE_TOKEN_FILE=/secrets/gdrive_token.json

RUN useradd --create-home --uid 10001 lumen \
    && mkdir -p /data /secrets \
    && chown lumen:lumen /data /secrets
USER lumen
VOLUME ["/data"]

EXPOSE 8000 8001 8002
CMD ["lumen-prism"]
