"""Independent plan feasibility validator.

Recomputes every quantity from the snapshot and the plan's decisions
(planned meals, substitutions, allocations) and checks every hard
constraint. It shares only the low-level calculators with the planner, never
the planner's bookkeeping, so a planner or optimizer bug cannot certify
itself. A plan is labelled feasible only when this returns no violations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from cornucopia.compiler.calculators import (
    ZERO,
    ceil3,
    delivery_capacities,
    meal_needs,
    team_capacities,
    usable_lots,
)
from cornucopia.compiler.diet import violations as diet_violations
from cornucopia.compiler.plan import Plan
from cornucopia.compiler.planner import ceil_int
from cornucopia.compiler.snapshot import OperationalSnapshot


@dataclass
class ValidationReport:
    violations: list[str] = field(default_factory=list)
    checks: int = 0

    @property
    def valid(self) -> bool:
        return not self.violations

    def check(self, ok: bool, message: str) -> None:
        self.checks += 1
        if not ok:
            self.violations.append(message)


def validate_plan(snap: OperationalSnapshot, plan: Plan) -> ValidationReport:
    rep = ValidationReport()
    rep.check(
        plan.state_version == snap.state_version,
        f"plan computed against state v{plan.state_version}, current is v{snap.state_version}",
    )
    commitments = {c.id: c for c in snap.commitments}

    exact_by_ing: dict[UUID, Decimal] = {}
    exact_by_recipe_ing: dict[tuple[UUID, UUID], Decimal] = {}
    diets_by_recipe: dict[UUID, set[str]] = {}
    portions_exact = ZERO
    route_meals: dict[UUID, int] = {}

    for cp in plan.commitments:
        c = commitments.get(cp.commitment_id)
        rep.check(c is not None, f"commitment {cp.commitment_id} does not exist")
        if c is None:
            continue
        rep.check(c.status == "active", f"{c.recipient}: commitment is {c.status}")
        rep.check(
            0 <= cp.planned <= c.meals_count,
            f"{c.recipient}: planned {cp.planned} outside 0..{c.meals_count}",
        )
        rep.check(cp.requested == c.meals_count, f"{c.recipient}: requested count is stale")
        expected = (
            "feasible" if cp.planned == c.meals_count else "partial" if cp.planned else "infeasible"
        )
        rep.check(cp.status == expected, f"{c.recipient}: status {cp.status} should be {expected}")
        if cp.planned == 0:
            continue
        needs = meal_needs(snap, c.meal_id, c.diet_requirements)
        rep.check(not needs.problems, f"{c.recipient}: meal unusable: {needs.problems}")
        rep.check(
            not needs.diet_violations, f"{c.recipient}: meal breaks diet: {needs.diet_violations}"
        )
        for ing, per in needs.ingredient_per_meal.items():
            exact_by_ing[ing] = exact_by_ing.get(ing, ZERO) + per * cp.planned
        for comp in snap.components_by_meal.get(c.meal_id, ()):
            diets_by_recipe.setdefault(comp.recipe_id, set()).update(c.diet_requirements)
            recipe = snap.recipe[comp.recipe_id]
            for line in snap.lines_by_recipe.get(recipe.id, ()):
                attrs = snap.ingredient[line.ingredient_id].attributes
                if line.optional and diet_violations(attrs, c.diet_requirements):
                    continue
                key = (recipe.id, line.ingredient_id)
                exact_by_recipe_ing[key] = exact_by_recipe_ing.get(key, ZERO) + (
                    line.quantity_base * comp.portions * cp.planned / recipe.yield_portions
                )
        portions_exact += needs.portions_per_meal * cp.planned

    # ---- substitutions
    rules = {s.id: s for s in snap.substitutions}
    required = {i: ceil3(v) for i, v in exact_by_ing.items()}
    for su in plan.substitutions:
        rule = rules.get(su.substitution_id)
        rep.check(rule is not None, f"substitution rule {su.substitution_id} does not exist")
        if rule is None:
            continue
        rep.check(
            rule.ingredient_id == su.ingredient_id and rule.substitute_id == su.substitute_id,
            "substitution does not match its rule",
        )
        rep.check(rule.recipe_id in (None, su.recipe_id), "substitution used outside its recipe")
        rep.check(su.replaced_base > 0, "substitution replaces nothing")
        rep.check(
            su.substitute_base == ceil3(su.replaced_base * rule.ratio),
            "substitute quantity does not follow the rule's ratio",
        )
        need = exact_by_recipe_ing.get((su.recipe_id, su.ingredient_id), ZERO)
        rep.check(
            su.replaced_base <= ceil3(need), "substitution replaces more than the recipe needs"
        )
        sub_attrs = snap.ingredient[su.substitute_id].attributes
        bad = diet_violations(sub_attrs, diets_by_recipe.get(su.recipe_id, set()))
        rep.check(not bad, f"substitute breaks diet: {bad}")
        required[su.ingredient_id] = required.get(su.ingredient_id, ZERO) - su.replaced_base
        required[su.substitute_id] = required.get(su.substitute_id, ZERO) + su.substitute_base

    # ---- allocations
    usable = {lot.id: lot for lot in usable_lots(snap, include_pledged=plan.include_pledged)}
    per_lot: dict[UUID, Decimal] = {}
    allocated: dict[UUID, Decimal] = {}
    for a in plan.allocations:
        lot = usable.get(a.lot_id)
        rep.check(lot is not None, f"lot {a.lot_id} is not usable")
        rep.check(a.quantity_base > 0, "zero or negative allocation")
        if lot is None:
            continue
        rep.check(lot.ingredient_id == a.ingredient_id, "allocation ingredient does not match lot")
        per_lot[a.lot_id] = per_lot.get(a.lot_id, ZERO) + a.quantity_base
        allocated[a.ingredient_id] = allocated.get(a.ingredient_id, ZERO) + a.quantity_base
    for lot_id, q in per_lot.items():
        rep.check(q <= usable[lot_id].quantity_base, f"lot {lot_id} over-allocated")
    for ing in sorted(set(required) | set(allocated), key=str):
        need = max(required.get(ing, ZERO), ZERO)
        got = allocated.get(ing, ZERO)
        name = snap.ingredient[ing].name if ing in snap.ingredient else str(ing)
        rep.check(got == need, f"{name}: allocated {got} but plan needs {need}")

    # ---- preparation capacity
    caps = {t.team_id: t.portions for t in team_capacities(snap)}
    total_load = 0
    for t in plan.teams:
        rep.check(t.team_id in caps, f"team {t.team_id} unknown")
        rep.check(0 <= t.portions <= caps.get(t.team_id, 0), f"team {t.team_id} over capacity")
        total_load += t.portions
    rep.check(
        total_load >= ceil_int(portions_exact),
        f"teams prepare {total_load} portions but plan needs {ceil_int(portions_exact)}",
    )

    # ---- delivery: every planned meal of a routed commitment rides a usable route
    routed: dict[UUID, int] = {}
    for ra in plan.routing:
        rep.check(ra.meals > 0, "empty route assignment")
        route_meals[ra.delivery_id] = route_meals.get(ra.delivery_id, 0) + ra.meals
        routed[ra.commitment_id] = routed.get(ra.commitment_id, 0) + ra.meals
    for cp in plan.commitments:
        c = commitments.get(cp.commitment_id)
        if c is None or cp.planned == 0:
            continue
        if c.delivery_id is not None or cp.commitment_id in routed:
            rep.check(
                routed.get(cp.commitment_id, 0) == cp.planned,
                f"{c.recipient}: {routed.get(cp.commitment_id, 0)} meals routed, "
                f"{cp.planned} planned",
            )
    routes = delivery_capacities(snap)
    for rid, meals in route_meals.items():
        r = routes.get(rid)
        rep.check(r is not None and r.usable, f"route {rid} unusable but carries meals")
        if r is not None:
            rep.check(meals <= r.meals, f"{r.route_name}: {meals} meals > capacity {r.meals}")
    return rep
