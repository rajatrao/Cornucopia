"""Demo reset endpoints (enabled only when CORNUCOPIA_DEMO_RESET_ROLE is set).

``GET`` reports whether a reset is available and how the last one went; it
needs only the service token, because a running reset invalidates every
existing session and the UI keeps polling through that. ``POST`` needs a
signed-in operator with at least the configured role.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from cornucopia.api.operations import current_operator
from cornucopia.auth import OperatorIdentity
from cornucopia.demo.reset import DemoReset, ResetBusy


def _reset(request: Request) -> DemoReset:
    r: DemoReset = request.app.state.demo_reset
    return r


def build_router() -> APIRouter:
    r = APIRouter(prefix="/api/v1/admin", tags=["demo"])

    @r.get("/demo-reset")
    def status(request: Request, reset: Annotated[DemoReset, Depends(_reset)]) -> dict[str, Any]:
        role = request.app.state.settings.demo_reset_role
        return {"enabled": role is not None, "required_role": role, **reset.status}

    @r.post("/demo-reset", status_code=202)
    def start(
        request: Request,
        reset: Annotated[DemoReset, Depends(_reset)],
        op: Annotated[OperatorIdentity, Depends(current_operator)],
    ) -> dict[str, Any]:
        role = request.app.state.settings.demo_reset_role
        if role is None:
            raise HTTPException(404, "demo reset is not enabled on this deployment")
        if not op.at_least(role):
            raise HTTPException(403, f"requires the {role} role")
        try:
            return reset.start(op, background=request.app.state.demo_reset_background)
        except ResetBusy as exc:
            raise HTTPException(409, str(exc)) from exc

    return r
