"""Repository interfaces and their Supabase implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from cornucopia.persistence.client import SupabaseClient


class Probe(BaseModel):
    id: UUID
    note: str
    source: str
    created_at: datetime


class DbHealth(BaseModel):
    ok: bool
    schema_name: str
    server_time: datetime
    backend: str | None = None


class SystemRepository(ABC):
    @abstractmethod
    def health(self) -> DbHealth: ...

    @abstractmethod
    def record_probe(self, note: str, source: str) -> Probe: ...

    @abstractmethod
    def get_probe(self, probe_id: UUID) -> Probe | None: ...

    @abstractmethod
    def recent_probes(self, limit: int = 10) -> list[Probe]: ...


class SupabaseSystemRepository(SystemRepository):
    def __init__(self, db: SupabaseClient) -> None:
        self._db = db

    def health(self) -> DbHealth:
        raw: dict[str, Any] = self._db.rpc("health_check")
        return DbHealth(
            ok=bool(raw["ok"]),
            schema_name=raw["schema"],
            server_time=raw["server_time"],
            backend=raw.get("backend"),
        )

    def record_probe(self, note: str, source: str) -> Probe:
        # Written through an RPC so the write path exercised here is the same
        # one later transactional operations use.
        row = self._db.rpc("record_probe", {"p_note": note, "p_source": source})
        return Probe.model_validate(row)

    def get_probe(self, probe_id: UUID) -> Probe | None:
        rows = self._db.select("system_probes", filters={"id": f"eq.{probe_id}"}, limit=1)
        return Probe.model_validate(rows[0]) if rows else None

    def recent_probes(self, limit: int = 10) -> list[Probe]:
        rows = self._db.select("system_probes", order="created_at.desc", limit=limit)
        return [Probe.model_validate(r) for r in rows]
