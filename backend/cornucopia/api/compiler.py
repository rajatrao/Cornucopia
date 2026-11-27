"""Phase 3 HTTP surface: baseline plan, impact analysis, dependency graph."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cornucopia.api.operations import Org, Repo, db_error
from cornucopia.compiler.calculators import availability, full_demand, team_capacities
from cornucopia.compiler.plan import Plan, fingerprint
from cornucopia.compiler.planner import compile_baseline
from cornucopia.compiler.snapshot import OperationalSnapshot, parse_snapshot
from cornucopia.compiler.substitutions import suggestions
from cornucopia.compiler.validator import validate_plan
from cornucopia.depgraph.graph import Impact, build_graph, event_origins, impact
from cornucopia.persistence.client import SupabaseError


class Validation(BaseModel):
    valid: bool
    checks: int
    violations: list[str]


class IngredientBalance(BaseModel):
    ingredient_id: UUID
    name: str
    base_unit: str
    required_base: Decimal
    available_base: Decimal
    planned_base: Decimal


class SubstitutionSuggestion(BaseModel):
    substitution_id: UUID
    recipe_id: UUID
    ingredient_id: UUID
    substitute_id: UUID
    ratio: Decimal
    substitute_spare_base: Decimal
    max_replaceable_base: Decimal


class TeamOut(BaseModel):
    team_id: UUID
    name: str
    capacity_portions: int
    notes: list[str]


class PlanReport(BaseModel):
    plan: Plan
    fingerprint: str
    validation: Validation
    labels: dict[str, str]
    ingredients: list[IngredientBalance]
    teams: list[TeamOut]
    substitution_suggestions: list[SubstitutionSuggestion]


class ImpactReport(BaseModel):
    event_id: UUID
    event_type: str
    state_version: int
    impact: Impact


class GraphOut(BaseModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


def labels(snap: OperationalSnapshot) -> dict[str, str]:
    out: dict[str, str] = {}
    for i in snap.ingredients:
        out[str(i.id)] = i.name
    for r in snap.recipes:
        out[str(r.id)] = r.name
    for m in snap.meals:
        out[str(m.id)] = m.name
    for c in snap.commitments:
        out[str(c.id)] = c.recipient
    for t in snap.teams:
        out[str(t.id)] = t.name
    for d in snap.deliveries:
        out[str(d.id)] = d.route_name
    return out


def _snapshot(repo: Any, org_id: UUID) -> OperationalSnapshot:
    try:
        return parse_snapshot(repo.snapshot(org_id))
    except SupabaseError as exc:
        raise db_error(exc) from exc


def build_router() -> APIRouter:
    r = APIRouter(prefix="/api/v1/compiler", tags=["compiler"])

    @r.get("/plan", response_model=PlanReport)
    def baseline(repo: Repo, org: Org, include_pledged: bool = False) -> PlanReport:
        snap = _snapshot(repo, org.id)
        plan = compile_baseline(snap, include_pledged=include_pledged)
        rep = validate_plan(snap, plan)
        avail = availability(snap, include_pledged=include_pledged)
        demand = full_demand(snap)
        planned: dict[UUID, Decimal] = {}
        for a in plan.allocations:
            planned[a.ingredient_id] = planned.get(a.ingredient_id, Decimal(0)) + a.quantity_base
        balances = [
            IngredientBalance(
                ingredient_id=i.id,
                name=i.name,
                base_unit=i.base_unit.value,
                required_base=demand.by_ingredient.get(i.id, Decimal(0)),
                available_base=avail.get(i.id, Decimal(0)),
                planned_base=planned.get(i.id, Decimal(0)),
            )
            for i in sorted(snap.ingredients, key=lambda x: x.name.lower())
            if demand.by_ingredient.get(i.id) or avail.get(i.id)
        ]
        return PlanReport(
            plan=plan,
            fingerprint=fingerprint(plan),
            validation=Validation(valid=rep.valid, checks=rep.checks, violations=rep.violations),
            labels=labels(snap),
            ingredients=balances,
            teams=[
                TeamOut(
                    team_id=t.team_id,
                    name=t.name,
                    capacity_portions=t.portions,
                    notes=list(t.notes),
                )
                for t in team_capacities(snap)
            ],
            substitution_suggestions=[
                SubstitutionSuggestion(
                    **{k: getattr(o, k) for k in SubstitutionSuggestion.model_fields}
                )
                for o in suggestions(snap, plan)
            ],
        )

    @r.get("/impact/{event_id}", response_model=ImpactReport)
    def event_impact(event_id: UUID, repo: Repo, org: Org) -> ImpactReport:
        ev = repo.get("operational_events", org.id, event_id)
        if ev is None:
            raise HTTPException(404, "event not found")
        snap = _snapshot(repo, org.id)
        g = build_graph(snap)
        origins = event_origins(str(ev["event_type"]), dict(ev["payload"]), dict(ev["effect"]))
        return ImpactReport(
            event_id=event_id,
            event_type=str(ev["event_type"]),
            state_version=snap.state_version,
            impact=impact(g, origins),
        )

    @r.get("/graph", response_model=GraphOut)
    def graph(repo: Repo, org: Org) -> GraphOut:
        g = build_graph(_snapshot(repo, org.id))
        return GraphOut(
            nodes=[{"id": n, **d} for n, d in sorted(g.nodes(data=True))],
            edges=[{"source": u, "target": v, **d} for u, v, d in sorted(g.edges(data=True))],
        )

    return r
