"""Phase 7/8 HTTP surface: command center, reality recompilation, simulation
laboratory, notifications. Aggregates server-side so each screen is one
round trip from the browser and one consistent snapshot."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from cornucopia.api.compiler import _snapshot, labels
from cornucopia.api.operations import Org, Repo
from cornucopia.compiler.calculators import availability, full_demand
from cornucopia.compiler.planner import compile_baseline
from cornucopia.depgraph.graph import build_graph, event_origins, impact
from cornucopia.simulation.scenarios import SCENARIOS, simulate

ScenarioKey = Literal[
    "donation_cancellation",
    "ingredient_shortage",
    "volunteer_shortage",
    "delivery_disruption",
    "multiple_failures",
]


class SimulationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: ScenarioKey


def _agent_status(repo: Any, org: UUID) -> dict[str, Any]:
    workers = repo.list("agent_workers", org, order="last_seen_at.desc", limit=10)
    now = datetime.now(UTC)
    live = [
        w
        for w in workers
        if w["status"] == "running"
        and (now - datetime.fromisoformat(str(w["last_seen_at"]))).total_seconds() < 90
    ]
    return {
        "workers": workers,
        "live_workers": len(live),
        "last_seen_at": workers[0]["last_seen_at"] if workers else None,
    }


def build_router() -> APIRouter:
    r = APIRouter(prefix="/api/v1", tags=["command"])

    @r.get("/command-center")
    def command_center(repo: Repo, org: Org) -> dict[str, Any]:
        snap = _snapshot(repo, org.id)
        base = compile_baseline(snap)
        avail = availability(snap)
        demand = full_demand(snap)
        inventory = []
        for i in sorted(snap.ingredients, key=lambda x: x.name.lower()):
            need, have = demand.by_ingredient.get(i.id, Decimal(0)), avail.get(i.id, Decimal(0))
            if need == 0 and have == 0:
                continue
            inventory.append(
                {
                    "ingredient_id": str(i.id),
                    "name": i.name,
                    "base_unit": i.base_unit.value,
                    "required_base": str(need),
                    "available_base": str(have),
                    "coverage": float(min(have / need, Decimal(9.99))) if need else None,
                }
            )
        st = repo.list("operational_state", org.id, order="version.desc", limit=1)
        committed_id = st[0].get("committed_plan_version_id") if st else None
        committed = (
            repo.get("plan_versions", org.id, UUID(str(committed_id))) if committed_id else None
        )
        execs = repo.list("agent_executions", org.id, order="created_at.desc", limit=50)
        approvals = repo.list(
            "approval_requests",
            org.id,
            filters={"status": "eq.pending"},
            order="created_at.desc",
            limit=20,
        )
        events = repo.list("operational_events", org.id, order="created_at.desc", limit=10)
        notes = repo.list("operator_notifications", org.id, order="created_at.desc", limit=10)
        return {
            "organization": org.model_dump(mode="json"),
            "state_version": snap.state_version,
            "meals_committed": base.metrics.meals_requested,
            "meals_feasible_now": base.metrics.meals_planned,
            "committed_plan": (
                {
                    "version_number": committed["version_number"],
                    "meals_planned": committed["plan"]["metrics"]["meals_planned"],
                    "committed_at": committed.get("committed_at"),
                    "fingerprint": committed["fingerprint"],
                }
                if committed
                else None
            ),
            "commitments": [c.model_dump(mode="json") for c in base.commitments],
            "inventory": inventory,
            "shortages": [
                {
                    "ingredient_id": str(s.ingredient_id),
                    "name": snap.ingredient[s.ingredient_id].name,
                    "missing_base": str(s.missing_base),
                    "base_unit": snap.ingredient[s.ingredient_id].base_unit.value,
                }
                for s in base.shortages
            ],
            "agent": {
                **_agent_status(repo, org.id),
                "running": [x for x in execs if x["status"] == "running"],
                "recent": execs[:8],
            },
            "pending_approvals": approvals,
            "recent_events": events,
            "notifications": notes,
        }

    @r.get("/recompilation/{execution_id}")
    def recompilation(execution_id: UUID, repo: Repo, org: Org) -> dict[str, Any]:
        ex = repo.get("agent_executions", org.id, execution_id)
        if ex is None:
            raise HTTPException(404, "execution not found")
        ev = repo.get("operational_events", org.id, UUID(str(ex["event_id"])))
        snap = _snapshot(repo, org.id)
        imp = None
        if ev is not None:
            try:
                origins = event_origins(
                    str(ev["event_type"]), dict(ev["payload"]), dict(ev["effect"])
                )
                imp = impact(build_graph(snap), origins).model_dump(mode="json")
            except (KeyError, ValueError):
                imp = None
        runs = repo.list(
            "optimization_runs",
            org.id,
            order="created_at.desc",
            limit=50,
            filters={"correlation_id": f"eq.{ex['correlation_id']}"},
        )
        run = runs[0] if runs else None
        results = repo.optimization_results(UUID(str(run["id"]))) if run else []
        rec = next((x for x in results if x["recommended"]), None)
        req = next(
            iter(
                repo.list(
                    "approval_requests",
                    org.id,
                    filters={"execution_id": f"eq.{execution_id}"},
                    limit=1,
                )
            ),
            None,
        )
        changes = (
            repo.children(
                "plan_changes", "plan_version_id", UUID(str(req["plan_version_id"])), "id.asc"
            )
            if req
            else []
        )
        return {
            "execution": ex,
            "event": ev,
            "steps": repo.execution_steps(execution_id),
            "impact": imp,
            "run": run,
            "candidates": [
                {k: x[k] for k in ("candidate", "verdict", "meals_planned", "fingerprint")}
                for x in results
            ],
            "proposed_plan": rec["plan"] if rec else None,
            "approval_request": req,
            "changes": changes,
            "labels": labels(snap),
            "current_state_version": snap.state_version,
        }

    @r.get("/simulations/scenarios")
    def scenarios() -> list[dict[str, str]]:
        return [
            {"key": s.key, "title": s.title, "description": s.description}
            for s in SCENARIOS.values()
        ]

    @r.post("/simulations")
    def run_simulation(body: SimulationIn, repo: Repo, org: Org) -> dict[str, Any]:
        """Read-only: runs on a copy of the snapshot and persists nothing."""
        snap = _snapshot(repo, org.id)
        out = simulate(snap, body.scenario)
        out["labels"] = labels(snap)
        return out

    @r.get("/notifications")
    def notifications(repo: Repo, org: Org, limit: int = 20) -> list[dict[str, Any]]:
        return repo.list(
            "operator_notifications", org.id, order="created_at.desc", limit=max(1, min(limit, 100))
        )

    return r
