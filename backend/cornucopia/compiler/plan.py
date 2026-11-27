"""Plan data model, canonical serialisation and fingerprint."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class _P(BaseModel):
    model_config = ConfigDict(frozen=True)


class CommitmentPlan(_P):
    commitment_id: UUID
    recipient: str
    meal_id: UUID
    requested: int
    planned: int
    status: Literal["feasible", "partial", "infeasible"]
    delivery_id: UUID | None
    limited_by: tuple[str, ...] = ()  # resources that capped the planned count
    risks: tuple[str, ...] = ()  # non-blocking problems (late route, no route, ...)
    omitted_optional: tuple[str, ...] = ()


class RecipePlan(_P):
    recipe_id: UUID
    portions: Decimal
    batches: Decimal  # portions / yield, exact


class Allocation(_P):
    lot_id: UUID
    ingredient_id: UUID
    quantity_base: Decimal


class SubstitutionUse(_P):
    substitution_id: UUID
    recipe_id: UUID
    ingredient_id: UUID
    substitute_id: UUID
    replaced_base: Decimal  # of the original ingredient
    substitute_base: Decimal  # of the substitute (replaced x ratio, rounded up)


class RouteAssignment(_P):
    """Meals of a commitment carried on a delivery route.

    The baseline keeps every commitment on its assigned route; the optimizer
    may move meals to another usable route (a plan change needing approval).
    """

    commitment_id: UUID
    delivery_id: UUID
    meals: int


class TeamLoad(_P):
    team_id: UUID
    portions: int
    capacity: int


class DeliveryLoad(_P):
    delivery_id: UUID
    meals: int
    capacity: int


class Shortage(_P):
    ingredient_id: UUID
    required_base: Decimal  # to serve every active commitment in full
    available_base: Decimal
    missing_base: Decimal


class PlanMetrics(_P):
    meals_requested: int
    meals_planned: int
    commitments_total: int
    commitments_feasible: int
    commitments_partial: int
    commitments_infeasible: int
    portions_planned: int
    prep_capacity_portions: int
    ingredient_base_allocated: Decimal
    ingredient_base_available: Decimal


class Plan(_P):
    """A plan is a proposal. Being computed or even validated never makes it
    approved or committed; those states live in the approval engine."""

    kind: Literal["baseline", "optimized"]
    organization_id: UUID
    state_version: int
    as_of: datetime
    include_pledged: bool
    commitments: tuple[CommitmentPlan, ...]
    recipes: tuple[RecipePlan, ...]
    allocations: tuple[Allocation, ...]
    substitutions: tuple[SubstitutionUse, ...] = ()
    routing: tuple[RouteAssignment, ...] = ()
    teams: tuple[TeamLoad, ...]
    deliveries: tuple[DeliveryLoad, ...]
    shortages: tuple[Shortage, ...]
    metrics: PlanMetrics

    @property
    def fully_feasible(self) -> bool:
        return all(c.status == "feasible" for c in self.commitments)


def _canon(v: object) -> object:
    if isinstance(v, Decimal):
        return format(v.normalize(), "f") if v != 0 else "0"
    if isinstance(v, dict):
        return {k: _canon(x) for k, x in sorted(v.items())}
    if isinstance(v, list | tuple):
        return [_canon(x) for x in v]
    if isinstance(v, UUID | datetime):
        return str(v)
    return v


def canonical_json(plan: Plan) -> str:
    """Byte-stable JSON of the plan's decision content.

    ``as_of`` is excluded: two computations of the same decisions at
    different moments must share a fingerprint. ``state_version`` is included:
    a plan computed against other inputs is a different plan.
    """
    data = plan.model_dump(exclude={"as_of"})
    return json.dumps(_canon(data), sort_keys=True, separators=(",", ":"))


def fingerprint(plan: Plan) -> str:
    return hashlib.sha256(canonical_json(plan).encode()).hexdigest()
