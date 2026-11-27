"""Runtime configuration.

Transport selection is explicit. Production on the Sprite uses the Sprites
Supabase connector gateway, which injects the Supabase secret key server side,
so no database credential exists on the Sprite. ``direct`` mode is for local
development only and reads the key from a gitignored ``.env``. ``memory`` mode
is for tests. The app never falls back from one mode to another.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
# On the Sprite, secrets that are ours (not Supabase's) live here, mode 600,
# outside the release directory. Missing files are ignored.
SPRITE_ENV_FILE = Path("/home/sprite/.config/cornucopia/cornucopia.env")


class TransportMode(StrEnum):
    GATEWAY = "gateway"
    DIRECT = "direct"
    MEMORY = "memory"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=(REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env", SPRITE_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = Field(default="development", alias="CORNUCOPIA_ENV")
    transport: TransportMode = Field(default=TransportMode.GATEWAY, alias="CORNUCOPIA_TRANSPORT")
    db_schema: str = Field(default="cornucopia", alias="CORNUCOPIA_DB_SCHEMA")

    # gateway mode: CORNUCOPIA's own config name for the connector base URL,
    # e.g. https://api.sprites.dev/v1/gateway/supabase/<connection_id>
    supabase_gateway_url: str | None = Field(default=None, alias="SUPABASE_GATEWAY_URL")

    # direct mode (local development only)
    supabase_url: str | None = Field(default=None, alias="SUPABASE_URL")
    supabase_secret_key: SecretStr | None = Field(default=None, alias="SUPABASE_SECRET_KEY")

    # MVP: one operating organization, created on startup if missing.
    org_slug: str = Field(default="thanksgiving-2026", alias="CORNUCOPIA_ORG_SLUG")
    org_name: str = Field(default="Thanksgiving Community Food Rescue", alias="CORNUCOPIA_ORG_NAME")

    # API auth: bearer token shared with the frontend's server side only.
    api_token: SecretStr | None = Field(default=None, alias="CORNUCOPIA_API_TOKEN")
    cors_origins: list[str] = Field(default_factory=list, alias="CORNUCOPIA_CORS_ORIGINS")
    # Operator sessions (Phase 6): HS256 signing secret held only by the API.
    session_secret: SecretStr = Field(
        default=SecretStr("dev-only-session-secret-change-me-0123456789"),
        alias="CORNUCOPIA_SESSION_SECRET",
    )
    session_ttl_minutes: int = Field(default=480, ge=5, le=24 * 60, alias="CORNUCOPIA_SESSION_TTL")
    approval_ttl_minutes: int = Field(
        default=240, ge=5, le=24 * 60, alias="CORNUCOPIA_APPROVAL_TTL"
    )

    http_timeout_s: float = Field(default=15.0, alias="CORNUCOPIA_HTTP_TIMEOUT_S")
    http_retries: int = Field(default=3, ge=0, le=6, alias="CORNUCOPIA_HTTP_RETRIES")

    @model_validator(mode="after")
    def _check_transport(self) -> Settings:
        if self.transport is TransportMode.GATEWAY and not self.supabase_gateway_url:
            raise ValueError("SUPABASE_GATEWAY_URL is required when CORNUCOPIA_TRANSPORT=gateway")
        if self.transport is TransportMode.DIRECT:
            if self.environment == "production":
                raise ValueError("direct transport is not allowed in production; use gateway")
            if not (self.supabase_url and self.supabase_secret_key):
                raise ValueError("SUPABASE_URL and SUPABASE_SECRET_KEY are required for direct")
        if self.environment == "production" and self.api_token is None:
            raise ValueError("CORNUCOPIA_API_TOKEN is required in production")
        if self.environment == "production" and (
            "dev-only" in self.session_secret.get_secret_value()
            or len(self.session_secret.get_secret_value()) < 32
        ):
            raise ValueError("a strong CORNUCOPIA_SESSION_SECRET is required in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
