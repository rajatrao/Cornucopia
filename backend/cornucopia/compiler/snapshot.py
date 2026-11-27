"""Typed, immutable view of an organization's operational state."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from functools import cached_property
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from cornucopia.domain.units import IngredientPhysics, Unit


class _M(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class SIngredient(_M):
    id: UUID
    name: str
    base_unit: Unit
    density_g_per_ml: Decimal | None = None
    unit_weight_g: Decimal | None = None
    attributes: tuple[str, ...] = ()

    @property
    def physics(self) -> IngredientPhysics:
        return IngredientPhysics(self.density_g_per_ml, self.unit_weight_g)


class SLot(_M):
    id: UUID
    ingredient_id: UUID
    donation_id: UUID | None = None
    quantity_base: Decimal
    base_unit: Unit
    status: str
    expires_at: datetime | None = None
    created_at: datetime


class SDonation(_M):
    id: UUID
    description: str
    status: str


class SRecipe(_M):
    id: UUID
    name: str
    yield_portions: Decimal
    prep_minutes: int


class SRecipeLine(_M):
    id: UUID
    recipe_id: UUID
    ingredient_id: UUID
    quantity_base: Decimal
    optional: bool = False


class SSubstitution(_M):
    id: UUID
    ingredient_id: UUID
    substitute_id: UUID
    ratio: Decimal
    recipe_id: UUID | None = None


class SMeal(_M):
    id: UUID
    name: str


class SMealComponent(_M):
    id: UUID
    meal_id: UUID
    recipe_id: UUID
    portions: Decimal


class SCommitment(_M):
    id: UUID
    recipient: str
    meal_id: UUID
    meals_count: int
    diet_requirements: tuple[str, ...] = ()
    due_at: datetime
    delivery_id: UUID | None = None
    status: str
    version: int
    created_at: datetime


class STeam(_M):
    id: UUID
    name: str
    capacity_portions_per_hour: Decimal
    available_hours: Decimal
    active: bool


class SVolunteer(_M):
    id: UUID
    name: str
    role: str
    team_id: UUID | None = None
    available: bool
    available_hours: Decimal


class SDelivery(_M):
    id: UUID
    route_name: str
    capacity_meals: int
    departs_at: datetime
    status: str
    delay_minutes: int = 0


class OperationalSnapshot(_M):
    organization_id: UUID
    state_version: int
    as_of: datetime
    ingredients: tuple[SIngredient, ...] = ()
    lots: tuple[SLot, ...] = ()
    donations: tuple[SDonation, ...] = ()
    recipes: tuple[SRecipe, ...] = ()
    recipe_ingredients: tuple[SRecipeLine, ...] = ()
    substitutions: tuple[SSubstitution, ...] = ()
    meals: tuple[SMeal, ...] = ()
    meal_components: tuple[SMealComponent, ...] = ()
    commitments: tuple[SCommitment, ...] = ()
    teams: tuple[STeam, ...] = ()
    volunteers: tuple[SVolunteer, ...] = ()
    deliveries: tuple[SDelivery, ...] = Field(default=())

    # ---- indexes (cached; the model is frozen) -------------------------
    @cached_property
    def ingredient(self) -> dict[UUID, SIngredient]:
        return {i.id: i for i in self.ingredients}

    @cached_property
    def recipe(self) -> dict[UUID, SRecipe]:
        return {r.id: r for r in self.recipes}

    @cached_property
    def meal(self) -> dict[UUID, SMeal]:
        return {m.id: m for m in self.meals}

    @cached_property
    def delivery(self) -> dict[UUID, SDelivery]:
        return {d.id: d for d in self.deliveries}

    @cached_property
    def team(self) -> dict[UUID, STeam]:
        return {t.id: t for t in self.teams}

    @cached_property
    def lines_by_recipe(self) -> dict[UUID, tuple[SRecipeLine, ...]]:
        out: dict[UUID, list[SRecipeLine]] = {}
        for line in sorted(self.recipe_ingredients, key=lambda x: str(x.id)):
            out.setdefault(line.recipe_id, []).append(line)
        return {k: tuple(v) for k, v in out.items()}

    @cached_property
    def components_by_meal(self) -> dict[UUID, tuple[SMealComponent, ...]]:
        out: dict[UUID, list[SMealComponent]] = {}
        for c in sorted(self.meal_components, key=lambda x: str(x.id)):
            out.setdefault(c.meal_id, []).append(c)
        return {k: tuple(v) for k, v in out.items()}

    @cached_property
    def active_commitments(self) -> tuple[SCommitment, ...]:
        """Planning order: earliest due first, then creation, then id."""
        return tuple(
            sorted(
                (c for c in self.commitments if c.status == "active"),
                key=lambda c: (c.due_at, c.created_at, str(c.id)),
            )
        )


def parse_snapshot(raw: dict[str, Any]) -> OperationalSnapshot:
    return OperationalSnapshot.model_validate(raw)
