"""Seed a clearly labelled SAMPLE Thanksgiving operation through the public API.

Everything goes through the same validated endpoints the UI uses (resources
CRUD + operational events), so seeded data is audited like any other change.
Idempotent: existing records (matched by name) are reused, donation events
use fixed idempotency keys.

    CORNUCOPIA_API_URL=http://localhost:8000 CORNUCOPIA_API_TOKEN=... \
    CORNUCOPIA_USERNAME=raj CORNUCOPIA_PASSWORD=... \
      uv run --project backend python scripts/seed_sample.py --label "[sample] "

This is demonstration data. It must only be loaded into a development or
demonstration organization.
"""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="[sample] ", help="prefix for every seeded name")
    ap.add_argument("--day", default=None, help="service date YYYY-MM-DD (default: tomorrow)")
    ap.add_argument("--quinoa-lb", default="40", help="pantry quinoa donated by the grocer")
    args = ap.parse_args()
    p = args.label
    base = os.environ.get("CORNUCOPIA_API_URL", "http://localhost:8000").rstrip("/")
    token = os.environ["CORNUCOPIA_API_TOKEN"]
    http = httpx.Client(base_url=f"{base}/api/v1", timeout=60,
                        # fresh connection per request: long-lived keep-alive
                        # connections through the Sprite URL proxy can stall
                        limits=httpx.Limits(max_keepalive_connections=0),
                        headers={"Authorization": f"Bearer {token}"})
    login = http.post("/auth/login", json={"username": os.environ["CORNUCOPIA_USERNAME"],
                                           "password": os.environ["CORNUCOPIA_PASSWORD"]})
    if login.is_error:
        raise SystemExit(f"sign-in failed: {login.status_code}")
    http.headers["X-Cornucopia-Session"] = login.json()["token"]

    day = (datetime.fromisoformat(args.day).replace(tzinfo=UTC) if args.day
           else (datetime.now(UTC) + timedelta(days=1)).replace(hour=0, minute=0, second=0,
                                                                  microsecond=0))

    def at(h: int, m: int = 0) -> str:
        return (day + timedelta(hours=h, minutes=m)).isoformat()

    def existing(kind: str, key: str, value: str) -> dict[str, Any] | None:
        for row in http.get(f"/resources/{kind}").raise_for_status().json():
            if row.get(key) == value:
                return dict(row)
        return None

    def ensure(kind: str, body: dict[str, Any], key: str = "name") -> str:
        found = existing(kind, key, body[key])
        if found:
            return str(found["id"])
        r = http.post(f"/resources/{kind}", json=body)
        if r.is_error:
            raise SystemExit(f"{kind} {body[key]}: {r.status_code} {r.text}")
        return str(r.json()["id"])

    def line(recipe: str, ingredient: str, qty: str, unit: str, optional: bool = False) -> None:
        rows = http.get("/resources/recipe-ingredients").raise_for_status().json()
        if any(x["recipe_id"] == recipe and x["ingredient_id"] == ingredient for x in rows):
            return
        http.post("/resources/recipe-ingredients", json={
            "recipe_id": recipe, "ingredient_id": ingredient, "quantity": qty, "unit": unit,
            "optional": optional}).raise_for_status()

    def component(meal: str, recipe: str) -> None:
        rows = http.get("/resources/meal-components").raise_for_status().json()
        if not any(x["meal_id"] == meal and x["recipe_id"] == recipe for x in rows):
            http.post("/resources/meal-components",
                      json={"meal_id": meal, "recipe_id": recipe, "portions": "1"}).raise_for_status()

    ing = {
        "rice": ensure("ingredients", {"name": f"{p}Rice", "category": "grain", "base_unit": "g",
                                       "density_g_per_ml": "0.85"}),
        "quinoa": ensure("ingredients", {"name": f"{p}Quinoa", "category": "grain",
                                         "base_unit": "g"}),
        "potatoes": ensure("ingredients", {"name": f"{p}Potatoes", "category": "vegetable",
                                           "base_unit": "g", "unit_weight_g": "213"}),
        "carrots": ensure("ingredients", {"name": f"{p}Carrots", "category": "vegetable",
                                          "base_unit": "g"}),
        "butter": ensure("ingredients", {"name": f"{p}Butter", "category": "dairy",
                                         "base_unit": "g",
                                         "attributes": ["dairy", "animal_product"]}),
        "oil": ensure("ingredients", {"name": f"{p}Olive oil", "category": "fat",
                                      "base_unit": "ml", "density_g_per_ml": "0.91"}),
    }
    donors = {
        "coop": ensure("donors", {"name": f"{p}Harvest Co-op", "kind": "farm"}),
        "grocer": ensure("donors", {"name": f"{p}Main Street Grocer", "kind": "business"}),
    }
    rec = {
        "pilaf": ensure("recipes", {"name": f"{p}Rice pilaf", "yield_portions": "50",
                                    "prep_minutes": 45}),
        "mash": ensure("recipes", {"name": f"{p}Mashed potatoes", "yield_portions": "50",
                                   "prep_minutes": 60}),
        "carrots": ensure("recipes", {"name": f"{p}Roasted carrots", "yield_portions": "50",
                                      "prep_minutes": 40}),
    }
    line(rec["pilaf"], ing["rice"], "12", "lb")
    line(rec["pilaf"], ing["oil"], "2", "cup")
    line(rec["mash"], ing["potatoes"], "12", "lb")
    line(rec["mash"], ing["butter"], "1", "lb", optional=True)
    line(rec["carrots"], ing["carrots"], "8", "lb")
    line(rec["carrots"], ing["oil"], "1", "cup")
    subs = http.get("/resources/substitutions").raise_for_status().json()
    if not any(s["ingredient_id"] == ing["rice"] and s["substitute_id"] == ing["quinoa"]
               for s in subs):
        http.post("/resources/substitutions", json={
            "ingredient_id": ing["rice"], "substitute_id": ing["quinoa"], "ratio": "1.0",
            "recipe_id": rec["pilaf"], "notes": "Quinoa cooks like rice 1:1 by dry weight"},
        ).raise_for_status()

    meal = ensure("meals", {"name": f"{p}Thanksgiving plate",
                            "description": "Rice pilaf, mashed potatoes, roasted carrots"})
    for r in rec.values():
        component(meal, r)

    team = ensure("teams", {"name": f"{p}Main kitchen", "capacity_portions_per_hour": "200",
                            "available_hours": "8"})
    for n in range(1, 13):
        role = "cook" if n <= 8 else "driver" if n <= 11 else "coordinator"
        ensure("volunteers", {"name": f"{p}Volunteer {n:02d}", "role": role,
                              "team_id": team if role == "cook" else None})

    routes = [
        ensure("deliveries", {"route_name": f"{p}Route {x}", "capacity_meals": 200,
                              "departs_at": at(15, 30)}, key="route_name")
        for x in ("North", "Central", "South")
    ]
    for who, n, route, diets in (
        ("Riverside Shelter", 200, routes[0], []),
        ("Oak Street Senior Center", 150, routes[1], ["dairy_free"]),
        ("Eastside Family Pantry", 150, routes[2], []),
    ):
        ensure("commitments", {"recipient": f"{p}{who}", "meal_id": meal, "meals_count": n,
                               "diet_requirements": diets, "due_at": at(17),
                               "delivery_id": route}, key="recipient")

    def donate(key: str, desc: str, donor: str, lots: list[tuple[str, str, str, int]]) -> None:
        r = http.post("/events", json={"idempotency_key": key, "event": {
            "type": "DONATION_CREATED", "description": desc, "donor_id": donor, "received": True,
            "lots": [{"ingredient_id": i, "quantity": q, "unit": u,
                      "expires_at": (day + timedelta(days=d)).isoformat()} for i, q, u, d in lots],
        }})
        if r.is_error:
            raise SystemExit(f"donation {key}: {r.status_code} {r.text}")

    slug = p.strip().strip("[]").replace(" ", "-") or "seed"
    donate(f"seed-{slug}-rice-0001", f"{p}Rice donation", donors["coop"],
           [(ing["rice"], "180", "lb", 180)])
    donate(f"seed-{slug}-produce-0001", f"{p}Produce donation", donors["coop"],
           [(ing["potatoes"], "120", "lb", 21), (ing["carrots"], "100", "lb", 14)])
    donate(f"seed-{slug}-pantry-0001", f"{p}Pantry staples", donors["grocer"],
           [(ing["butter"], "10", "lb", 20), (ing["oil"], "2", "gal", 365),
            (ing["quinoa"], args.quinoa_lb, "lb", 365)])
    plan = http.get("/compiler/plan").raise_for_status().json()
    m = plan["plan"]["metrics"]
    print(f"seeded. baseline: {m['meals_planned']}/{m['meals_requested']} meals, "
          f"valid={plan['validation']['valid']}, fingerprint={plan['fingerprint'][:12]}")


if __name__ == "__main__":
    main()
