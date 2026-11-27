"""CP-SAT recovery optimizer.

Hard constraints (never traded against anything):
  * a meal is only planned for a commitment whose diets it satisfies;
  * ingredient use (after substitutions) never exceeds usable stock;
  * cooked portions never exceed preparation capacity;
  * meals only ride usable routes, within route capacity.

Soft objectives, optimised lexicographically (each stage fixes the optimum of
the previous one, then improves the next):
  1. commitments fully met            (maximise)  "preserve commitments"
  2. meals served                     (maximise)
  3. change vs. the reference plan    (minimise)  meals moved + substitution rules used
  4. food waste                       (minimise)  stock expiring within the horizon left unused
  5. delivery disruption              (minimise)  meals moved off their route + meals on late routes
  6. due-date priority                (maximise)  tie-break: earlier-due commitments first

Integer scaling (all exact or rounded in the safe direction):
  ingredients in milligram units (base x 1000). Each recipe line's need is
  modelled as an exact rational, ceil(sum(qty_mg x portions x meals) / yield),
  using integer numerators and denominators; substitute use is exactly
  ceil(replaced x ratio). Portions x 100, ratios x 10000.

Determinism: one search worker, fixed seed, deterministic-time limits. The
solver's answer is then rebuilt with exact Decimal arithmetic and checked by
the independent validator; nothing unverified is ever labelled feasible.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any
from uuid import UUID

from ortools.sat.python import cp_model

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
from cornucopia.compiler.diet import violations
from cornucopia.compiler.plan import (
    Allocation,
    CommitmentPlan,
    DeliveryLoad,
    Plan,
    PlanMetrics,
    RecipePlan,
    RouteAssignment,
    Shortage,
    SubstitutionUse,
    TeamLoad,
)
from cornucopia.compiler.planner import ceil_int
from cornucopia.compiler.snapshot import OperationalSnapshot
from cornucopia.compiler.substitutions import recipe_diets

MG = Decimal(1000)

STAGES = (
    "commitments_met",
    "meals_served",
    "plan_change",
    "waste_mg",
    "delivery_disruption",
    "due_priority",
)


@dataclass(frozen=True)
class OptimizerConfig:
    include_pledged: bool = False
    use_substitutions: bool = True
    allow_rerouting: bool = True
    waste_horizon_hours: int = 72
    # deterministic time (CP-SAT work units, machine independent) per stage
    stage_deterministic_time: float = 10.0
    stage_wall_time_s: float = 20.0
    random_seed: int = 0

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class StageResult:
    name: str
    status: str
    objective: int | None
    wall_ms: float
    deterministic_time: float


@dataclass
class OptimizationOutcome:
    config: OptimizerConfig
    status: str  # OPTIMAL | FEASIBLE (time-limited) | MODEL_INVALID | ERROR
    stages: list[StageResult]
    plan: Plan | None
    objectives: dict[str, int]
    blocked: dict[str, list[str]]  # commitment id -> reasons it cannot be served at all
    model_stats: dict[str, int] = field(default_factory=dict)
    wall_ms: float = 0.0


def _exact_int(v: Decimal) -> int:
    if v != v.to_integral_value():
        raise ValueError(f"expected an exact integer after scaling, got {v}")
    return int(v)


def _scaled_up(v: Decimal, scale: Decimal) -> int:
    return int((v * scale).to_integral_value(rounding=ROUND_CEILING))


def _scaled_down(v: Decimal, scale: Decimal) -> int:
    return int((v * scale).to_integral_value(rounding=ROUND_FLOOR))


@dataclass
class _Sub:
    rule_id: UUID
    recipe_id: UUID
    ingredient_id: UUID
    substitute_id: UUID
    ratio: Decimal
    r: cp_model.IntVar  # original replaced, mg
    u: cp_model.IntVar  # substitute used, mg
    z: cp_model.IntVar  # rule used (bool)


class RecoveryModel:
    """Builds the CP-SAT model for one snapshot and configuration."""

    def __init__(
        self,
        snap: OperationalSnapshot,
        cfg: OptimizerConfig,
        reference: Plan | None = None,
        *,
        force_full: bool = False,
    ) -> None:
        self.snap, self.cfg, self.reference = snap, cfg, reference
        self.force_full = force_full
        self.m = cp_model.CpModel()
        self.avail = availability(snap, include_pledged=cfg.include_pledged)
        self.routes = delivery_capacities(snap)
        self.teams = team_capacities(snap)
        self.prep_capacity = sum(t.portions for t in self.teams)
        self.blocked: dict[str, list[str]] = {}
        self.meals: dict[UUID, cp_model.IntVar] = {}
        self.route_vars: dict[tuple[UUID, UUID], cp_model.IntVar] = {}
        self.subs: list[_Sub] = []
        self.slacks: dict[str, cp_model.IntVar] = {}
        self.ub: dict[int, int] = {}
        self._build()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        snap, cfg, m = self.snap, self.cfg, self.m
        needs_by_c = {}
        # exact rational line needs: mg = sum(qty_mg * P * meals) / Y, with
        # P = component portions x 100 and Y = recipe yield x 100 (both integers)
        line_terms: dict[tuple[UUID, UUID], list[tuple[int, cp_model.IntVar]]] = {}
        line_den: dict[tuple[UUID, UUID], int] = {}
        prep_terms: list[tuple[int, cp_model.IntVar]] = []

        for c in snap.active_commitments:
            needs = meal_needs(snap, c.meal_id, c.diet_requirements)
            needs_by_c[c.id] = needs
            reasons = [f"meal: {p}" for p in needs.problems]
            reasons += [f"diet: {v}" for v in needs.diet_violations]
            usable_routes = self._routes_for(c.id, c.delivery_id)
            if c.delivery_id is not None and not usable_routes:
                rt = self.routes.get(c.delivery_id)
                reasons.append(f"delivery: {rt.reason if rt else 'route missing'}")
            if reasons:
                self.blocked[str(c.id)] = reasons
            ub = 0 if reasons else c.meals_count
            x = m.new_int_var(ub if (self.force_full and not reasons) else 0, ub, f"meals_{c.id}")
            self.meals[c.id] = x
            self.ub[x.index] = ub

            for comp in snap.components_by_meal.get(c.meal_id, ()):
                recipe = snap.recipe[comp.recipe_id]
                for line in snap.lines_by_recipe.get(recipe.id, ()):
                    attrs = snap.ingredient[line.ingredient_id].attributes
                    if line.optional and violations(attrs, c.diet_requirements):
                        continue
                    qty_mg = _exact_int(line.quantity_base * MG)
                    key = (recipe.id, line.ingredient_id)
                    line_terms.setdefault(key, []).append(
                        (qty_mg * _exact_int(comp.portions * 100), x)
                    )
                    line_den[key] = _exact_int(recipe.yield_portions * 100)
            ppm = needs.portions_per_meal
            if ppm > 0:
                prep_terms.append((_scaled_up(ppm, Decimal(100)), x))

            # routing
            if usable_routes:
                ys = []
                for d in usable_routes:
                    y = m.new_int_var(0, c.meals_count, f"route_{c.id}_{d}")
                    self.route_vars[(c.id, d)] = y
                    ys.append(y)
                m.add(sum(ys) == x)
        self.needs_by_c = needs_by_c

        # t_line = ceil(exact line need in mg), modelled exactly:
        #   Y*t >= N  and  Y*t <= N + Y - 1
        self.line_need: dict[tuple[UUID, UUID], cp_model.IntVar] = {}
        for key, terms in sorted(line_terms.items(), key=lambda kv: str(kv[0])):
            y_den = line_den[key]
            numer = sum(coef * x for coef, x in terms)
            hi = sum(coef * self.snap_req(x) for coef, x in terms) // y_den + 1
            t = m.new_int_var(0, max(hi, 0), f"need_{key[0]}_{key[1]}")
            m.add(y_den * t >= numer)
            m.add(y_den * t <= numer + y_den - 1)
            self.line_need[key] = t

        # substitutions
        if cfg.use_substitutions:
            for (recipe_id, ing_id), _terms in sorted(
                line_terms.items(), key=lambda kv: str(kv[0])
            ):
                diets = recipe_diets(snap, recipe_id)
                rules = [
                    s
                    for s in sorted(snap.substitutions, key=lambda s: str(s.id))
                    if s.ingredient_id == ing_id
                    and s.recipe_id in (None, recipe_id)
                    and s.substitute_id in snap.ingredient
                    and not violations(snap.ingredient[s.substitute_id].attributes, diets)
                ]
                if not rules:
                    continue
                t_line = self.line_need[(recipe_id, ing_id)]
                cap = int(t_line.proto.domain[1])
                group = []
                for rule in rules:
                    tag = f"{rule.id}_{recipe_id}"
                    r = m.new_int_var(0, max(cap, 0), f"sub_r_{tag}")
                    sub_avail = _scaled_down(self.avail.get(rule.substitute_id, ZERO), MG)
                    u = m.new_int_var(0, max(sub_avail, 0), f"sub_u_{tag}")
                    z = m.new_bool_var(f"sub_z_{tag}")
                    ratio = _exact_int(rule.ratio * 10_000)
                    # u = ceil(r * ratio) exactly: no phantom "use" of a substitute
                    m.add(10_000 * u >= ratio * r)
                    m.add(10_000 * u <= ratio * r + 9_999)
                    m.add(r <= max(cap, 0) * z)
                    self.subs.append(
                        _Sub(rule.id, recipe_id, ing_id, rule.substitute_id, rule.ratio, r, u, z)
                    )
                    group.append(r)
                m.add(sum(group) <= t_line)

        # ingredient balance
        self.q: dict[UUID, cp_model.IntVar] = {}
        all_ings = {k[1] for k in self.line_need} | {s.substitute_id for s in self.subs}
        for i in sorted(all_ings, key=str):
            needs_i = [t for (r, ing), t in self.line_need.items() if ing == i]
            hi = sum(int(t.proto.domain[1]) for t in needs_i)
            q = m.new_int_var(0, max(hi, 0), f"use_{i}")
            m.add(q == sum(needs_i)) if needs_i else m.add(q == 0)
            self.q[i] = q
            replaced = [s.r for s in self.subs if s.ingredient_id == i]
            used_as_sub = [s.u for s in self.subs if s.substitute_id == i]
            avail_mg = _scaled_down(self.avail.get(i, ZERO), MG)
            expr = q - sum(replaced) + sum(used_as_sub)
            if self.force_full:
                e = m.new_int_var(0, 10**12, f"slack_ing_{i}")
                self.slacks[f"ingredient:{i}"] = e
                m.add(expr <= avail_mg + e)
            else:
                m.add(expr <= avail_mg)
            m.add(expr >= 0)

        # preparation capacity
        if prep_terms:
            if self.force_full:
                e = m.new_int_var(0, 10**9, "slack_prep")
                self.slacks["prep"] = e
                m.add(sum(k * x for k, x in prep_terms) <= 100 * self.prep_capacity + e)
            else:
                m.add(sum(k * x for k, x in prep_terms) <= 100 * self.prep_capacity)

        # route capacity
        for d, route in sorted(self.routes.items(), key=lambda kv: str(kv[0])):
            ys = [y for (c, dd), y in self.route_vars.items() if dd == d]
            if not ys:
                continue
            if self.force_full:
                e = m.new_int_var(0, 10**7, f"slack_route_{d}")
                self.slacks[f"route:{d}"] = e
                m.add(sum(ys) <= route.meals + e)
            else:
                m.add(sum(ys) <= route.meals)

    def snap_req(self, x: cp_model.IntVar) -> int:
        """Upper bound of a meals variable (tracked explicitly)."""
        return self.ub[x.index]

    def _routes_for(self, commitment_id: UUID, original: UUID | None) -> list[UUID]:
        usable = sorted((d for d, r in self.routes.items() if r.usable), key=str)
        if not self.cfg.allow_rerouting:
            return [original] if original in usable else []
        if original is None:
            return []  # commitment without a route is not routed (reported as a risk)
        return usable

    # ------------------------------------------------------------ objectives
    def objective_exprs(self) -> dict[str, Any]:
        snap, m = self.snap, self.m
        full = []
        for c in snap.active_commitments:
            b = m.new_bool_var(f"full_{c.id}")
            m.add(self.meals[c.id] >= c.meals_count).only_enforce_if(b)
            full.append(b)
        change_terms: list[Any] = [s.z for s in self.subs]
        if self.reference is not None:
            ref = {p.commitment_id: p.planned for p in self.reference.commitments}
            for c in snap.active_commitments:
                dev = m.new_int_var(0, c.meals_count, f"dev_{c.id}")
                m.add_abs_equality(dev, self.meals[c.id] - ref.get(c.id, 0))
                change_terms.append(dev)
        # waste: usable stock expiring within the horizon that the plan does not use
        horizon = snap.as_of + timedelta(hours=self.cfg.waste_horizon_hours)
        expiring: dict[UUID, Decimal] = {}
        for lot in usable_lots(snap, include_pledged=self.cfg.include_pledged):
            if lot.expires_at is not None and lot.expires_at <= horizon:
                expiring[lot.ingredient_id] = (
                    expiring.get(lot.ingredient_id, ZERO) + lot.quantity_base
                )
        waste_terms = []
        for i, qty in sorted(expiring.items(), key=lambda kv: str(kv[0])):
            exp_mg = _scaled_down(qty, MG)
            used: Any = self.q.get(i, 0)
            used = (
                used
                - sum(s.r for s in self.subs if s.ingredient_id == i)
                + sum(s.u for s in self.subs if s.substitute_id == i)
            )
            w = m.new_int_var(0, exp_mg, f"waste_{i}")
            m.add(w >= exp_mg - used)
            waste_terms.append(w)
        disruption = []
        for (cid, d), y in self.route_vars.items():
            c = next(x for x in snap.active_commitments if x.id == cid)
            late = snap.delivery[d].departs_at > c.due_at
            moved = c.delivery_id is not None and d != c.delivery_id
            weight = int(moved) + int(late)
            if weight:
                disruption.append(weight * y)
        # tie-break: among otherwise equal plans, serve earlier-due commitments first
        n = len(snap.active_commitments)
        priority = sum((n - k) * self.meals[c.id] for k, c in enumerate(snap.active_commitments))
        return {
            "due_priority": priority if n else 0,
            "commitments_met": sum(full),
            "meals_served": sum(self.meals.values()),
            "plan_change": sum(change_terms) if change_terms else 0,
            "waste_mg": sum(waste_terms) if waste_terms else 0,
            "delivery_disruption": sum(disruption) if disruption else 0,
        }


def _solver(cfg: OptimizerConfig) -> cp_model.CpSolver:
    s = cp_model.CpSolver()
    s.parameters.num_search_workers = 1
    s.parameters.random_seed = cfg.random_seed
    s.parameters.max_deterministic_time = cfg.stage_deterministic_time
    s.parameters.max_time_in_seconds = cfg.stage_wall_time_s
    return s


def _lexicographic(
    rm: RecoveryModel, order: list[tuple[str, bool]], exprs: dict[str, Any]
) -> tuple[list[StageResult], cp_model.CpSolver | None, dict[str, int], str]:
    stages: list[StageResult] = []
    fixed: dict[str, int] = {}
    solver: cp_model.CpSolver | None = None
    overall = "OPTIMAL"
    for name, maximize in order:
        expr = exprs[name]
        if isinstance(expr, int):
            fixed[name] = expr
            stages.append(StageResult(name, "TRIVIAL", expr, 0.0, 0.0))
            continue
        if maximize:
            rm.m.maximize(expr)
        else:
            rm.m.minimize(expr)
        if solver is not None:  # warm start from the previous stage's solution
            rm.m.clear_hints()  # type: ignore[no-untyped-call]
            for v in _all_vars(rm):
                rm.m.add_hint(v, solver.value(v))
        solver = _solver(rm.cfg)
        t0 = time.perf_counter()
        st = solver.solve(rm.m)
        wall = (time.perf_counter() - t0) * 1000
        name_st = solver.status_name(st)
        stages.append(
            StageResult(
                name,
                name_st,
                int(solver.objective_value)
                if st in (cp_model.OPTIMAL, cp_model.FEASIBLE)
                else None,
                round(wall, 1),
                round(solver.deterministic_time, 3),
            )
        )
        if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return stages, None, fixed, name_st
        if st == cp_model.FEASIBLE:
            overall = "FEASIBLE"
        best = int(round(solver.objective_value))
        fixed[name] = best
        rm.m.add(expr >= best if maximize else expr <= best)
    return stages, solver, fixed, overall


def _all_vars(rm: RecoveryModel) -> list[cp_model.IntVar]:
    out: list[cp_model.IntVar] = list(rm.meals.values()) + list(rm.route_vars.values())
    for s in rm.subs:
        out += [s.r, s.u, s.z]
    out += list(rm.q.values())
    return out


def optimize(
    snap: OperationalSnapshot, cfg: OptimizerConfig | None = None, reference: Plan | None = None
) -> OptimizationOutcome:
    cfg = cfg or OptimizerConfig()
    t0 = time.perf_counter()
    rm = RecoveryModel(snap, cfg, reference)
    exprs = rm.objective_exprs()
    order = [
        ("commitments_met", True),
        ("meals_served", True),
        ("plan_change", False),
        ("waste_mg", False),
        ("delivery_disruption", False),
        ("due_priority", True),
    ]
    stages, solver, fixed, status = _lexicographic(rm, order, exprs)
    proto = rm.m.proto
    stats = {
        "variables": len(proto.variables),
        "constraints": len(proto.constraints),
        "substitution_options": len(rm.subs),
        "route_options": len(rm.route_vars),
    }
    plan = _extract(rm, solver) if solver is not None else None
    return OptimizationOutcome(
        cfg,
        status,
        stages,
        plan,
        fixed,
        rm.blocked,
        stats,
        round((time.perf_counter() - t0) * 1000, 1),
    )


# ----------------------------------------------------------------- extraction
def _extract(rm: RecoveryModel, solver: cp_model.CpSolver) -> Plan:
    """Rebuild the plan with exact Decimal arithmetic from the solver's decisions."""
    snap, cfg = rm.snap, rm.cfg
    commitments: list[CommitmentPlan] = []
    used_exact: dict[UUID, Decimal] = {}
    portions_exact = ZERO
    recipe_portions: dict[UUID, Decimal] = {}
    for c in snap.active_commitments:
        needs = rm.needs_by_c[c.id]
        planned = int(solver.value(rm.meals[c.id]))
        for i, p in needs.ingredient_per_meal.items():
            used_exact[i] = used_exact.get(i, ZERO) + p * planned
        portions_exact += needs.portions_per_meal * planned
        for r, p in needs.portions_by_recipe.items():
            recipe_portions[r] = recipe_portions.get(r, ZERO) + p * planned
        limited = list(rm.blocked.get(str(c.id), []))
        if planned < c.meals_count and not limited:
            limited.append("optimizer: shared resources exhausted (see diagnosis)")
        risks: list[str] = []
        if c.delivery_id is None:
            risks.append("no delivery route assigned")
        for (cid, d), y in rm.route_vars.items():
            if cid == c.id and solver.value(y) > 0:
                if d != c.delivery_id:
                    risks.append(
                        f"{int(solver.value(y))} meals moved to {snap.delivery[d].route_name}"
                    )
                if snap.delivery[d].departs_at > c.due_at:
                    risks.append(f"{snap.delivery[d].route_name} departs after the due time")
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

    subs: list[SubstitutionUse] = []
    required = {i: ceil3(v) for i, v in used_exact.items() if v > 0}
    for s in rm.subs:
        r_mg = int(solver.value(s.r))
        if r_mg <= 0:
            continue
        replaced = Decimal(r_mg) / MG
        sub_base = ceil3(replaced * s.ratio)
        subs.append(
            SubstitutionUse(
                substitution_id=s.rule_id,
                recipe_id=s.recipe_id,
                ingredient_id=s.ingredient_id,
                substitute_id=s.substitute_id,
                replaced_base=replaced,
                substitute_base=sub_base,
            )
        )
        required[s.ingredient_id] = required.get(s.ingredient_id, ZERO) - replaced
        required[s.substitute_id] = required.get(s.substitute_id, ZERO) + sub_base

    allocations: list[Allocation] = []
    remaining = {i: v for i, v in required.items() if v > 0}
    for lot in usable_lots(snap, include_pledged=cfg.include_pledged):
        need = remaining.get(lot.ingredient_id, ZERO)
        if need <= 0:
            continue
        take = min(need, lot.quantity_base)
        allocations.append(
            Allocation(lot_id=lot.id, ingredient_id=lot.ingredient_id, quantity_base=take)
        )
        remaining[lot.ingredient_id] = need - take

    routing = tuple(
        sorted(
            (
                RouteAssignment(commitment_id=cid, delivery_id=d, meals=int(solver.value(y)))
                for (cid, d), y in rm.route_vars.items()
                if solver.value(y) > 0
            ),
            key=lambda a: (str(a.commitment_id), str(a.delivery_id)),
        )
    )
    route_used: dict[UUID, int] = {}
    for a in routing:
        route_used[a.delivery_id] = route_used.get(a.delivery_id, 0) + a.meals

    portions_total = ceil_int(portions_exact)
    loads, unassigned = [], portions_total
    for t in rm.teams:
        assign = min(unassigned, t.portions)
        loads.append(TeamLoad(team_id=t.team_id, portions=assign, capacity=t.portions))
        unassigned -= assign

    demand = full_demand(snap)
    shortages = tuple(
        Shortage(
            ingredient_id=i,
            required_base=req,
            available_base=rm.avail.get(i, ZERO),
            missing_base=req - rm.avail.get(i, ZERO),
        )
        for i, req in sorted(demand.by_ingredient.items(), key=lambda kv: str(kv[0]))
        if req > rm.avail.get(i, ZERO)
    )
    metrics = PlanMetrics(
        meals_requested=sum(c.requested for c in commitments),
        meals_planned=sum(c.planned for c in commitments),
        commitments_total=len(commitments),
        commitments_feasible=sum(c.status == "feasible" for c in commitments),
        commitments_partial=sum(c.status == "partial" for c in commitments),
        commitments_infeasible=sum(c.status == "infeasible" for c in commitments),
        portions_planned=portions_total,
        prep_capacity_portions=rm.prep_capacity,
        ingredient_base_allocated=sum((a.quantity_base for a in allocations), ZERO),
        ingredient_base_available=sum(rm.avail.values(), ZERO),
    )
    return Plan(
        kind="optimized",
        organization_id=snap.organization_id,
        state_version=snap.state_version,
        as_of=snap.as_of,
        include_pledged=cfg.include_pledged,
        commitments=tuple(commitments),
        recipes=tuple(
            RecipePlan(recipe_id=r, portions=p, batches=p / snap.recipe[r].yield_portions)
            for r, p in sorted(recipe_portions.items(), key=lambda kv: str(kv[0]))
            if p > 0
        ),
        allocations=tuple(sorted(allocations, key=lambda a: (str(a.ingredient_id), str(a.lot_id)))),
        substitutions=tuple(sorted(subs, key=lambda s: (str(s.recipe_id), str(s.substitution_id)))),
        routing=routing,
        teams=tuple(loads),
        deliveries=tuple(
            DeliveryLoad(
                delivery_id=r.delivery_id, meals=route_used.get(r.delivery_id, 0), capacity=r.meals
            )
            for r in sorted(rm.routes.values(), key=lambda x: (x.route_name, str(x.delivery_id)))
        ),
        shortages=shortages,
        metrics=metrics,
    )
