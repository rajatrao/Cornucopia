"""Run the optimizer end to end: solve, verify, diagnose, compare candidates."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Literal

from pydantic import BaseModel

from cornucopia.compiler.compare import PlanDiff, compare_plans
from cornucopia.compiler.plan import Plan, fingerprint
from cornucopia.compiler.planner import compile_baseline
from cornucopia.compiler.snapshot import OperationalSnapshot
from cornucopia.compiler.validator import validate_plan
from cornucopia.optimizer.diagnosis import diagnose
from cornucopia.optimizer.model import OptimizationOutcome, OptimizerConfig, optimize

Verdict = Literal["verified_feasible", "verified_partial", "unverified", "failed"]


class StageOut(BaseModel):
    name: str
    status: str
    objective: int | None
    wall_ms: float
    deterministic_time: float


class CandidateOut(BaseModel):
    name: str
    description: str
    verdict: Verdict
    fingerprint: str | None
    meals_planned: int
    commitments_feasible: int
    substitutions_used: int
    meals_rerouted: int
    objectives: dict[str, int]
    violations: list[str]
    diff_vs_recommended: PlanDiff | None = None


class ShortfallOut(BaseModel):
    resource: str
    id: str | None
    label: str
    missing: str
    unit: str
    display: str


class DiagnosisOut(BaseModel):
    status: str
    fully_serviceable: bool
    shortfalls: list[ShortfallOut]
    blocked: dict[str, list[str]]
    explanation: str


class OptimizationReport(BaseModel):
    """What the agent and the UI consume. ``verdict`` is the only feasibility
    label: it is ``verified_*`` only if the independent validator agreed."""

    state_version: int
    config: dict[str, Any]
    solver_status: str
    verdict: Verdict
    plan: Plan | None
    fingerprint: str | None
    validation_checks: int
    violations: list[str]
    stages: list[StageOut]
    objectives: dict[str, int]
    model_stats: dict[str, int]
    wall_ms: float
    diagnosis: DiagnosisOut
    candidates: list[CandidateOut]


def _verdict(snap: OperationalSnapshot, plan: Plan | None) -> tuple[Verdict, list[str], int]:
    if plan is None:
        return "failed", ["solver returned no solution"], 0
    rep = validate_plan(snap, plan)
    if not rep.valid:
        return "unverified", rep.violations, rep.checks
    return ("verified_feasible" if plan.fully_feasible else "verified_partial"), [], rep.checks


def _candidate(
    name: str,
    desc: str,
    snap: OperationalSnapshot,
    plan: Plan | None,
    objectives: dict[str, int],
    recommended: Plan | None,
) -> CandidateOut:
    verdict, violations, _ = _verdict(snap, plan)
    moved = 0
    if plan is not None:
        orig = {c.commitment_id: c.delivery_id for c in plan.commitments}
        moved = sum(a.meals for a in plan.routing if orig.get(a.commitment_id) != a.delivery_id)
    return CandidateOut(
        name=name,
        description=desc,
        verdict=verdict,
        fingerprint=fingerprint(plan) if plan else None,
        meals_planned=plan.metrics.meals_planned if plan else 0,
        commitments_feasible=plan.metrics.commitments_feasible if plan else 0,
        substitutions_used=len(plan.substitutions) if plan else 0,
        meals_rerouted=moved,
        objectives=objectives,
        violations=violations,
        diff_vs_recommended=compare_plans(recommended, plan) if plan and recommended else None,
    )


def run(
    snap: OperationalSnapshot,
    cfg: OptimizerConfig | None = None,
    reference: Plan | None = None,
    *,
    with_candidates: bool = True,
) -> OptimizationReport:
    cfg = cfg or OptimizerConfig()
    out: OptimizationOutcome = optimize(snap, cfg, reference)
    verdict, violations, checks = _verdict(snap, out.plan)
    if out.status == "FEASIBLE" and verdict.startswith("verified"):
        pass  # time-limited but still independently verified; status reported as FEASIBLE
    diag = diagnose(snap, cfg)
    candidates: list[CandidateOut] = []
    if with_candidates:
        base = compile_baseline(snap, include_pledged=cfg.include_pledged)
        candidates.append(
            _candidate(
                "baseline",
                "Greedy baseline: no substitutions, no rerouting",
                snap,
                base,
                {},
                out.plan,
            )
        )
        for name, desc, variant in (
            (
                "no_substitutions",
                "Optimizer without ingredient substitutions",
                replace(cfg, use_substitutions=False),
            ),
            (
                "no_rerouting",
                "Optimizer keeping every commitment on its route",
                replace(cfg, allow_rerouting=False),
            ),
        ):
            alt = optimize(snap, variant, reference)
            candidates.append(_candidate(name, desc, snap, alt.plan, alt.objectives, out.plan))
        candidates.append(
            _candidate(
                "recommended",
                "Optimizer with all recovery options",
                snap,
                out.plan,
                out.objectives,
                None,
            )
        )
    return OptimizationReport(
        state_version=snap.state_version,
        config=cfg.as_dict(),
        solver_status=out.status,
        verdict=verdict,
        plan=out.plan,
        fingerprint=fingerprint(out.plan) if out.plan else None,
        validation_checks=checks,
        violations=violations,
        stages=[StageOut(**s.__dict__) for s in out.stages],
        objectives=out.objectives,
        model_stats=out.model_stats,
        wall_ms=out.wall_ms,
        diagnosis=DiagnosisOut(
            status=diag.status,
            fully_serviceable=diag.fully_serviceable,
            shortfalls=[
                ShortfallOut(
                    resource=s.resource,
                    id=s.id,
                    label=s.label,
                    missing=format(s.missing.normalize(), "f"),
                    unit=s.unit,
                    display=s.display,
                )
                for s in diag.shortfalls
            ],
            blocked=diag.blocked,
            explanation=diag.explanation,
        ),
        candidates=candidates,
    )
