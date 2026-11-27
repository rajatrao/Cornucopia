"""Ingredient substitution engine: which swaps are legal, and how much they cover.

A substitution is valid for a recipe when:
* a rule exists for (ingredient -> substitute) scoped to that recipe or global;
* the substitute violates no diet of any active commitment whose meal uses
  the recipe;
* the substitute is a known ingredient.
Coverage is limited by the substitute's stock left after the plan's own use.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from uuid import UUID

from cornucopia.compiler.calculators import ZERO, availability, ceil3
from cornucopia.compiler.diet import violations
from cornucopia.compiler.plan import Plan
from cornucopia.compiler.snapshot import OperationalSnapshot
from cornucopia.domain.units import BASE_QUANT


@dataclass(frozen=True)
class SubstitutionOption:
    substitution_id: UUID
    recipe_id: UUID
    ingredient_id: UUID
    substitute_id: UUID
    ratio: Decimal
    valid: bool
    reasons: tuple[str, ...]
    substitute_spare_base: Decimal  # substitute stock not used by the plan
    max_replaceable_base: Decimal  # original base units this could replace


def recipe_diets(snap: OperationalSnapshot, recipe_id: UUID) -> set[str]:
    diets: set[str] = set()
    meals = {c.meal_id for c in snap.meal_components if c.recipe_id == recipe_id}
    for c in snap.active_commitments:
        if c.meal_id in meals:
            diets.update(c.diet_requirements)
    return diets


def options_for(
    snap: OperationalSnapshot,
    recipe_id: UUID,
    ingredient_id: UUID,
    *,
    plan: Plan | None = None,
    include_pledged: bool = False,
) -> list[SubstitutionOption]:
    avail = availability(snap, include_pledged=include_pledged)
    used: dict[UUID, Decimal] = {}
    if plan is not None:
        for a in plan.allocations:
            used[a.ingredient_id] = used.get(a.ingredient_id, ZERO) + a.quantity_base
    diets = recipe_diets(snap, recipe_id)
    out = []
    for rule in sorted(snap.substitutions, key=lambda s: (str(s.substitute_id), str(s.id))):
        if rule.ingredient_id != ingredient_id or rule.recipe_id not in (None, recipe_id):
            continue
        reasons: list[str] = []
        sub = snap.ingredient.get(rule.substitute_id)
        if sub is None:
            reasons.append("substitute ingredient missing")
            spare = ZERO
        else:
            bad = violations(sub.attributes, diets)
            if bad:
                reasons.append(f"breaks diets {sorted(diets)} via {', '.join(bad)}")
            spare = max(avail.get(sub.id, ZERO) - used.get(sub.id, ZERO), ZERO)
            if spare <= 0:
                reasons.append(f"no spare {sub.name}")
        max_replace = (spare / rule.ratio).quantize(BASE_QUANT, rounding=ROUND_FLOOR)
        while max_replace > 0 and ceil3(max_replace * rule.ratio) > spare:
            max_replace -= BASE_QUANT
        out.append(
            SubstitutionOption(
                substitution_id=rule.id,
                recipe_id=recipe_id,
                ingredient_id=ingredient_id,
                substitute_id=rule.substitute_id,
                ratio=rule.ratio,
                valid=not reasons,
                reasons=tuple(reasons),
                substitute_spare_base=spare,
                max_replaceable_base=max(max_replace, ZERO),
            )
        )
    return out


def suggestions(snap: OperationalSnapshot, plan: Plan) -> list[SubstitutionOption]:
    """Valid substitutions that could relieve the plan's shortages."""
    short = {s.ingredient_id for s in plan.shortages}
    out = []
    for line in sorted(
        snap.recipe_ingredients, key=lambda x: (str(x.recipe_id), str(x.ingredient_id))
    ):
        if line.ingredient_id in short:
            out += [
                o
                for o in options_for(
                    snap,
                    line.recipe_id,
                    line.ingredient_id,
                    plan=plan,
                    include_pledged=plan.include_pledged,
                )
                if o.valid
            ]
    return out
