from __future__ import annotations

import random
from decimal import Decimal as D

import pytest

from cornucopia.compiler.calculators import availability, meal_needs, team_capacities, usable_lots
from cornucopia.compiler.compare import compare_plans
from cornucopia.compiler.diet import forbidden_for, violations
from cornucopia.compiler.plan import SubstitutionUse, canonical_json, fingerprint
from cornucopia.compiler.planner import compile_baseline
from cornucopia.compiler.snapshot import parse_snapshot
from cornucopia.compiler.substitutions import options_for, suggestions
from cornucopia.compiler.validator import validate_plan
from cornucopia.depgraph.graph import build_graph, event_origins, impact, nid
from tests.compiler_fixtures import LB, Builder, thanksgiving

# ------------------------------------------------------------------ diet


def test_diet_rules() -> None:
    assert "dairy" in forbidden_for(["vegan"])
    assert violations(["dairy", "gluten"], ["dairy_free"]) == ["dairy"]
    assert violations(["pork"], ["vegetarian", "halal"]) == ["pork"]
    with pytest.raises(ValueError):
        forbidden_for(["paleo"])


# ------------------------------------------------------------ calculators


def test_recipe_requirements_per_meal() -> None:
    b, ids = thanksgiving()
    snap = b.snapshot()
    needs = meal_needs(snap, parse_id(ids["plate"]), ())
    assert needs.portions_per_meal == 3
    rice = needs.ingredient_per_meal[parse_id(ids["rice"])]
    assert rice.quantize(D("0.001")) == (D(12) * LB / 50).quantize(D("0.001"))
    dairy_free = meal_needs(snap, parse_id(ids["plate"]), ("dairy_free",))
    assert parse_id(ids["butter"]) not in dairy_free.ingredient_per_meal
    assert dairy_free.omitted_optional == ["Mashed potatoes: Butter (dairy)"]
    assert dairy_free.feasible_by_definition


def test_availability_ignores_pledged_cancelled_and_stale_lots() -> None:
    b = Builder()
    rice = b.ingredient("Rice")
    b.lot(rice, "10", key="ok", expires_in_h=48)
    b.lot(rice, "5", key="pledged", status="pledged")
    b.lot(rice, "7", key="stale", expires_in_h=-1)  # expired by date, never reported
    b.lot(rice, "3", key="cancelled", status="cancelled")
    snap = b.snapshot()
    assert availability(snap)[parse_id(rice)] == (D(10) * LB).quantize(D("0.001"))
    with_pledged = availability(snap, include_pledged=True)[parse_id(rice)]
    assert with_pledged == ((D(10) * LB).quantize(D("0.001")) + (D(5) * LB).quantize(D("0.001")))


def test_fifo_order_is_earliest_expiry_first() -> None:
    b = Builder()
    rice = b.ingredient("Rice")
    late = b.lot(rice, "10", key="late", expires_in_h=100)
    never = b.lot(rice, "10", key="never")
    soon = b.lot(rice, "10", key="soon", expires_in_h=5)
    order = [str(lot.id) for lot in usable_lots(b.snapshot())]
    assert order == [soon, late, never]


def test_team_capacity_scales_with_available_cooks() -> None:
    b, ids = thanksgiving(cooks=4)
    b.rows["volunteers"][0]["available"] = False
    cap = team_capacities(b.snapshot())[0]
    assert cap.portions == 1500 and cap.notes == ("1 of 4 cooks unavailable",)


# ---------------------------------------------------------- baseline plan


def test_initial_plan_is_feasible_and_validated() -> None:
    b, _ = thanksgiving()
    snap = b.snapshot()
    plan = compile_baseline(snap)
    assert plan.fully_feasible and plan.metrics.meals_planned == 500
    assert plan.shortages == ()
    report = validate_plan(snap, plan)
    assert report.valid, report.violations
    assert report.checks > 20


def test_rice_cancellation_makes_every_plate_infeasible() -> None:
    b, ids = thanksgiving()
    for lot in b.rows["lots"]:
        if lot["id"] == ids["lot_rice"]:
            lot["status"], lot["quantity_base"] = "cancelled", "0"
    snap = b.snapshot()
    plan = compile_baseline(snap)
    assert plan.metrics.meals_planned == 0
    assert all(c.status == "infeasible" for c in plan.commitments)
    assert all("ingredients: Rice" in c.limited_by for c in plan.commitments)
    (short,) = plan.shortages
    assert short.ingredient_id == parse_id(ids["rice"])
    assert short.missing_base == short.required_base  # needs ~120 lb, has none
    assert validate_plan(snap, plan).valid


def test_partial_shortage_is_computed_not_guessed() -> None:
    b, _ = thanksgiving(rice_lb="60")  # 0.24 lb rice per plate -> 250 plates
    snap = b.snapshot()
    plan = compile_baseline(snap)
    by_who = {c.recipient: c for c in plan.commitments}
    assert by_who["Shelter"].planned == 200 and by_who["Shelter"].status == "feasible"
    assert by_who["Senior center"].planned == 50  # 60 lb / 0.24 lb = 250 plates exactly
    assert by_who["Senior center"].status == "partial"
    assert by_who["Family pantry"].planned == 0
    assert plan.metrics.meals_planned == 250
    assert validate_plan(snap, plan).valid


def test_rounding_never_over_allocates_at_the_boundary() -> None:
    b, _ = thanksgiving(rice_lb="59.999")  # just under 250 plates of rice
    snap = b.snapshot()
    plan = compile_baseline(snap)
    assert plan.metrics.meals_planned == 249
    assert validate_plan(snap, plan).valid


def test_preparation_and_delivery_limits() -> None:
    b, ids = thanksgiving(cooks=4)
    for v in b.rows["volunteers"][:3]:
        v["available"] = False  # 1 of 4 cooks -> 500 portions -> 166 plates
    for d in b.rows["deliveries"]:
        if d["id"] == ids["route_c"]:
            d["status"] = "cancelled"
    snap = b.snapshot()
    plan = compile_baseline(snap)
    by_who = {c.recipient: c for c in plan.commitments}
    assert (
        by_who["Shelter"].planned == 166 and "preparation capacity" in by_who["Shelter"].limited_by
    )
    assert by_who["Family pantry"].planned == 0
    assert any("route cancelled" in r for r in by_who["Family pantry"].limited_by)
    assert validate_plan(snap, plan).valid


def test_diet_violation_detected() -> None:
    b, ids = thanksgiving()
    turkey = b.ingredient("Turkey", attrs=("meat", "poultry", "animal_product"))
    b.lot(turkey, "100")
    b.rows["recipe_ingredients"].append(
        {
            "id": "6c0e8d9a-0000-4000-8000-000000000001",
            "recipe_id": ids["pilaf"],
            "ingredient_id": turkey,
            "quantity_base": "1000",
            "optional": False,
        }
    )
    b.commitment("Veg kitchen", ids["plate"], 10, delivery=ids["route_a"], diets=("vegetarian",))
    snap = b.snapshot()
    veg = next(c for c in compile_baseline(snap).commitments if c.recipient == "Veg kitchen")
    assert veg.status == "infeasible"
    assert veg.limited_by == ("diet: Rice pilaf: Turkey (meat, poultry)",)


def test_plan_is_deterministic_and_order_independent() -> None:
    b, _ = thanksgiving(rice_lb="90")
    first = compile_baseline(b.snapshot())
    for seed in range(5):
        rng = random.Random(seed)  # noqa: S311 - test shuffling, not crypto
        shuffled = {k: rng.sample(v, len(v)) for k, v in b.rows.items()}
        snap = parse_snapshot(
            {
                **b.snapshot().model_dump(
                    mode="json", include={"organization_id", "state_version", "as_of"}
                ),
                **shuffled,
            }
        )
        again = compile_baseline(snap)
        assert canonical_json(again) == canonical_json(first)
        assert fingerprint(again) == fingerprint(first)


# -------------------------------------------------------------- validator


def test_validator_catches_tampering() -> None:
    b, ids = thanksgiving()
    snap = b.snapshot()
    plan = compile_baseline(snap)
    over = plan.model_copy(
        update={
            "allocations": tuple(
                a.model_copy(update={"quantity_base": a.quantity_base * 10})
                for a in plan.allocations
            )
        }
    )
    assert any("over-allocated" in v for v in validate_plan(snap, over).violations)
    stale = plan.model_copy(update={"state_version": plan.state_version - 1})
    assert any("state" in v for v in validate_plan(snap, stale).violations)
    lazy = plan.model_copy(update={"teams": ()})
    assert any("teams prepare 0" in v for v in validate_plan(snap, lazy).violations)


def test_substitutions_validated() -> None:
    b, ids = thanksgiving(rice_lb="0.001")
    quinoa = b.ingredient("Quinoa")
    b.lot(quinoa, "200")
    barley = b.ingredient("Barley", attrs=("gluten",))
    b.lot(barley, "200")
    cheese = b.ingredient("Cheese", attrs=("dairy", "animal_product"))
    b.lot(cheese, "200")
    s_q = b.substitution(ids["rice"], quinoa, "1.0", recipe=ids["pilaf"])
    b.substitution(ids["rice"], barley, "1.1")
    b.substitution(ids["rice"], cheese, "1.0")
    b.commitment("GF pantry", ids["plate"], 10, delivery=ids["route_a"], diets=("gluten_free",))
    snap = b.snapshot()
    opts = {
        snap.ingredient[o.substitute_id].name: o
        for o in options_for(snap, parse_id(ids["pilaf"]), parse_id(ids["rice"]))
    }
    assert opts["Quinoa"].valid
    assert not opts["Barley"].valid and "gluten" in opts["Barley"].reasons[0]
    assert not opts["Cheese"].valid  # dairy_free commitment uses the plate
    plan = compile_baseline(snap)
    assert [snap.ingredient[o.substitute_id].name for o in suggestions(snap, plan)] == ["Quinoa"]

    # a substitution outside its recipe scope, with the wrong ratio, is refused
    bad = plan.model_copy(
        update={
            "substitutions": (
                SubstitutionUse(
                    substitution_id=parse_id(s_q),
                    recipe_id=parse_id(ids["mash"]),
                    ingredient_id=parse_id(ids["rice"]),
                    substitute_id=quinoa_id(snap),
                    replaced_base=D("1"),
                    substitute_base=D("2"),
                ),
            )
        }
    )
    errs = validate_plan(snap, bad).violations
    assert any("outside its recipe" in e for e in errs)
    assert any("ratio" in e for e in errs)


# ------------------------------------------------------- dependency graph


def test_rice_cancellation_impact_reaches_every_commitment() -> None:
    b, ids = thanksgiving()
    snap = b.snapshot()
    g = build_graph(snap)
    origins = event_origins("DONATION_CANCELLED", {"donation_id": ids["don_rice"]}, {})
    imp = impact(g, origins)
    kinds = imp.counts
    assert kinds["donation"] == 1 and kinds["lot"] == 1 and kinds["ingredient"] == 1
    assert kinds["recipe"] == 1 and kinds["meal"] == 1 and kinds["commitment"] == 3
    assert nid("recipe", ids["mash"]) not in {n.id for n in imp.nodes}
    assert nid("lot", ids["lot_potatoes"]) not in {n.id for n in imp.nodes}


def test_volunteer_and_commitment_impacts() -> None:
    b, ids = thanksgiving(cooks=2)
    snap = b.snapshot()
    g = build_graph(snap)
    vol = b.rows["volunteers"][0]["id"]
    imp = impact(g, event_origins("VOLUNTEER_UNAVAILABLE", {"volunteer_id": vol}, {}))
    assert imp.counts["team"] == 1 and imp.counts["batch"] == 3 and imp.counts["commitment"] == 3
    imp2 = impact(g, event_origins("COMMITMENT_CHANGED", {"commitment_id": ids["c_shelter"]}, {}))
    roles = {n.id: n.role for n in imp2.nodes}
    assert roles[nid("commitment", ids["c_shelter"])] == "origin"
    assert roles[nid("lot", ids["lot_rice"])] == "upstream"
    assert imp2.affected_commitments == (nid("commitment", ids["c_shelter"]),)
    imp3 = impact(g, event_origins("DELIVERY_CANCELLED", {"delivery_id": ids["route_c"]}, {}))
    assert imp3.affected_commitments == (nid("commitment", ids["c_families"]),)


# --------------------------------------------------------- plan comparison


def test_plan_comparison() -> None:
    b, ids = thanksgiving()
    before = compile_baseline(b.snapshot())
    assert compare_plans(before, before).identical
    b2, _ = thanksgiving(rice_lb="60")
    after = compile_baseline(b2.snapshot())
    diff = compare_plans(before, after)
    assert not diff.identical and diff.meals_planned_delta == -250
    assert diff.commitments_changed == 2
    assert diff == compare_plans(before, after)  # deterministic


# ------------------------------------------------------------------ helpers
def parse_id(s: str):  # type: ignore[no-untyped-def]
    import uuid

    return uuid.UUID(s)


def quinoa_id(snap):  # type: ignore[no-untyped-def]
    return next(i.id for i in snap.ingredients if i.name == "Quinoa")
