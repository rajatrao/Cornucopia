"""Baseline planner: deterministic greedy compilation of an operational plan.

Commitments are served in planning order (earliest due first). Each gets the
largest whole number of meals that the remaining ingredients, preparation
capacity and its delivery route allow. Ingredients are then allocated to
lots first-expiring-first. No substitutions are used here; the CP-SAT
optimizer (Phase 4) improves on this baseline.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal
from uuid import UUID

from cornucopia.compiler.calculators import (
    ZERO,
    availability,
    ceil3,
    delivery_capacities,
    full_demand,
    meal_needs,
    team_capacities,
    usable_lots,
)
from cornucopia.compiler.plan import (
    Allocation,
    CommitmentPlan,
    DeliveryLoad,
    Plan,
    PlanMetrics,
    RecipePlan,
    Shortage,
    TeamLoad,
)
from cornucopia.compiler.snapshot import OperationalSnapshot


def ceil_int(v: Decimal) -> int:
    return int(v.to_integral_value(rounding=ROUND_CEILING))


def _max_meals(
    requested: int,
    per_meal: dict[UUID, Decimal],
    used: dict[UUID, Decimal],
    avail: dict[UUID, Decimal],
) -> tuple[int, list[UUID]]:
    """Largest m <= requested with ceil3(used_i + per_i*m) <= avail_i for all i."""

    def fits(m: int) -> bool:
        return all(
            ceil3(used.get(i, ZERO) + p * m) <= avail.get(i, ZERO) for i, p in per_meal.items()
        )

    lo, hi = 0, requested
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fits(mid):
            lo = mid
        else:
            hi = mid - 1
    limiting = (
        []
        if lo == requested
        else [
            i
            for i, p in sorted(per_meal.items(), key=lambda kv: str(kv[0]))
            if ceil3(used.get(i, ZERO) + p * (lo + 1)) > avail.get(i, ZERO)
        ]
    )
    return lo, limiting


def compile_baseline(snap: OperationalSnapshot, *, include_pledged: bool = False) -> Plan:
    avail = availability(snap, include_pledged=include_pledged)
    teams = team_capacities(snap)
    prep_capacity = sum(t.portions for t in teams)
    routes = delivery_capacities(snap)

    used_exact: dict[UUID, Decimal] = {}  # exact (unrounded) ingredient use
    portions_exact = ZERO
    route_used: dict[UUID, int] = {}
    recipe_portions: dict[UUID, Decimal] = {}
    commitments: list[CommitmentPlan] = []

    for c in snap.active_commitments:
        needs = meal_needs(snap, c.meal_id, c.diet_requirements)
        limited: list[str] = []
        risks: list[str] = []
        cap = c.meals_count

        if needs.problems:
            limited += [f"meal: {p}" for p in needs.problems]
            cap = 0
        if needs.diet_violations:
            limited += [f"diet: {v}" for v in needs.diet_violations]
            cap = 0

        route = routes.get(c.delivery_id) if c.delivery_id else None
        if c.delivery_id is None:
            risks.append("no delivery route assigned")
        elif route is None or not route.usable:
            limited.append(f"delivery: {route.reason if route else 'route missing'}")
            cap = 0
        else:
            left = route.meals - route_used.get(route.delivery_id, 0)
            if left < cap:
                limited.append(f"delivery: {route.route_name} capacity")
                cap = max(0, left)
            d = snap.delivery[route.delivery_id]
            if d.departs_at > c.due_at:
                risks.append(f"{route.route_name} departs after the due time")

        ppm = needs.portions_per_meal
        if ppm > 0:
            room = Decimal(prep_capacity) - portions_exact
            by_prep = max(0, int((room / ppm).to_integral_value(rounding="ROUND_FLOOR")))
            while by_prep > 0 and ceil_int(portions_exact + ppm * by_prep) > prep_capacity:
                by_prep -= 1
            if by_prep < cap:
                limited.append("preparation capacity")
                cap = by_prep

        planned, short = _max_meals(cap, needs.ingredient_per_meal, used_exact, avail)
        if planned < cap:
            names = [snap.ingredient[i].name for i in short]
            limited.append("ingredients: " + ", ".join(names))

        for i, p in needs.ingredient_per_meal.items():
            used_exact[i] = used_exact.get(i, ZERO) + p * planned
        portions_exact += ppm * planned
        for r, p in needs.portions_by_recipe.items():
            recipe_portions[r] = recipe_portions.get(r, ZERO) + p * planned
        if route is not None and route.usable:
            route_used[route.delivery_id] = route_used.get(route.delivery_id, 0) + planned

        status = (
            "feasible" if planned == c.meals_count else ("partial" if planned else "infeasible")
        )
        commitments.append(
            CommitmentPlan(
                commitment_id=c.id,
                recipient=c.recipient,
                meal_id=c.meal_id,
                requested=c.meals_count,
                planned=planned,
                status=status,
                delivery_id=c.delivery_id,
                limited_by=tuple(limited),
                risks=tuple(risks),
                omitted_optional=tuple(needs.omitted_optional),
            )
        )

    # --- allocate lots FIFO by expiry
    required = {i: ceil3(v) for i, v in used_exact.items() if v > 0}
    remaining = dict(required)
    allocations: list[Allocation] = []
    for lot in usable_lots(snap, include_pledged=include_pledged):
        need = remaining.get(lot.ingredient_id, ZERO)
        if need <= 0:
            continue
        take = min(need, lot.quantity_base)
        allocations.append(
            Allocation(lot_id=lot.id, ingredient_id=lot.ingredient_id, quantity_base=take)
        )
        remaining[lot.ingredient_id] = need - take
    if any(v > 0 for v in remaining.values()):  # pragma: no cover - guarded by _max_meals
        raise AssertionError("allocation exceeded availability")

    # --- preparation: fill teams in deterministic order
    portions_total = ceil_int(portions_exact)
    loads: list[TeamLoad] = []
    unassigned = portions_total
    for t in teams:
        assign = min(unassigned, t.portions)
        loads.append(TeamLoad(team_id=t.team_id, portions=assign, capacity=t.portions))
        unassigned -= assign

    deliveries = tuple(
        DeliveryLoad(
            delivery_id=r.delivery_id, meals=route_used.get(r.delivery_id, 0), capacity=r.meals
        )
        for r in sorted(routes.values(), key=lambda x: (x.route_name, str(x.delivery_id)))
    )

    demand = full_demand(snap)
    shortages = tuple(
        Shortage(
            ingredient_id=i,
            required_base=req,
            available_base=avail.get(i, ZERO),
            missing_base=req - avail.get(i, ZERO),
        )
        for i, req in sorted(demand.by_ingredient.items(), key=lambda kv: str(kv[0]))
        if req > avail.get(i, ZERO)
    )

    recipes = tuple(
        RecipePlan(recipe_id=r, portions=p, batches=p / snap.recipe[r].yield_portions)
        for r, p in sorted(recipe_portions.items(), key=lambda kv: str(kv[0]))
        if p > 0
    )
    metrics = PlanMetrics(
        meals_requested=sum(c.requested for c in commitments),
        meals_planned=sum(c.planned for c in commitments),
        commitments_total=len(commitments),
        commitments_feasible=sum(c.status == "feasible" for c in commitments),
        commitments_partial=sum(c.status == "partial" for c in commitments),
        commitments_infeasible=sum(c.status == "infeasible" for c in commitments),
        portions_planned=portions_total,
        prep_capacity_portions=prep_capacity,
        ingredient_base_allocated=sum((a.quantity_base for a in allocations), ZERO),
        ingredient_base_available=sum(avail.values(), ZERO),
    )
    return Plan(
        kind="baseline",
        organization_id=snap.organization_id,
        state_version=snap.state_version,
        as_of=snap.as_of,
        include_pledged=include_pledged,
        commitments=tuple(commitments),
        recipes=recipes,
        allocations=tuple(sorted(allocations, key=lambda a: (str(a.ingredient_id), str(a.lot_id)))),
        teams=tuple(loads),
        deliveries=deliveries,
        shortages=shortages,
        metrics=metrics,
    )
