"""Simulation Laboratory: predefined disruptions applied to a COPY of the
current operational snapshot.

Nothing here writes to the database: the snapshot is immutable and each
scenario builds a modified copy, then runs the same optimizer and dependency
analysis the agent uses. Results are returned to the caller only, so they can
never be mistaken for (or leak into) production records.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from cornucopia.compiler.snapshot import OperationalSnapshot
from cornucopia.depgraph.graph import build_graph, impact, nid
from cornucopia.optimizer.model import OptimizerConfig
from cornucopia.optimizer.service import OptimizationReport, run


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    description: str
    apply: Callable[[OperationalSnapshot], tuple[OperationalSnapshot, list[str], list[str]]]


def _replace(snap: OperationalSnapshot, **changes: Any) -> OperationalSnapshot:
    data = snap.model_dump()
    data.update(changes)
    return OperationalSnapshot.model_validate(data)


def _largest_donation(
    snap: OperationalSnapshot,
) -> tuple[OperationalSnapshot, list[str], list[str]]:
    sizes: dict[Any, Decimal] = {}
    for lot in snap.lots:
        if lot.donation_id and lot.status == "available":
            sizes[lot.donation_id] = sizes.get(lot.donation_id, Decimal(0)) + lot.quantity_base
    if not sizes:
        return snap, ["no received donation to cancel"], []
    target = max(sizes, key=lambda d: (sizes[d], str(d)))
    desc = next((d.description for d in snap.donations if d.id == target), str(target))
    lots = [
        lot.model_copy(update={"status": "cancelled", "quantity_base": Decimal(0)})
        if lot.donation_id == target
        else lot
        for lot in snap.lots
    ]
    return _replace(snap, lots=lots), [f"Cancelled donation: {desc}"], [nid("donation", target)]


def _ingredient_shortage(
    snap: OperationalSnapshot,
) -> tuple[OperationalSnapshot, list[str], list[str]]:
    use: dict[Any, int] = {}
    for line in snap.recipe_ingredients:
        use[line.ingredient_id] = use.get(line.ingredient_id, 0) + 1
    stock = {
        i: sum(
            (
                x.quantity_base
                for x in snap.lots
                if x.ingredient_id == i and x.status == "available"
            ),
            Decimal(0),
        )
        for i in use
    }
    candidates = [i for i in use if stock.get(i, 0) > 0]
    if not candidates:
        return snap, ["no stocked recipe ingredient"], []
    target = max(candidates, key=lambda i: (use[i], stock[i], str(i)))
    lots = [
        lot.model_copy(update={"quantity_base": (lot.quantity_base / 2).quantize(Decimal("0.001"))})
        if lot.ingredient_id == target and lot.status == "available"
        else lot
        for lot in snap.lots
    ]
    name = snap.ingredient[target].name
    origins = [nid("lot", x.id) for x in snap.lots if x.ingredient_id == target]
    return _replace(snap, lots=lots), [f"Half of the {name} stock spoiled"], origins


def _volunteer_shortage(
    snap: OperationalSnapshot,
) -> tuple[OperationalSnapshot, list[str], list[str]]:
    cooks = sorted(
        (v for v in snap.volunteers if v.role == "cook" and v.available),
        key=lambda v: (v.name, str(v.id)),
    )
    out = cooks[: (len(cooks) + 1) // 2]
    gone = {v.id for v in out}
    vols = [
        v.model_copy(update={"available": False}) if v.id in gone else v for v in snap.volunteers
    ]
    return (
        _replace(snap, volunteers=vols),
        [f"{len(out)} of {len(cooks)} cooks are unavailable"],
        [nid("volunteer", v) for v in gone],
    )


def _delivery_disruption(
    snap: OperationalSnapshot,
) -> tuple[OperationalSnapshot, list[str], list[str]]:
    load: dict[Any, int] = {}
    for c in snap.active_commitments:
        if c.delivery_id:
            load[c.delivery_id] = load.get(c.delivery_id, 0) + c.meals_count
    if not load:
        return snap, ["no routed commitments"], []
    target = max(load, key=lambda d: (load[d], str(d)))
    routes = [
        d.model_copy(update={"status": "cancelled"}) if d.id == target else d
        for d in snap.deliveries
    ]
    return (
        _replace(snap, deliveries=routes),
        [f"Delivery route {snap.delivery[target].route_name} cancelled"],
        [nid("delivery", target)],
    )


def _multiple(snap: OperationalSnapshot) -> tuple[OperationalSnapshot, list[str], list[str]]:
    notes: list[str] = []
    origins: list[str] = []
    for fn in (_largest_donation, _volunteer_shortage, _delivery_disruption):
        snap, n, o = fn(snap)
        notes += n
        origins += o
    return snap, notes, origins


SCENARIOS: dict[str, Scenario] = {
    s.key: s
    for s in (
        Scenario(
            "donation_cancellation",
            "Donation cancellation",
            "The largest received donation is cancelled.",
            _largest_donation,
        ),
        Scenario(
            "ingredient_shortage",
            "Ingredient shortage",
            "Half the stock of the most-used ingredient spoils.",
            _ingredient_shortage,
        ),
        Scenario(
            "volunteer_shortage",
            "Volunteer shortage",
            "Half of the available cooks drop out.",
            _volunteer_shortage,
        ),
        Scenario(
            "delivery_disruption",
            "Delivery disruption",
            "The busiest delivery route is cancelled.",
            _delivery_disruption,
        ),
        Scenario(
            "multiple_failures",
            "Multiple simultaneous failures",
            "Donation cancelled, cooks drop out and a route is cancelled at once.",
            _multiple,
        ),
    )
}


def _summary(rep: OptimizationReport) -> dict[str, Any]:
    p = rep.plan
    return {
        "verdict": rep.verdict,
        "solver_status": rep.solver_status,
        "meals_planned": p.metrics.meals_planned if p else 0,
        "meals_requested": p.metrics.meals_requested if p else 0,
        "commitments_feasible": p.metrics.commitments_feasible if p else 0,
        "substitutions": len(p.substitutions) if p else 0,
        "commitments": [c.model_dump(mode="json") for c in p.commitments] if p else [],
        "diagnosis": rep.diagnosis.model_dump(mode="json"),
        "objectives": rep.objectives,
        "wall_ms": rep.wall_ms,
    }


def simulate(snap: OperationalSnapshot, key: str) -> dict[str, Any]:
    scenario = SCENARIOS[key]
    cfg = OptimizerConfig(stage_deterministic_time=5.0)
    before = run(snap, cfg, with_candidates=False)
    changed, notes, origins = scenario.apply(snap)
    after = run(changed, cfg, with_candidates=False)
    imp = impact(build_graph(snap), origins)
    return {
        "scenario": {
            "key": scenario.key,
            "title": scenario.title,
            "description": scenario.description,
        },
        "isolated": True,
        "applied": notes,
        "state_version": snap.state_version,
        "before": _summary(before),
        "after": _summary(after),
        "impact": imp.model_dump(mode="json"),
    }
