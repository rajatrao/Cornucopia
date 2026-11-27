"""Runtime configuration.

Transport selection is explicit. Production on the Sprite uses the Sprites
Supabase connector gateway, which injects the Supabase secret key server side,
so no database credential exists on the Sprite. ``direct`` mode is for local
development only and reads the key from a gitignored ``.env``. ``memory`` mode
is for tests. The app never falls back from one mode to another.
"""

from __future__ import annotations

import json
import os
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal

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

    # Which organization is active can be switched at runtime by the in-app
    # demo reset. The switch is written to this file (shared by the API and
    # the worker on the Sprite) and overrides the slug/name above.
    active_org_file: Path | None = Field(default=None, alias="CORNUCOPIA_ACTIVE_ORG_FILE")
    # Minimum role allowed to reset the demo from the UI; unset disables it.
    demo_reset_role: Literal["operator", "approver", "admin"] | None = Field(
        default=None, alias="CORNUCOPIA_DEMO_RESET_ROLE"
    )
    # How the API reaches itself to load the sample data during a reset.
    self_url: str = Field(default="http://127.0.0.1:8000", alias="CORNUCOPIA_SELF_URL")

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

    def active_org(self) -> tuple[str, str]:
        """(slug, name) of the organization this deployment operates now."""
        f = self.active_org_file
        if f is not None and f.is_file():
            try:
                data = json.loads(f.read_text())
                return str(data["slug"]), str(data["name"])
            except (OSError, ValueError, KeyError):
                pass
        return self.org_slug, self.org_name

    def set_active_org(self, slug: str, name: str) -> None:
        f = self.active_org_file
        if f is None:
            return
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps({"slug": slug, "name": name}))
        tmp.chmod(0o600)
        os.replace(tmp, f)

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
