"""Infeasibility diagnosis: the smallest additions that would serve every meal.

The recovery model is rebuilt with every serviceable commitment forced to its
full meal count, and each hard resource limit gets a non-negative slack. The
slacks are minimised lexicographically (ingredients first, then preparation
capacity, then route capacity), with substitutions and rerouting still
available. Each non-zero slack is an exact, explained shortfall. Commitments
that no amount of extra stock could serve (diet conflicts, broken meals) are
reported separately as blocked.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from cornucopia.compiler.snapshot import OperationalSnapshot
from cornucopia.domain.units import Quantity, Unit
from cornucopia.optimizer.model import OptimizerConfig, RecoveryModel, _solver


@dataclass(frozen=True)
class Shortfall:
    resource: str  # ingredient | preparation | route
    id: str | None
    label: str
    missing: Decimal
    unit: str
    display: str


@dataclass(frozen=True)
class Diagnosis:
    status: str
    fully_serviceable: bool  # True when no slack is needed
    shortfalls: tuple[Shortfall, ...]
    blocked: dict[str, list[str]]
    explanation: str


def diagnose(snap: OperationalSnapshot, cfg: OptimizerConfig) -> Diagnosis:
    rm = RecoveryModel(snap, cfg, force_full=True)
    groups = [
        ("ingredient", [v for k, v in rm.slacks.items() if k.startswith("ingredient:")]),
        ("preparation", [v for k, v in rm.slacks.items() if k == "prep"]),
        ("route", [v for k, v in rm.slacks.items() if k.startswith("route:")]),
    ]
    solver = None
    for _, vars_ in groups:
        if not vars_:
            continue
        rm.m.minimize(sum(vars_))
        solver = _solver(cfg)
        st = solver.solve(rm.m)
        if solver.status_name(st) not in ("OPTIMAL", "FEASIBLE"):
            return Diagnosis(
                solver.status_name(st), False, (), rm.blocked, "diagnosis model could not be solved"
            )
        rm.m.add(sum(vars_) <= int(round(solver.objective_value)))
    if solver is None:
        return Diagnosis("TRIVIAL", True, (), rm.blocked, "nothing to serve")

    out: list[Shortfall] = []
    for key, var in sorted(rm.slacks.items()):
        val = int(solver.value(var))
        if val <= 0:
            continue
        if key.startswith("ingredient:"):
            iid = UUID(key.split(":", 1)[1])
            ing = snap.ingredient[iid]
            amount = Decimal(val) / 1000
            disp = (
                f"{Quantity(amount, Unit.G).to(Unit.LB).amount.quantize(Decimal('0.1'))} lb"
                if ing.base_unit is Unit.G
                else f"{amount.normalize():f} {ing.base_unit.value}"
            )
            out.append(
                Shortfall("ingredient", str(iid), ing.name, amount, ing.base_unit.value, disp)
            )
        elif key == "prep":
            portions = (Decimal(val) / 100).to_integral_value(rounding="ROUND_CEILING")
            out.append(
                Shortfall(
                    "preparation",
                    None,
                    "Preparation capacity",
                    portions,
                    "portion",
                    f"{portions} portions",
                )
            )
        else:
            did = UUID(key.split(":", 1)[1])
            out.append(
                Shortfall(
                    "route",
                    str(did),
                    snap.delivery[did].route_name,
                    Decimal(val),
                    "meal",
                    f"{val} meals",
                )
            )
    if not out:
        text = "Every serviceable commitment can be met in full with current resources."
    else:
        text = "To serve every serviceable meal, the operation is missing: " + "; ".join(
            f"{s.label} {s.display}" for s in out
        )
        if cfg.use_substitutions:
            text += " (after using every valid substitution)"
    if rm.blocked:
        text += f". {len(rm.blocked)} commitment(s) cannot be served by any resource change."
    return Diagnosis("OPTIMAL", not out, tuple(out), rm.blocked, text)
