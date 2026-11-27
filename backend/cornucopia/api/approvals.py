"""Phase 6 HTTP surface: operator sign-in, approvals, committed plan.

Approval state is never taken from the client: the server re-reads the
request, and the decision RPC re-verifies operator role, fingerprint, the
operational state version, expiry and explicit confirmation in one
transaction. Refused attempts are recorded too.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from cornucopia.api.compiler import labels
from cornucopia.api.operations import Org, Repo, Viewer, db_error
from cornucopia.auth import OperatorIdentity, issue_session, verify_password
from cornucopia.compiler.snapshot import parse_snapshot
from cornucopia.persistence.client import SupabaseError

REFUSAL_HTTP = {
    "unauthorized": 403,
    "duplicate": 409,
    "not_pending": 409,
    "expired": 409,
    "stale": 409,
    "fingerprint_mismatch": 409,
    "confirmation_required": 422,
}


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: Annotated[str, Field(min_length=3, max_length=64, pattern=r"^[a-z0-9._-]+$")]
    password: Annotated[str, Field(min_length=1, max_length=200)]


class LoginOut(BaseModel):
    token: str
    expires_at: datetime
    operator: OperatorIdentity


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject"]
    fingerprint: Annotated[str, Field(min_length=64, max_length=64)]
    state_version: int
    confirm: bool = False
    reason: Annotated[str, Field(max_length=500)] | None = None


def build_router() -> APIRouter:
    r = APIRouter(prefix="/api/v1", tags=["approvals"])

    @r.post("/auth/login", response_model=LoginOut)
    def login(body: LoginIn, request: Request, repo: Repo, org: Org) -> LoginOut:
        rows = repo.list("operators", org.id, filters={"username": f"eq.{body.username}"}, limit=1)
        row = rows[0] if rows else None
        ok = verify_password(row["password_hash"] if row else None, body.password)
        if not ok or row is None or not row.get("active"):
            raise HTTPException(401, "invalid username or password")
        ident = OperatorIdentity.model_validate(row)
        s = request.app.state.settings
        token, exp = issue_session(
            ident, org.id, s.session_secret.get_secret_value(), s.session_ttl_minutes
        )
        return LoginOut(token=token, expires_at=exp, operator=ident)

    @r.get("/auth/me", response_model=OperatorIdentity)
    def me(op: Viewer) -> OperatorIdentity:
        return op

    @r.get("/approvals")
    def list_approvals(repo: Repo, org: Org, op: Viewer, limit: int = 50) -> list[dict[str, Any]]:
        try:
            repo.call("expire_approvals", {"p_organization_id": str(org.id)})
        except SupabaseError as exc:
            raise db_error(exc) from exc
        reqs = repo.list(
            "approval_requests", org.id, order="created_at.desc", limit=max(1, min(limit, 200))
        )
        versions = {
            str(v["id"]): v
            for v in repo.list("plan_versions", org.id, order="created_at.desc", limit=400)
        }
        out = []
        for x in reqs:
            pv = versions.get(str(x["plan_version_id"]), {})
            metrics = (pv.get("plan") or {}).get("metrics", {})
            out.append(
                {
                    **x,
                    "version_number": pv.get("version_number"),
                    "verdict": pv.get("verdict"),
                    "meals_planned": metrics.get("meals_planned"),
                    "meals_requested": metrics.get("meals_requested"),
                }
            )
        return out

    @r.get("/approvals/{request_id}")
    def get_approval(request_id: UUID, repo: Repo, org: Org, op: Viewer) -> dict[str, Any]:
        req = repo.get("approval_requests", org.id, request_id)
        if req is None:
            raise HTTPException(404, "approval request not found")
        pv = repo.get("plan_versions", org.id, UUID(str(req["plan_version_id"])))
        snap = parse_snapshot(repo.snapshot(org.id))
        current = None
        committed_id = next(
            (
                str(s["committed_plan_version_id"])
                for s in repo.list("operational_state", org.id, order="version.desc", limit=1)
                if s.get("committed_plan_version_id")
            ),
            None,
        )
        if committed_id:
            current = repo.get("plan_versions", org.id, UUID(committed_id))
        return {
            "request": req,
            "plan_version": pv,
            "current_plan_version": current,
            "changes": repo.children(
                "plan_changes", "plan_version_id", UUID(str(req["plan_version_id"])), "id.asc"
            ),
            "decisions": repo.children(
                "approval_decisions", "approval_request_id", request_id, "created_at.asc"
            ),
            "operational_state_version": snap.state_version,
            "is_current": snap.state_version == req["state_version"],
            "labels": labels(snap),
        }

    @r.post("/approvals/{request_id}/decision")
    def decide(
        request_id: UUID, body: DecisionIn, repo: Repo, org: Org, op: Viewer
    ) -> dict[str, Any]:
        try:
            res: dict[str, Any] = repo.call(
                "decide_approval",
                {
                    "p_organization_id": str(org.id),
                    "p_request_id": str(request_id),
                    "p_operator_id": str(op.id),
                    "p_decision": body.decision,
                    "p_fingerprint": body.fingerprint,
                    "p_state_version": body.state_version,
                    "p_confirm": body.confirm,
                    "p_reason": body.reason,
                },
            )
        except SupabaseError as exc:
            raise db_error(exc) from exc
        if not res.get("accepted"):
            code = str(res.get("code"))
            raise HTTPException(
                REFUSAL_HTTP.get(code, 409), {"code": code, "status": res.get("status")}
            )
        return res

    @r.get("/plans/current")
    def current_plan(repo: Repo, org: Org, op: Viewer) -> dict[str, Any]:
        st = repo.list("operational_state", org.id, order="version.desc", limit=1)
        pid = st[0].get("committed_plan_version_id") if st else None
        if not pid:
            return {"plan_version": None, "state_version": st[0]["version"] if st else 0}
        return {
            "plan_version": repo.get("plan_versions", org.id, UUID(str(pid))),
            "state_version": st[0]["version"],
        }

    return r
