"""Requirement, availability and capacity calculators."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from uuid import UUID

from cornucopia.compiler.diet import violations
from cornucopia.compiler.snapshot import OperationalSnapshot, SLot
from cornucopia.domain.units import BASE_QUANT

ZERO = Decimal(0)


def ceil3(v: Decimal) -> Decimal:
    """Round a consumption up to storage precision (never under-allocate)."""
    return v.quantize(BASE_QUANT, rounding=ROUND_CEILING)


def floor_int(v: Decimal) -> int:
    return int(v.to_integral_value(rounding=ROUND_FLOOR))


# --------------------------------------------------------------- meal recipe
@dataclass(frozen=True)
class MealNeeds:
    """What one meal of a given meal type needs, for a given set of diets."""

    meal_id: UUID
    portions_by_recipe: dict[UUID, Decimal]  # portions per meal
    ingredient_per_meal: dict[UUID, Decimal]  # base units per meal (exact)
    diet_violations: list[str]  # "Recipe: ingredient (attr)" for required lines
    omitted_optional: list[str]  # optional lines left out to satisfy diets
    problems: list[str]  # structural problems (no components, ...)

    @property
    def portions_per_meal(self) -> Decimal:
        return sum(self.portions_by_recipe.values(), ZERO)

    @property
    def feasible_by_definition(self) -> bool:
        return not self.diet_violations and not self.problems


def meal_needs(snap: OperationalSnapshot, meal_id: UUID, diets: tuple[str, ...]) -> MealNeeds:
    portions: dict[UUID, Decimal] = {}
    per_meal: dict[UUID, Decimal] = {}
    viol: list[str] = []
    omitted: list[str] = []
    problems: list[str] = []
    components = snap.components_by_meal.get(meal_id, ())
    if not components:
        problems.append("meal has no recipe components")
    for comp in components:
        recipe = snap.recipe.get(comp.recipe_id)
        if recipe is None:
            problems.append(f"recipe {comp.recipe_id} missing")
            continue
        portions[recipe.id] = portions.get(recipe.id, ZERO) + comp.portions
        lines = snap.lines_by_recipe.get(recipe.id, ())
        if not lines:
            problems.append(f"{recipe.name} has no ingredients")
        for line in lines:
            ing = snap.ingredient[line.ingredient_id]
            bad = violations(ing.attributes, diets)
            if bad:
                label = f"{recipe.name}: {ing.name} ({', '.join(bad)})"
                (omitted if line.optional else viol).append(label)
                if line.optional:
                    continue
            need = line.quantity_base * comp.portions / recipe.yield_portions
            per_meal[ing.id] = per_meal.get(ing.id, ZERO) + need
    return MealNeeds(meal_id, portions, per_meal, viol, omitted, problems)


# ------------------------------------------------------------- availability
def usable_lots(snap: OperationalSnapshot, *, include_pledged: bool = False) -> list[SLot]:
    """Lots the planner may consume, in FIFO order (earliest expiry first).

    A lot whose expiry is at or before the snapshot time is unusable even if
    nobody reported it expired. Ties break on creation time then id, so the
    order is total and reproducible.
    """
    ok_status = {"available", "pledged"} if include_pledged else {"available"}
    lots = [
        lot
        for lot in snap.lots
        if lot.status in ok_status
        and lot.quantity_base > 0
        and (lot.expires_at is None or lot.expires_at > snap.as_of)
    ]
    far = snap.as_of.replace(year=9999)
    return sorted(lots, key=lambda x: (x.expires_at or far, x.created_at, str(x.id)))


def availability(
    snap: OperationalSnapshot, *, include_pledged: bool = False
) -> dict[UUID, Decimal]:
    out: dict[UUID, Decimal] = {i.id: ZERO for i in snap.ingredients}
    for lot in usable_lots(snap, include_pledged=include_pledged):
        out[lot.ingredient_id] = out.get(lot.ingredient_id, ZERO) + lot.quantity_base
    return out


# --------------------------------------------------------------- capacity
@dataclass(frozen=True)
class TeamCapacity:
    team_id: UUID
    name: str
    portions: int
    rate: Decimal
    hours: Decimal
    staffing: Decimal  # fraction of assigned cooks still available
    notes: tuple[str, ...] = ()


def team_capacities(snap: OperationalSnapshot) -> list[TeamCapacity]:
    """Portions each team can prepare in this operation.

    capacity = rate (portions/hour) x available hours x staffing, where
    staffing = available cooks / assigned cooks when the team has cooks
    assigned (1.0 when none are assigned, i.e. capacity was entered as a
    team figure). Rounded down to whole portions.
    """
    out = []
    for t in sorted(snap.teams, key=lambda x: (x.name, str(x.id))):
        notes: list[str] = []
        if not t.active:
            out.append(
                TeamCapacity(
                    t.id,
                    t.name,
                    0,
                    t.capacity_portions_per_hour,
                    t.available_hours,
                    ZERO,
                    ("team inactive",),
                )
            )
            continue
        cooks = [v for v in snap.volunteers if v.team_id == t.id and v.role == "cook"]
        staffing = Decimal(1)
        if cooks:
            available = [v for v in cooks if v.available]
            staffing = Decimal(len(available)) / Decimal(len(cooks))
            if len(available) < len(cooks):
                notes.append(f"{len(cooks) - len(available)} of {len(cooks)} cooks unavailable")
        portions = floor_int(t.capacity_portions_per_hour * t.available_hours * staffing)
        out.append(
            TeamCapacity(
                t.id,
                t.name,
                portions,
                t.capacity_portions_per_hour,
                t.available_hours,
                staffing,
                tuple(notes),
            )
        )
    return out


@dataclass(frozen=True)
class DeliveryCapacity:
    delivery_id: UUID
    route_name: str
    meals: int
    usable: bool
    reason: str | None = None


def delivery_capacities(snap: OperationalSnapshot) -> dict[UUID, DeliveryCapacity]:
    out = {}
    for d in snap.deliveries:
        if d.status in ("cancelled", "completed"):
            out[d.id] = DeliveryCapacity(d.id, d.route_name, 0, False, f"route {d.status}")
        else:
            out[d.id] = DeliveryCapacity(d.id, d.route_name, d.capacity_meals, True)
    return out


@dataclass
class Demand:
    """Total demand if every active commitment were served in full."""

    by_ingredient: dict[UUID, Decimal] = field(default_factory=dict)
    portions: Decimal = ZERO
    meals: int = 0


def full_demand(snap: OperationalSnapshot) -> Demand:
    d = Demand()
    for c in snap.active_commitments:
        needs = meal_needs(snap, c.meal_id, c.diet_requirements)
        d.meals += c.meals_count
        d.portions += needs.portions_per_meal * c.meals_count
        for ing, per in needs.ingredient_per_meal.items():
            d.by_ingredient[ing] = d.by_ingredient.get(ing, ZERO) + ceil3(per * c.meals_count)
    return d
