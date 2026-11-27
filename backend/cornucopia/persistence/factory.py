from __future__ import annotations

from cornucopia.config import Settings, TransportMode
from cornucopia.persistence.client import RestSupabaseClient, SupabaseClient
from cornucopia.persistence.memory import InMemorySupabaseClient


def build_client(settings: Settings) -> SupabaseClient:
    """Build exactly the transport the settings ask for. No silent fallback."""
    match settings.transport:
        case TransportMode.GATEWAY:
            assert settings.supabase_gateway_url
            # The Sprites gateway authenticates the calling Sprite and attaches
            # the stored sb_secret_ key; we must not send credentials.
            return RestSupabaseClient(
                settings.supabase_gateway_url,
                schema=settings.db_schema,
                timeout_s=settings.http_timeout_s,
                retries=settings.http_retries,
            )
        case TransportMode.DIRECT:
            assert settings.supabase_url and settings.supabase_secret_key
            return RestSupabaseClient(
                settings.supabase_url,
                schema=settings.db_schema,
                headers={"apikey": settings.supabase_secret_key.get_secret_value()},
                timeout_s=settings.http_timeout_s,
                retries=settings.http_retries,
            )
        case TransportMode.MEMORY:
            return InMemorySupabaseClient()
