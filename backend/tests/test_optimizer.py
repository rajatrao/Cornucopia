from __future__ import annotations

import time
import uuid
from dataclasses import replace

from cornucopia.compiler.plan import fingerprint
from cornucopia.compiler.validator import validate_plan
from cornucopia.optimizer.model import OptimizerConfig, optimize
from cornucopia.optimizer.service import run
from tests.compiler_fixtures import thanksgiving


def _cancel_rice(b, ids) -> None:  # type: ignore[no-untyped-def]
    for lot in b.rows["lots"]:
        if lot["id"] == ids["lot_rice"]:
            lot["status"], lot["quantity_base"] = "cancelled", "0"


def _add_quinoa(b, ids, lb: str = "40") -> str:  # type: ignore[no-untyped-def]
    q = b.ingredient("Quinoa")
    b.lot(q, lb)
    b.substitution(ids["rice"], q, "1.0", recipe=ids["pilaf"])
    return q


def test_full_resources_give_verified_feasible_plan() -> None:
    b, _ = thanksgiving()
    rep = run(b.snapshot())
    assert rep.solver_status == "OPTIMAL" and rep.verdict == "verified_feasible"
    assert rep.plan is not None and rep.plan.metrics.meals_planned == 500
    assert rep.objectives["commitments_met"] == 3 and rep.objectives["meals_served"] == 500
    assert rep.diagnosis.fully_serviceable


def test_rice_cancelled_without_alternatives_is_reported_infeasible() -> None:
    b, ids = thanksgiving()
    _cancel_rice(b, ids)
    rep = run(b.snapshot())
    assert rep.plan is not None and rep.plan.metrics.meals_planned == 0
    assert rep.verdict == "verified_partial"  # a verified plan of what IS possible: nothing
    (sf,) = rep.diagnosis.shortfalls
    assert sf.label == "Rice" and sf.display == "120.0 lb"
    assert "missing: Rice 120.0 lb" in rep.diagnosis.explanation


def test_substitution_recovers_what_the_stock_allows() -> None:
    b, ids = thanksgiving()
    _cancel_rice(b, ids)
    _add_quinoa(b, ids, "40")
    snap = b.snapshot()
    rep = run(snap)
    assert rep.plan is not None
    # 40 lb quinoa at 0.24 lb per plate = 166.67 -> 166 plates; computed, not assumed
    assert rep.plan.metrics.meals_planned == 166
    assert rep.verdict == "verified_partial" and validate_plan(snap, rep.plan).valid
    (sub,) = rep.plan.substitutions
    assert sub.substitute_base == sub.replaced_base  # ratio 1.0
    by = {c.recipient: c for c in rep.plan.commitments}
    # two commitments cannot both be met; 150 + 150 > 166, so exactly one is met in
    # full (a 150-meal one), and the earliest-due tie-break gives the rest to Shelter
    assert sum(c.status == "feasible" for c in rep.plan.commitments) == 1
    assert by["Senior center"].status == "feasible"
    assert by["Shelter"].planned == 16 and by["Family pantry"].planned == 0
    assert "Rice 80.0 lb" in rep.diagnosis.explanation
    names = {c.name: c for c in rep.candidates}
    assert names["baseline"].meals_planned == 0
    assert names["no_substitutions"].meals_planned == 0
    assert names["recommended"].meals_planned == 166
    assert all(c.verdict.startswith("verified") for c in rep.candidates)


def test_enough_substitute_serves_everyone() -> None:
    b, ids = thanksgiving()
    _cancel_rice(b, ids)
    _add_quinoa(b, ids, "125")
    rep = run(b.snapshot())
    assert rep.verdict == "verified_feasible" and rep.plan is not None
    assert rep.plan.metrics.meals_planned == 500


def test_cancelled_route_is_recovered_by_rerouting() -> None:
    b, ids = thanksgiving()
    for d in b.rows["deliveries"]:
        if d["id"] == ids["route_c"]:
            d["status"] = "cancelled"
        else:
            d["capacity_meals"] = 300  # spare capacity elsewhere
    snap = b.snapshot()
    rep = run(snap)
    assert rep.verdict == "verified_feasible" and rep.plan is not None
    moved = [a for a in rep.plan.routing if str(a.commitment_id) == ids["c_families"]]
    assert sum(a.meals for a in moved) == 150
    assert all(str(a.delivery_id) != ids["route_c"] for a in moved)
    assert rep.objectives["delivery_disruption"] == 150
    no_reroute = {c.name: c for c in rep.candidates}["no_rerouting"]
    assert no_reroute.meals_planned == 350


def test_waste_objective_uses_expiring_stock_first() -> None:
    b, ids = thanksgiving()
    _cancel_rice(b, ids)
    q = b.ingredient("Quinoa")
    b.lot(q, "200", key="fresh")
    barley = b.ingredient("Barley")
    b.lot(barley, "130", key="expiring", expires_in_h=24)
    b.substitution(ids["rice"], q, "1.0")
    b.substitution(ids["rice"], barley, "1.0")
    rep = run(b.snapshot())
    assert rep.verdict == "verified_feasible" and rep.plan is not None
    # either single swap is an equally small change; the waste stage picks the
    # substitute that would otherwise spoil within the 72 h horizon
    used = {str(s.substitute_id) for s in rep.plan.substitutions}
    assert used == {barley}
    assert rep.objectives["plan_change"] == 1


def test_diet_conflicts_are_never_optimised_away() -> None:
    b, ids = thanksgiving()
    turkey = b.ingredient("Turkey", attrs=("meat", "poultry", "animal_product"))
    b.lot(turkey, "100")
    b.rows["recipe_ingredients"].append(
        {
            "id": str(uuid.uuid4()),
            "recipe_id": ids["carrot_dish"],
            "ingredient_id": turkey,
            "quantity_base": "100",
            "optional": False,
        }
    )
    b.commitment("Veg kitchen", ids["plate"], 20, delivery=ids["route_a"], diets=("vegetarian",))
    rep = run(b.snapshot())
    veg = next(c for c in rep.plan.commitments if c.recipient == "Veg kitchen")  # type: ignore[union-attr]
    assert veg.planned == 0 and veg.limited_by[0].startswith("diet:")
    assert any("diet" in r for rs in rep.diagnosis.blocked.values() for r in rs)


def test_deterministic_for_fixed_inputs_and_config() -> None:
    b, ids = thanksgiving()
    _cancel_rice(b, ids)
    _add_quinoa(b, ids, "40")
    snap = b.snapshot()
    a = optimize(snap)
    c = optimize(snap)
    assert a.plan is not None and c.plan is not None
    assert fingerprint(a.plan) == fingerprint(c.plan) and a.objectives == c.objectives


def test_unverified_plans_are_never_labelled_feasible() -> None:
    b, _ = thanksgiving()
    snap = b.snapshot()
    rep = run(snap, with_candidates=False)
    assert rep.plan is not None
    bad = rep.plan.model_copy(update={"teams": ()})
    from cornucopia.optimizer.service import _verdict

    verdict, violations, _ = _verdict(snap, bad)
    assert verdict == "unverified" and violations


def test_performance_on_demonstration_dataset() -> None:
    b, ids = thanksgiving()
    _cancel_rice(b, ids)
    _add_quinoa(b, ids, "40")
    snap = b.snapshot()
    t0 = time.perf_counter()
    rep = run(snap, replace(OptimizerConfig(), stage_deterministic_time=5.0))
    elapsed = time.perf_counter() - t0
    assert rep.solver_status == "OPTIMAL"
    assert elapsed < 10, f"full optimisation with candidates took {elapsed:.2f}s"
    assert rep.model_stats["variables"] > 0
