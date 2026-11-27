"""Deterministic plan comparison."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from cornucopia.compiler.calculators import ZERO
from cornucopia.compiler.plan import Plan, fingerprint


class Change(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: str  # commitment | recipe | ingredient | lot | team | delivery | substitution
    id: str
    field: str
    before: str
    after: str


class PlanDiff(BaseModel):
    model_config = ConfigDict(frozen=True)
    before_fingerprint: str
    after_fingerprint: str
    identical: bool
    meals_planned_delta: int
    commitments_changed: int
    changes: tuple[Change, ...]


def _s(v: object) -> str:
    if isinstance(v, Decimal):
        return format(v.normalize(), "f") if v != 0 else "0"
    return str(v)


def _diff_maps(kind: str, field: str, a: dict[str, object], b: dict[str, object]) -> list[Change]:
    out = []
    for k in sorted(set(a) | set(b)):
        x, y = a.get(k, ZERO), b.get(k, ZERO)
        if _s(x) != _s(y):
            out.append(Change(kind=kind, id=k, field=field, before=_s(x), after=_s(y)))
    return out


def compare_plans(before: Plan, after: Plan) -> PlanDiff:
    changes: list[Change] = []
    changes += _diff_maps(
        "commitment",
        "planned",
        {str(c.commitment_id): c.planned for c in before.commitments},
        {str(c.commitment_id): c.planned for c in after.commitments},
    )
    changes += _diff_maps(
        "commitment",
        "status",
        {str(c.commitment_id): c.status for c in before.commitments},
        {str(c.commitment_id): c.status for c in after.commitments},
    )
    changes += _diff_maps(
        "recipe",
        "portions",
        {str(r.recipe_id): r.portions for r in before.recipes},
        {str(r.recipe_id): r.portions for r in after.recipes},
    )

    def by_ing(p: Plan) -> dict[str, object]:
        out: dict[UUID, Decimal] = {}
        for a in p.allocations:
            out[a.ingredient_id] = out.get(a.ingredient_id, ZERO) + a.quantity_base
        return {str(k): v for k, v in out.items()}

    changes += _diff_maps("ingredient", "allocated_base", by_ing(before), by_ing(after))
    changes += _diff_maps(
        "lot",
        "allocated_base",
        {str(a.lot_id): a.quantity_base for a in before.allocations},
        {str(a.lot_id): a.quantity_base for a in after.allocations},
    )
    changes += _diff_maps(
        "team",
        "portions",
        {str(t.team_id): t.portions for t in before.teams},
        {str(t.team_id): t.portions for t in after.teams},
    )
    changes += _diff_maps(
        "delivery",
        "meals",
        {str(d.delivery_id): d.meals for d in before.deliveries},
        {str(d.delivery_id): d.meals for d in after.deliveries},
    )

    def subs(p: Plan) -> dict[str, object]:
        return {
            f"{s.recipe_id}:{s.ingredient_id}->{s.substitute_id}": s.substitute_base
            for s in p.substitutions
        }

    changes += _diff_maps("substitution", "substitute_base", subs(before), subs(after))
    fa, fb = fingerprint(before), fingerprint(after)
    return PlanDiff(
        before_fingerprint=fa,
        after_fingerprint=fb,
        identical=fa == fb,
        meals_planned_delta=after.metrics.meals_planned - before.metrics.meals_planned,
        commitments_changed=len({c.id for c in changes if c.kind == "commitment"}),
        changes=tuple(changes),
    )
