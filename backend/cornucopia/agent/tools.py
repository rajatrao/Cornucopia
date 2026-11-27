"""Explicit tool interfaces the agent graph is allowed to use.

The graph never touches the database or the optimizer directly; it calls
these narrow, typed operations. Tests substitute fakes; production uses
``SupabaseAgentTools`` over the repository (and therefore the connector).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from cornucopia.compiler.snapshot import OperationalSnapshot, parse_snapshot
from cornucopia.optimizer.model import OptimizerConfig
from cornucopia.optimizer.service import OptimizationReport, run
from cornucopia.persistence.client import SupabaseClient
from cornucopia.persistence.repositories.operations import OperationsRepository


class LeaseLost(RuntimeError):  # noqa: N818 - domain name
    """A newer attempt owns this execution; this worker must stop immediately."""


class ApprovalEngineUnavailable(RuntimeError):  # noqa: N818
    """Commits require the Phase 6 approval engine."""


@dataclass(frozen=True)
class ExecutionContext:
    organization_id: UUID
    execution_id: UUID
    event_id: UUID
    correlation_id: UUID
    thread_id: str
    worker: str
    attempt: int

    @property
    def actor(self) -> str:
        return f"agent:{self.worker}"


class AgentTools(ABC):
    """Everything the graph may do, and nothing more."""

    ctx: ExecutionContext

    @abstractmethod
    def load_event(self) -> dict[str, Any]: ...

    @abstractmethod
    def snapshot(self) -> OperationalSnapshot: ...

    @abstractmethod
    def optimize(
        self, cfg: OptimizerConfig, idempotency_key: str
    ) -> tuple[UUID, OptimizationReport]:
        """Solve, verify, diagnose, compare; persist the run idempotently."""

    @abstractmethod
    def record_step(self, node: str, status: str, detail: dict[str, Any]) -> None:
        """Fenced execution history; raises LeaseLost if this worker was superseded."""

    def commit_plan(self, run_id: UUID, approval: dict[str, Any]) -> dict[str, Any]:
        raise ApprovalEngineUnavailable("plan commits are implemented by the approval engine")


class SupabaseAgentTools(AgentTools):
    def __init__(
        self, db: SupabaseClient, repo: OperationsRepository, ctx: ExecutionContext
    ) -> None:
        self.db, self.repo, self.ctx = db, repo, ctx

    def load_event(self) -> dict[str, Any]:
        row = self.repo.get("operational_events", self.ctx.organization_id, self.ctx.event_id)
        if row is None:
            raise LookupError(f"event {self.ctx.event_id} not found")
        return dict(row)

    def snapshot(self) -> OperationalSnapshot:
        return parse_snapshot(self.repo.snapshot(self.ctx.organization_id))

    def optimize(
        self, cfg: OptimizerConfig, idempotency_key: str
    ) -> tuple[UUID, OptimizationReport]:
        snap = self.snapshot()
        rep = run(snap, cfg)
        run_row = {
            "state_version": rep.state_version,
            "config": rep.config,
            "correlation_id": str(self.ctx.correlation_id),
            "idempotency_key": idempotency_key,
            "solver_status": rep.solver_status,
            "verdict": rep.verdict,
            "objectives": rep.objectives,
            "stages": [s.model_dump(mode="json") for s in rep.stages],
            "model_stats": rep.model_stats,
            "diagnosis": rep.diagnosis.model_dump(mode="json"),
            "wall_ms": rep.wall_ms,
        }
        results = [
            {
                "candidate": c.name,
                "recommended": c.name == "recommended",
                "verdict": c.verdict,
                "fingerprint": c.fingerprint,
                "meals_planned": c.meals_planned,
                "plan": rep.plan.model_dump(mode="json")
                if c.name == "recommended" and rep.plan
                else None,
                "summary": c.model_dump(mode="json", exclude={"diff_vs_recommended"}),
            }
            for c in rep.candidates
        ]
        run_id = self.repo.record_optimization_run(
            self.ctx.organization_id, self.ctx.actor, run_row, results
        )
        return run_id, rep

    def record_step(self, node: str, status: str, detail: dict[str, Any]) -> None:
        ok = self.db.rpc(
            "record_execution_step",
            {
                "p_execution_id": str(self.ctx.execution_id),
                "p_worker": self.ctx.worker,
                "p_attempt": self.ctx.attempt,
                "p_node": node,
                "p_status": status,
                "p_detail": detail,
            },
        )
        if ok is not True:
            raise LeaseLost(
                f"execution {self.ctx.execution_id} attempt {self.ctx.attempt} "
                "no longer holds the lease"
            )
