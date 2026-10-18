"""Application settings, loaded from environment variables and an optional `.env` file.

Every variable is prefixed with `LUMITRACE_` (for example `LUMITRACE_API_TOKEN`). Provider API keys
that LiteLLM reads itself (`OPENAI_API_KEY`, `AWS_ACCESS_KEY_ID`, ...) are *not* prefixed and are
not modelled here. `.env.example` documents every variable; keep the two in sync.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, PrivateAttr, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from lumitrace.household import Household, load_household


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LUMITRACE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- General -------------------------------------------------------------------------
    log_level: str = "INFO"
    timezone: str = "America/Chicago"
    day_rollover_hour: int = Field(default=4, ge=0, le=23)
    prompts_dir: Path = Path("prompts")
    _household: Household = PrivateAttr(default_factory=Household)

    # --- Recording API -------------------------------------------------------------------
    api_token: SecretStr = SecretStr("")
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_max_upload_mb: int = 200
    audio_bitrate_kbps: int = 32
    photo_max_dimension: int = 2048
    photo_jpeg_quality: int = Field(default=85, ge=1, le=95)
    flash_username: str = ""
    """Username for the Flash web app sign-in (``/flash/``); empty = sign-in turned off."""
    flash_password: SecretStr = SecretStr("")
    flash_session_days: int = Field(default=90, ge=1, le=400)
    """How long a Flash web app sign-in lasts before the password is asked again."""

    # --- Storage -------------------------------------------------------------------------
    storage_backend: Literal["local", "gdrive"] = "local"
    local_root: Path = Path("data/Lumitrace")
    gdrive_client_secrets_file: Path = Path("secrets/gdrive_client_secret.json")
    gdrive_token_file: Path = Path("secrets/gdrive_token.json")
    gdrive_root_folder: str = "Lumitrace"

    # --- Speech to text ------------------------------------------------------------------
    stt_provider: Literal["litellm", "aws_transcribe", "sarvam", "fake"] = "litellm"
    stt_model: str = "openai/gpt-4o-transcribe"
    stt_language: str = "en"
    stt_keyterms: str = ""
    """Comma-separated names, places and brands to bias recognition toward (Sarvam only). Names
    from the family file are always added. Use :attr:`stt_keyterm_list`."""
    aws_region: str = "us-east-1"
    aws_transcribe_bucket: str = ""
    sarvam_api_key: SecretStr = SecretStr("")
    sarvam_model: str = "saaras:v4"
    sarvam_mode: Literal["transcribe", "codemix", "verbatim", "translit"] = "codemix"
    """Output of the transcript kept in the day file; ``codemix`` keeps English words in English
    and the rest in its own script."""

    # --- LLMs (LiteLLM model strings) ----------------------------------------------------
    llm_write_journal_model: str = "gemini/gemini-3.8-flash"
    """Fills the day file at 4:05 a.m., and updates it when a later recording arrives."""
    llm_fallback_model: str = "gemini/gemini-3.6-flash"
    llm_timeout_seconds: int = 120
    llm_max_retries: int = 2

    # --- Embeddings ----------------------------------------------------------------------
    embedding_model: str = "gemini/gemini-embedding-2"
    """Search vectors. The call asks for ``embedding_dimension`` values.
    Gemini's full size is 3072."""
    embedding_dimension: int = Field(default=1536, gt=0)

    # --- Index / indexer -----------------------------------------------------------------
    index_path: Path = Path("data/index/lumitrace.sqlite")
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
    mcp_auth_mode: Literal["none", "oauth"] = "oauth"
    mcp_owner_password: SecretStr = SecretStr("")
    mcp_session_days: int = Field(default=7, ge=1)
    mcp_admin_host: str = "127.0.0.1"
    mcp_admin_port: int = 8003
    mcp_admin_url: str = "http://127.0.0.1:8003"

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

    def __init__(self, **kwargs: Any) -> None:
        household = kwargs.pop("household", None)
        super().__init__(**kwargs)
        if household is not None:
            if not isinstance(household, Household):
                raise TypeError("household must be a Household")
            self._household = household

    def with_household(self, household: Household) -> Settings:
        """A copy of these settings that uses ``household`` instead of an empty family."""
        copied = self.model_copy()
        copied._household = household
        return copied

    @property
    def household(self) -> Household:
        """Family members and notes. Empty unless passed in or loaded by :func:`get_settings`."""
        return self._household

    @property
    def family_members(self) -> list[str]:
        """Names from the family file, in file order."""
        return self._household.members

    @property
    def family_relations(self) -> dict[str, str]:
        """``{name: relation}`` from the family file; ``""`` when no relation is given."""
        return self._household.relations

    @property
    def owner_name(self) -> str | None:
        """The family member marked ``me`` or ``self``: the person who keeps the journal."""
        return self._household.owner_name

    @property
    def glossary_text(self) -> str:
        """Markdown notes from the family file, or ``(none)``."""
        return self._household.glossary

    @property
    def stt_keyterm_list(self) -> list[str]:
        """Family names, then :attr:`stt_keyterms`: trimmed, duplicates (any case) removed."""
        terms: dict[str, str] = {}
        for raw in [*self.family_members, *self.stt_keyterms.split(",")]:
            term = " ".join(raw.split())
            if term:
                terms.setdefault(term.casefold(), term)
        return list(terms.values())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton. Loads ``secrets/family.md`` when that file exists.

    Tests should construct ``Settings(...)`` directly. That does not read the family file,
    so a checkout with real names in ``secrets/`` cannot leak into tests.
    """
    settings = Settings()
    settings._household = load_household()
    return settings
