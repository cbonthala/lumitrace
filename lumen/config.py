"""Application settings, loaded from environment variables and an optional `.env` file.

Every variable is prefixed with `LUMEN_` (for example `LUMEN_API_TOKEN`). Provider API keys
that LiteLLM reads itself (`OPENAI_API_KEY`, `AWS_ACCESS_KEY_ID`, ...) are *not* prefixed and are
not modelled here. `.env.example` documents every variable; keep the two in sync.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LUMEN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- General -------------------------------------------------------------------------
    log_level: str = "INFO"
    timezone: str = "America/Chicago"
    day_rollover_hour: int = Field(default=4, ge=0, le=23)
    prompts_dir: Path = Path("prompts")
    family: str = ""
    """Comma-separated names of the family members who get their own "Family" sub-section in
    each day file, e.g. ``Maya, Leo``. Use :attr:`family_members`."""

    # --- Recording API -------------------------------------------------------------------
    api_token: SecretStr = SecretStr("")
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_max_upload_mb: int = 200
    audio_bitrate_kbps: int = 32
    photo_max_dimension: int = 2048
    photo_jpeg_quality: int = Field(default=85, ge=1, le=95)

    # --- Storage -------------------------------------------------------------------------
    storage_backend: Literal["local", "gdrive"] = "local"
    local_root: Path = Path("data/Lumen")
    gdrive_client_secrets_file: Path = Path("secrets/gdrive_client_secret.json")
    gdrive_token_file: Path = Path("secrets/gdrive_token.json")
    gdrive_root_folder: str = "Lumen"

    # --- Speech to text ------------------------------------------------------------------
    stt_provider: Literal["litellm", "aws_transcribe", "fake"] = "litellm"
    stt_model: str = "openai/gpt-4o-transcribe"
    stt_language: str = "en"
    aws_region: str = "us-east-1"
    aws_transcribe_bucket: str = ""

    # --- LLMs (LiteLLM model strings) ----------------------------------------------------
    llm_extract_facts_model: str = "openai/gpt-4o-mini"
    llm_write_journal_model: str = "openai/gpt-4o"
    llm_fallback_model: str = "openai/gpt-4o-mini"
    llm_timeout_seconds: int = 120
    llm_max_retries: int = 2

    # --- Embeddings ----------------------------------------------------------------------
    embedding_model: str = "openai/text-embedding-3-small"
    embedding_dimension: int = Field(default=1536, gt=0)

    # --- Index / indexer -----------------------------------------------------------------
    index_path: Path = Path("data/index/lumen.sqlite")
    indexer_host: str = "0.0.0.0"
    indexer_port: int = 8001
    indexer_poll_interval_seconds: int = Field(default=300, gt=0)
    indexer_nudge_url: str = "http://localhost:8001/nudge"
    indexer_backup_interval_hours: int = Field(default=24, ge=0)

    # --- MCP server ----------------------------------------------------------------------
    mcp_transport: Literal["stdio", "streamable-http"] = "streamable-http"
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8002
    mcp_path: str = "/mcp"
    mcp_public_url: str = "http://localhost:8002"
    mcp_auth_mode: Literal["none", "token", "oauth"] = "token"
    mcp_auth_token: SecretStr = SecretStr("")
    mcp_owner_password: SecretStr = SecretStr("")

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone: {value!r}") from exc
        return value

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def family_members(self) -> list[str]:
        """:attr:`family` as a list: trimmed, empty names dropped, duplicates (any case) removed."""
        names: dict[str, str] = {}
        for raw in self.family.split(","):
            name = " ".join(raw.split())
            if name:
                names.setdefault(name.casefold(), name)
        return list(names.values())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton. Tests should construct `Settings(...)` directly."""
    return Settings()
