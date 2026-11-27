"""Deterministic snapshot builder for compiler tests (test data only)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from typing import Any

from cornucopia.compiler.snapshot import OperationalSnapshot, parse_snapshot

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
LB = D("453.59237")


def uid(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"cornucopia-test/{name}"))


@dataclass
class Builder:
    rows: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    version: int = 1
    t: int = 0

    def _add(self, table: str, row: dict[str, Any]) -> str:
        self.t += 1
        row.setdefault(
            "created_at", (NOW - timedelta(days=1) + timedelta(seconds=self.t)).isoformat()
        )
        self.rows.setdefault(table, []).append(row)
        return str(row["id"])

    def ingredient(self, name: str, base: str = "g", attrs: tuple[str, ...] = ()) -> str:
        return self._add(
            "ingredients",
            {"id": uid(f"ing/{name}"), "name": name, "base_unit": base, "attributes": list(attrs)},
        )

    def lot(
        self,
        ingredient: str,
        lb: str | D,
        *,
        status: str = "available",
        expires_in_h: float | None = None,
        donation: str | None = None,
        key: str = "",
    ) -> str:
        q = (D(str(lb)) * LB).quantize(D("0.001"))
        exp = (
            (NOW + timedelta(hours=expires_in_h)).isoformat() if expires_in_h is not None else None
        )
        return self._add(
            "lots",
            {
                "id": uid(f"lot/{ingredient}/{key or lb}"),
                "ingredient_id": ingredient,
                "donation_id": donation,
                "quantity_base": str(q),
                "base_unit": "g",
                "status": status,
                "expires_at": exp,
            },
        )

    def donation(self, desc: str, status: str = "received") -> str:
        return self._add(
            "donations", {"id": uid(f"don/{desc}"), "description": desc, "status": status}
        )

    def recipe(
        self, name: str, yield_portions: str, lines: dict[str, str], optional: tuple[str, ...] = ()
    ) -> str:
        rid = self._add(
            "recipes",
            {
                "id": uid(f"rec/{name}"),
                "name": name,
                "yield_portions": yield_portions,
                "prep_minutes": 60,
            },
        )
        for ing, lb in lines.items():
            self._add(
                "recipe_ingredients",
                {
                    "id": uid(f"ri/{name}/{ing}"),
                    "recipe_id": rid,
                    "ingredient_id": ing,
                    "quantity_base": str((D(lb) * LB).quantize(D("0.001"))),
                    "optional": ing in optional,
                },
            )
        return rid

    def meal(self, name: str, recipes: dict[str, str]) -> str:
        mid = self._add("meals", {"id": uid(f"meal/{name}"), "name": name})
        for r, portions in recipes.items():
            self._add(
                "meal_components",
                {"id": uid(f"mc/{name}/{r}"), "meal_id": mid, "recipe_id": r, "portions": portions},
            )
        return mid

    def team(self, name: str, rate: str, hours: str, active: bool = True) -> str:
        return self._add(
            "teams",
            {
                "id": uid(f"team/{name}"),
                "name": name,
                "capacity_portions_per_hour": rate,
                "available_hours": hours,
                "active": active,
            },
        )

    def volunteer(
        self, name: str, team: str | None, role: str = "cook", available: bool = True
    ) -> str:
        return self._add(
            "volunteers",
            {
                "id": uid(f"vol/{name}"),
                "name": name,
                "role": role,
                "team_id": team,
                "available": available,
                "available_hours": "4",
            },
        )

    def delivery(
        self, name: str, capacity: int, departs_in_h: float = 5, status: str = "scheduled"
    ) -> str:
        return self._add(
            "deliveries",
            {
                "id": uid(f"del/{name}"),
                "route_name": name,
                "capacity_meals": capacity,
                "departs_at": (NOW + timedelta(hours=departs_in_h)).isoformat(),
                "status": status,
            },
        )

    def commitment(
        self,
        who: str,
        meal: str,
        count: int,
        *,
        due_in_h: float = 6,
        delivery: str | None = None,
        diets: tuple[str, ...] = (),
        status: str = "active",
    ) -> str:
        return self._add(
            "commitments",
            {
                "id": uid(f"com/{who}"),
                "recipient": who,
                "meal_id": meal,
                "meals_count": count,
                "diet_requirements": list(diets),
                "due_at": (NOW + timedelta(hours=due_in_h)).isoformat(),
                "delivery_id": delivery,
                "status": status,
                "version": 1,
            },
        )

    def substitution(
        self, ingredient: str, substitute: str, ratio: str, recipe: str | None = None
    ) -> str:
        return self._add(
            "substitutions",
            {
                "id": uid(f"sub/{ingredient}/{substitute}/{recipe}"),
                "ingredient_id": ingredient,
                "substitute_id": substitute,
                "ratio": ratio,
                "recipe_id": recipe,
            },
        )

    def snapshot(self) -> OperationalSnapshot:
        return parse_snapshot(
            {
                "organization_id": uid("org"),
                "state_version": self.version,
                "as_of": NOW.isoformat(),
                **self.rows,
            }
        )


def thanksgiving(
    rice_lb: str = "180", potatoes_lb: str = "120", carrots_lb: str = "100", cooks: int = 12
) -> tuple[Builder, dict[str, str]]:
    """A small Thanksgiving operation used across compiler tests."""
    b = Builder()
    ids: dict[str, str] = {}
    ids["rice"] = b.ingredient("Rice", attrs=())
    ids["potatoes"] = b.ingredient("Potatoes")
    ids["carrots"] = b.ingredient("Carrots")
    ids["butter"] = b.ingredient("Butter", attrs=("dairy", "animal_product"))
    ids["oil"] = b.ingredient("Olive oil")
    ids["don_rice"] = b.donation("Rice from Harvest Co-op")
    ids["lot_rice"] = b.lot(ids["rice"], rice_lb, donation=ids["don_rice"], expires_in_h=24 * 90)
    ids["lot_potatoes"] = b.lot(ids["potatoes"], potatoes_lb, expires_in_h=24 * 14)
    ids["lot_carrots"] = b.lot(ids["carrots"], carrots_lb, expires_in_h=24 * 10)
    ids["lot_butter"] = b.lot(ids["butter"], "10", expires_in_h=24 * 5)
    ids["lot_oil"] = b.lot(ids["oil"], "10")
    # per batch of 50 portions
    ids["pilaf"] = b.recipe("Rice pilaf", "50", {ids["rice"]: "12"})
    ids["mash"] = b.recipe(
        "Mashed potatoes",
        "50",
        {ids["potatoes"]: "12", ids["butter"]: "1"},
        optional=(ids["butter"],),
    )
    ids["carrot_dish"] = b.recipe("Roasted carrots", "50", {ids["carrots"]: "8"})
    ids["plate"] = b.meal(
        "Thanksgiving plate", {ids["pilaf"]: "1", ids["mash"]: "1", ids["carrot_dish"]: "1"}
    )
    ids["team"] = b.team("Main kitchen", "250", "8")
    for n in range(cooks):
        b.volunteer(f"Cook {n:02d}", ids["team"])
    ids["route_a"] = b.delivery("Route A", 200)
    ids["route_b"] = b.delivery("Route B", 200)
    ids["route_c"] = b.delivery("Route C", 200)
    ids["c_shelter"] = b.commitment("Shelter", ids["plate"], 200, delivery=ids["route_a"])
    ids["c_seniors"] = b.commitment(
        "Senior center",
        ids["plate"],
        150,
        delivery=ids["route_b"],
        diets=("dairy_free",),
        due_in_h=7,
    )
    ids["c_families"] = b.commitment(
        "Family pantry", ids["plate"], 150, delivery=ids["route_c"], due_in_h=8
    )
    return b, ids
