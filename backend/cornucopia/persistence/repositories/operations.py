"""Operations repository: resources, inventory, events, audit.

Reads use PostgREST tables filtered by organization. Every write is an RPC:
``write_resource`` for master data and ``ingest_event`` for operational
facts, so each write is one audited transaction.
"""

from __future__ import annotations

import builtins
import uuid
from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from cornucopia.persistence.client import JSON, SupabaseClient

Row = dict[str, JSON]


class Organization(BaseModel):
    id: UUID
    slug: str
    name: str


class IngestResult(BaseModel):
    duplicate: bool
    event: Row


class OperationsRepository(ABC):
    @abstractmethod
    def ensure_organization(self, slug: str, name: str) -> Organization: ...

    @abstractmethod
    def state_version(self, org: UUID) -> int: ...

    @abstractmethod
    def list(
        self,
        table: str,
        org: UUID,
        *,
        order: str = "created_at.asc",
        filters: dict[str, str] | None = None,
        limit: int | None = None,
    ) -> list[Row]: ...

    @abstractmethod
    def get(self, table: str, org: UUID, row_id: UUID) -> Row | None: ...

    @abstractmethod
    def write(
        self,
        org: UUID,
        actor: str,
        table: str,
        action: str,
        row_id: UUID | None,
        values: dict[str, Any],
    ) -> Row: ...

    @abstractmethod
    def snapshot(self, org: UUID) -> dict[str, Any]: ...

    @abstractmethod
    def optimization_results(self, run_id: UUID) -> builtins.list[Row]: ...

    @abstractmethod
    def execution_steps(self, execution_id: UUID) -> builtins.list[Row]: ...

    @abstractmethod
    def checkpoints(self, org: UUID, thread_id: str) -> builtins.list[Row]: ...

    @abstractmethod
    def record_optimization_run(
        self, org: UUID, actor: str, run: dict[str, Any], results: builtins.list[dict[str, Any]]
    ) -> UUID: ...

    @abstractmethod
    def ingest_event(
        self,
        org: UUID,
        key: str,
        event_type: str,
        payload: dict[str, Any],
        actor: str,
        correlation_id: UUID,
    ) -> IngestResult: ...


CHILD_PARENTS = {
    "recipe_ingredients": ("recipes", "recipe_id"),
    "meal_components": ("meals", "meal_id"),
}


class SupabaseOperationsRepository(OperationsRepository):
    def __init__(self, db: SupabaseClient) -> None:
        self._db = db

    def ensure_organization(self, slug: str, name: str) -> Organization:
        row = self._db.rpc("ensure_organization", {"p_slug": slug, "p_name": name})
        return Organization.model_validate(row)

    def state_version(self, org: UUID) -> int:
        rows = self._db.select(
            "operational_state",
            filters={"organization_id": f"eq.{org}"},
            columns="version",
            limit=1,
        )
        return int(rows[0]["version"]) if rows else 0

    def list(
        self,
        table: str,
        org: UUID,
        *,
        order: str = "created_at.asc",
        filters: dict[str, str] | None = None,
        limit: int | None = None,
    ) -> list[Row]:
        f = dict(filters or {})
        if table in CHILD_PARENTS:
            parent, col = CHILD_PARENTS[table]
            parents = self._db.select(
                parent, filters={"organization_id": f"eq.{org}"}, columns="id"
            )
            ids = {str(p["id"]) for p in parents}
            rows = self._db.select(table, filters=f, order=order, limit=limit)
            return [r for r in rows if str(r[col]) in ids]
        f["organization_id"] = f"eq.{org}"
        return self._db.select(table, filters=f, order=order, limit=limit)

    def get(self, table: str, org: UUID, row_id: UUID) -> Row | None:
        rows = self.list(table, org, filters={"id": f"eq.{row_id}"}, limit=1)
        return rows[0] if rows else None

    def write(
        self,
        org: UUID,
        actor: str,
        table: str,
        action: str,
        row_id: UUID | None,
        values: dict[str, Any],
    ) -> Row:
        row: Row = self._db.rpc(
            "write_resource",
            {
                "p_organization_id": str(org),
                "p_actor": actor,
                "p_table": table,
                "p_action": action,
                "p_id": str(row_id) if row_id else None,
                "p_values": values,
            },
        )
        return row

    def ingest_event(
        self,
        org: UUID,
        key: str,
        event_type: str,
        payload: dict[str, Any],
        actor: str,
        correlation_id: UUID,
    ) -> IngestResult:
        raw = self._db.rpc(
            "ingest_event",
            {
                "p_organization_id": str(org),
                "p_idempotency_key": key,
                "p_event_type": event_type,
                "p_payload": payload,
                "p_actor": actor,
                "p_correlation_id": str(correlation_id),
            },
        )
        return IngestResult.model_validate(raw)

    def snapshot(self, org: UUID) -> dict[str, Any]:
        raw: dict[str, Any] = self._db.rpc(
            "get_operational_snapshot", {"p_organization_id": str(org)}
        )
        return raw

    def optimization_results(self, run_id: UUID) -> builtins.list[Row]:
        """Results of a run; callers must have checked the run's organization."""
        return self._db.select(
            "optimization_results", filters={"run_id": f"eq.{run_id}"}, order="candidate.asc"
        )

    def execution_steps(self, execution_id: UUID) -> builtins.list[Row]:
        """Steps of an execution; callers must have checked its organization."""
        return self._db.select(
            "agent_execution_steps", filters={"execution_id": f"eq.{execution_id}"}, order="id.asc"
        )

    def checkpoints(self, org: UUID, thread_id: str) -> builtins.list[Row]:
        return self._db.select(
            "agent_checkpoints",
            columns="thread_id,checkpoint_ns,checkpoint_id,parent_checkpoint_id,summary,created_at",
            filters={"organization_id": f"eq.{org}", "thread_id": f"eq.{thread_id}"},
            order="checkpoint_id.asc",
        )

    def record_optimization_run(
        self, org: UUID, actor: str, run: dict[str, Any], results: builtins.list[dict[str, Any]]
    ) -> UUID:
        raw = self._db.rpc(
            "record_optimization_run",
            {"p_organization_id": str(org), "p_actor": actor, "p_run": run, "p_results": results},
        )
        return UUID(str(raw["run_id"]))


def new_correlation_id() -> UUID:
    return uuid.uuid4()
