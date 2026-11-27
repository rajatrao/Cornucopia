"""Phase 4 HTTP surface: run the CP-SAT optimizer and read past runs."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from cornucopia.api.compiler import _snapshot, labels
from cornucopia.api.operations import Actor, Org, Repo, db_error
from cornucopia.optimizer.model import OptimizerConfig
from cornucopia.optimizer.service import OptimizationReport, run
from cornucopia.persistence.client import SupabaseError


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    include_pledged: bool = False
    use_substitutions: bool = True
    allow_rerouting: bool = True
    waste_horizon_hours: int = Field(default=72, ge=0, le=24 * 30)
    stage_deterministic_time: float = Field(default=10.0, gt=0, le=60)
    correlation_id: UUID | None = None


class RunOut(BaseModel):
    run_id: UUID
    labels: dict[str, str]
    report: OptimizationReport


class RunSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: UUID
    state_version: int
    requested_by: str
    solver_status: str
    verdict: str
    objectives: dict[str, Any]
    wall_ms: Decimal
    created_at: str


def build_router() -> APIRouter:
    r = APIRouter(prefix="/api/v1/optimizer", tags=["optimizer"])

    @r.post("/runs", response_model=RunOut, status_code=201)
    def create_run(body: RunRequest, repo: Repo, org: Org, who: Actor) -> RunOut:
        snap = _snapshot(repo, org.id)
        cfg = OptimizerConfig(
            include_pledged=body.include_pledged,
            use_substitutions=body.use_substitutions,
            allow_rerouting=body.allow_rerouting,
            waste_horizon_hours=body.waste_horizon_hours,
            stage_deterministic_time=body.stage_deterministic_time,
        )
        rep = run(snap, cfg)
        run_row = {
            "state_version": rep.state_version,
            "config": rep.config,
            "correlation_id": str(body.correlation_id) if body.correlation_id else None,
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
        try:
            run_id = repo.record_optimization_run(org.id, who, run_row, results)
        except SupabaseError as exc:
            raise db_error(exc) from exc
        return RunOut(run_id=run_id, labels=labels(snap), report=rep)

    @r.get("/runs", response_model=list[RunSummary])
    def list_runs(repo: Repo, org: Org, limit: int = 20) -> list[RunSummary]:
        rows = repo.list(
            "optimization_runs", org.id, order="created_at.desc", limit=max(1, min(limit, 100))
        )
        return [RunSummary.model_validate({**x, "created_at": str(x["created_at"])}) for x in rows]

    @r.get("/runs/{run_id}")
    def get_run(run_id: UUID, repo: Repo, org: Org) -> dict[str, Any]:
        run_row = repo.get("optimization_runs", org.id, run_id)
        if run_row is None:
            raise HTTPException(404, "run not found")
        return {"run": run_row, "results": repo.optimization_results(run_id)}

    return r
