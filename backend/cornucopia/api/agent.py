"""Phase 5 HTTP surface: agent runtime status and execution history (read-only).

The agent runs in its own Sprite service; the API never executes the graph.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException

from cornucopia.api.operations import Org, Repo


def build_router() -> APIRouter:
    r = APIRouter(prefix="/api/v1/agent", tags=["agent"])

    @r.get("/status")
    def status(repo: Repo, org: Org) -> dict[str, Any]:
        execs = repo.list("agent_executions", org.id, order="created_at.desc", limit=200)
        pending = repo.list(
            "operational_events", org.id, filters={"processing_status": "eq.pending"}, limit=200
        )
        counts: dict[str, int] = {}
        for x in execs:
            counts[str(x["status"])] = counts.get(str(x["status"]), 0) + 1
        beats = [str(x["heartbeat_at"]) for x in execs if x.get("heartbeat_at")]
        last = max(beats) if beats else None
        running = [x for x in execs if x["status"] == "running"]
        return {
            "now": datetime.now(UTC).isoformat(),
            "pending_events": len(pending),
            "executions_by_status": counts,
            "running": len(running),
            "last_heartbeat_at": last,
            "active_workers": sorted(
                {str(x["lease_owner"]) for x in running if x.get("lease_owner")}
            ),
        }

    @r.get("/executions")
    def executions(repo: Repo, org: Org, limit: int = 50) -> list[dict[str, Any]]:
        rows = repo.list(
            "agent_executions", org.id, order="created_at.desc", limit=max(1, min(limit, 200))
        )
        events = {
            str(e["id"]): e
            for e in repo.list("operational_events", org.id, order="created_at.desc", limit=500)
        }
        out = []
        for x in rows:
            ev = events.get(str(x["event_id"]), {})
            out.append(
                {**x, "event_type": ev.get("event_type"), "event_created_at": ev.get("created_at")}
            )
        return out

    @r.get("/executions/{execution_id}")
    def execution(execution_id: UUID, repo: Repo, org: Org) -> dict[str, Any]:
        x = repo.get("agent_executions", org.id, execution_id)
        if x is None:
            raise HTTPException(404, "execution not found")
        ev = repo.get("operational_events", org.id, UUID(str(x["event_id"])))
        return {
            "execution": x,
            "event": ev,
            "steps": repo.execution_steps(execution_id),
            "checkpoints": repo.checkpoints(org.id, str(x["thread_id"])),
        }

    return r
