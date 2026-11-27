"""The CORNUCOPIA recovery agent as a LangGraph state machine.

receive_event -> validate_event -> classify_event -> update_operational_state
  -> analyze_dependencies -> assess_impact -> select_recovery_strategy
     -> (no recovery needed) record_outcome
     -> generate_candidate_plan -> run_cpsat_optimizer -> validate_candidate
          -> (unverified, retries left) generate_candidate_plan  [next strategy]
          -> (unverified, no retries) escalate_to_operator
          -> compare_plan_versions -> generate_decision_report
               -> (verified, every commitment met) request_approval
                    -> [interrupt: waits for a human decision]
                    -> commit_approved_plan -> record_outcome
               -> (verified but partial) investigate_infeasibility -> escalate_to_operator
  invalid events -> escalate_to_operator

All decisions are deterministic code. No language model is involved.
Every node records a fenced step; a worker that lost its lease stops at the
next node boundary. State holds only JSON-serialisable values so it can be
checkpointed through the Supabase connector.
"""

from __future__ import annotations

import operator
import os
import time
from collections.abc import Callable
from typing import Annotated, Any, Literal, TypedDict
from uuid import UUID

import httpx
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, interrupt

from cornucopia.agent.tools import AgentTools, LeaseLost
from cornucopia.compiler.planner import compile_baseline
from cornucopia.depgraph.graph import build_graph, event_origins, impact
from cornucopia.domain.events import EventType
from cornucopia.optimizer.model import OptimizerConfig
from cornucopia.persistence.client import SupabaseError

MAX_RETRIES = 2
RECURSION_LIMIT = 40

STRATEGIES: list[dict[str, Any]] = [
    {"name": "full_recovery", "use_substitutions": True, "allow_rerouting": True},
    {"name": "no_rerouting", "use_substitutions": True, "allow_rerouting": False},
    {"name": "no_substitutions", "use_substitutions": False, "allow_rerouting": False},
]

CATEGORY = {
    "DONATION_CREATED": ("supply_gain", "low"),
    "DONATION_CANCELLED": ("supply_loss", "high"),
    "INVENTORY_ADJUSTED": ("inventory_change", "medium"),
    "INGREDIENT_EXPIRED": ("supply_loss", "high"),
    "VOLUNTEER_UNAVAILABLE": ("capacity_loss", "medium"),
    "DELIVERY_DELAYED": ("delivery_disruption", "medium"),
    "DELIVERY_CANCELLED": ("delivery_disruption", "high"),
    "COMMITMENT_CHANGED": ("demand_change", "medium"),
    "PREPARATION_CAPACITY_CHANGED": ("capacity_change", "medium"),
}

REQUIRED_KEYS = {
    "DONATION_CREATED": ("description", "lots"),
    "DONATION_CANCELLED": ("donation_id", "reason"),
    "INVENTORY_ADJUSTED": ("lot_id", "delta_base", "reason"),
    "INGREDIENT_EXPIRED": ("lot_id", "reason"),
    "VOLUNTEER_UNAVAILABLE": ("volunteer_id", "reason"),
    "DELIVERY_DELAYED": ("delivery_id", "delay_minutes", "reason"),
    "DELIVERY_CANCELLED": ("delivery_id", "reason"),
    "COMMITMENT_CHANGED": ("commitment_id", "reason"),
    "PREPARATION_CAPACITY_CHANGED": ("team_id", "reason"),
}


class AgentState(TypedDict, total=False):
    execution_id: str
    event_id: str
    correlation_id: str
    event: dict[str, Any]
    validation_errors: list[str]
    classification: dict[str, Any]
    state_version: int
    impact: dict[str, Any]
    assessment: dict[str, Any]
    strategy_index: int
    strategy: dict[str, Any]
    retry_count: int
    optimization: dict[str, Any]
    comparison: dict[str, Any]
    report: dict[str, Any]
    investigation: dict[str, Any]
    decision: str
    approval: dict[str, Any] | None
    outcome: dict[str, Any]
    current_node: str
    trail: Annotated[list[str], operator.add]


def _tools(config: RunnableConfig) -> AgentTools:
    tools: AgentTools = config["configurable"]["tools"]
    return tools


def _transient(exc: Exception) -> bool:
    if isinstance(exc, SupabaseError):
        return exc.status >= 500 or exc.status == 429
    return isinstance(exc, httpx.TransportError)


Node = Callable[[AgentState, RunnableConfig], dict[str, Any]]


def node(name: str) -> Callable[[Node], Node]:
    """Wrap a node: fenced step records, drill delay, trail bookkeeping."""

    def deco(fn: Node) -> Node:
        def wrapped(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
            tools = _tools(config)
            delay = float(os.environ.get("CORNUCOPIA_AGENT_STEP_DELAY_S", "0") or 0)
            if delay > 0:  # resilience drills only (Phase 8); off by default
                time.sleep(delay)
            try:
                update = fn(state, config)
            except LeaseLost:
                raise
            except GraphBubbleUp:  # interrupt(): the graph pauses here, not a failure
                tools.record_step(name, "interrupted", {"waiting_for": "human approval"})
                raise
            except Exception as exc:
                tools.record_step(name, "failed", {"error": f"{type(exc).__name__}: {exc}"[:500]})
                raise
            tools.record_step(name, "completed", _summary(name, update))
            return {**update, "current_node": name, "trail": [name]}

        wrapped.__name__ = name
        return wrapped

    return deco


def _summary(name: str, update: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "decision",
        "classification",
        "assessment",
        "strategy",
        "comparison",
        "validation_errors",
        "state_version",
        "outcome",
    )
    out = {k: update[k] for k in keep if k in update}
    if "optimization" in update:
        o = update["optimization"]
        out["optimization"] = {
            k: o.get(k)
            for k in ("run_id", "verdict", "solver_status", "meals_planned", "fingerprint")
        }
    if "impact" in update:
        out["impact"] = {
            "counts": update["impact"].get("counts"),
            "affected_commitments": len(update["impact"].get("affected_commitments", [])),
        }
    return out


# ----------------------------------------------------------------- nodes
@node("receive_event")
def receive_event(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    ev = _tools(config).load_event()
    return {
        "event": {
            k: ev[k]
            for k in (
                "id",
                "event_type",
                "payload",
                "effect",
                "actor",
                "state_version",
                "correlation_id",
                "created_at",
            )
        }
    }


@node("validate_event")
def validate_event(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    ev = state["event"]
    errors: list[str] = []
    etype = str(ev.get("event_type"))
    if etype not in EventType.__members__:
        errors.append(f"unknown event type {etype}")
    else:
        missing = [k for k in REQUIRED_KEYS[etype] if k not in (ev.get("payload") or {})]
        if missing:
            errors.append(f"payload missing {', '.join(missing)}")
    if not isinstance(ev.get("effect"), dict):
        errors.append("event has no recorded effect")
    return {"validation_errors": errors}


@node("classify_event")
def classify_event(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    category, severity = CATEGORY[state["event"]["event_type"]]
    return {"classification": {"category": category, "severity": severity}}


@node("update_operational_state")
def update_operational_state(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """The fact was applied atomically when the event was journaled. Confirm the
    current state includes it; never apply it a second time."""
    snap = _tools(config).snapshot()
    applied_at = int(state["event"]["state_version"])
    if snap.state_version < applied_at:
        raise RuntimeError(f"state v{snap.state_version} predates event v{applied_at}")
    return {"state_version": snap.state_version}


@node("analyze_dependencies")
def analyze_dependencies(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    snap = _tools(config).snapshot()
    ev = state["event"]
    origins = event_origins(ev["event_type"], ev["payload"], ev["effect"])
    imp = impact(build_graph(snap), origins)
    return {"impact": imp.model_dump(mode="json")}


@node("assess_impact")
def assess_impact(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    snap = _tools(config).snapshot()
    base = compile_baseline(snap)
    affected = set(state["impact"]["affected_commitments"])
    at_risk = [
        c
        for c in base.commitments
        if c.status != "feasible" and f"commitment:{c.commitment_id}" in affected
    ]
    return {
        "assessment": {
            "meals_requested": base.metrics.meals_requested,
            "meals_feasible_without_recovery": base.metrics.meals_planned,
            # only shortfalls this event can explain count as its impact
            "meals_at_risk": sum(c.requested - c.planned for c in at_risk),
            "affected_commitments": len(affected),
            "commitments_at_risk": [str(c.commitment_id) for c in at_risk],
            "preexisting_shortfall_meals": base.metrics.meals_requested
            - base.metrics.meals_planned
            - sum(c.requested - c.planned for c in at_risk),
            "state_version": snap.state_version,
        }
    }


@node("select_recovery_strategy")
def select_recovery_strategy(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    a = state["assessment"]
    if not a["commitments_at_risk"]:  # pre-existing shortfalls belong to their own events
        return {"decision": "no_action", "strategy": {"name": "none"}}
    idx = int(state.get("strategy_index", 0))
    return {
        "decision": "recover",
        "strategy_index": idx,
        "strategy": STRATEGIES[idx],
        "retry_count": int(state.get("retry_count", 0)),
    }


@node("generate_candidate_plan")
def generate_candidate_plan(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    idx = int(state.get("strategy_index", 0))
    return {"strategy": STRATEGIES[min(idx, len(STRATEGIES) - 1)]}


@node("run_cpsat_optimizer")
def run_cpsat_optimizer(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    tools = _tools(config)
    s = state["strategy"]
    cfg = OptimizerConfig(
        use_substitutions=s["use_substitutions"], allow_rerouting=s["allow_rerouting"]
    )
    key = f"{state['execution_id']}:{s['name']}:{state.get('retry_count', 0)}"
    run_id, rep = tools.optimize(cfg, key)
    plan = rep.plan
    return {
        "optimization": {
            "run_id": str(run_id),
            "idempotency_key": key,
            "verdict": rep.verdict,
            "solver_status": rep.solver_status,
            "fingerprint": rep.fingerprint,
            "state_version": rep.state_version,
            "violations": rep.violations,
            "meals_planned": plan.metrics.meals_planned if plan else 0,
            "meals_requested": plan.metrics.meals_requested if plan else 0,
            "commitments": [c.model_dump(mode="json") for c in plan.commitments] if plan else [],
            "substitutions": [x.model_dump(mode="json") for x in plan.substitutions]
            if plan
            else [],
            "rerouted_meals": sum(
                c.meals_rerouted for c in rep.candidates if c.name == "recommended"
            ),
            "diagnosis": rep.diagnosis.model_dump(mode="json"),
            "objectives": rep.objectives,
            "candidates": [
                {"name": c.name, "verdict": c.verdict, "meals_planned": c.meals_planned}
                for c in rep.candidates
            ],
        }
    }


@node("validate_candidate")
def validate_candidate(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    o = state["optimization"]
    ok = o["verdict"] in ("verified_feasible", "verified_partial")
    if ok:
        return {"decision": "verified"}
    retries = int(state.get("retry_count", 0))
    if retries < MAX_RETRIES:
        _tools(config).record_step(
            "validate_candidate",
            "retry",
            {"verdict": o["verdict"], "violations": o["violations"][:5]},
        )
        return {
            "decision": "retry",
            "retry_count": retries + 1,
            "strategy_index": min(int(state.get("strategy_index", 0)) + 1, len(STRATEGIES) - 1),
        }
    return {"decision": "unverifiable"}


@node("compare_plan_versions")
def compare_plan_versions(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    snap = _tools(config).snapshot()
    base = compile_baseline(snap)
    o = state["optimization"]
    # Rebuild only what the diff needs from the stored recommended plan summary.
    before = {str(c.commitment_id): c.planned for c in base.commitments}
    after = {c["commitment_id"]: c["planned"] for c in o["commitments"]}
    changes = [
        {"commitment_id": k, "before": before.get(k, 0), "after": after.get(k, 0)}
        for k in sorted(set(before) | set(after))
        if before.get(k, 0) != after.get(k, 0)
    ]
    return {
        "comparison": {
            "baseline_meals": base.metrics.meals_planned,
            "proposed_meals": o["meals_planned"],
            "meals_recovered": o["meals_planned"] - base.metrics.meals_planned,
            "commitment_changes": changes,
            "substitutions": len(o["substitutions"]),
            "baseline_state_version": base.state_version,
        }
    }


@node("generate_decision_report")
def generate_decision_report(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    ev, a, o, cmp_ = state["event"], state["assessment"], state["optimization"], state["comparison"]
    full = o["verdict"] == "verified_feasible"
    lines = [
        f"Event: {ev['event_type'].replace('_', ' ').lower()} (state v{ev['state_version']}).",
        f"Impact: {a['affected_commitments']} commitment(s) depend on the changed resource; "
        f"{a['meals_at_risk']} of their meals cannot be produced without recovery "
        f"({a['meals_requested']} meals committed in total).",
        f"Recovery ({state['strategy']['name']}): the optimizer proposes {o['meals_planned']} of "
        f"{o['meals_requested']} meals ({cmp_['meals_recovered']:+d} vs. no action), "
        f"{cmp_['substitutions']} substitution(s), verdict {o['verdict']}.",
    ]
    if not full:
        lines.append(f"Unresolved: {o['diagnosis']['explanation']}")
    return {
        "decision": "request_approval" if full else "investigate",
        "report": {
            "headline": (
                "All commitments can be met with the proposed recovery."
                if full
                else "Not every commitment can be met; operator attention needed."
            ),
            "lines": lines,
            "requires_approval": True,
            "run_id": o["run_id"],
            "fingerprint": o["fingerprint"],
        },
    }


@node("investigate_infeasibility")
def investigate_infeasibility(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    o = state.get("optimization") or {}
    d = o.get("diagnosis") or {}
    unmet = [c for c in o.get("commitments", []) if c["status"] != "feasible"]
    return {
        "investigation": {
            "shortfalls": d.get("shortfalls", []),
            "blocked": d.get("blocked", {}),
            "explanation": d.get("explanation", "no diagnosis available"),
            "unmet_commitments": [
                {
                    "commitment_id": c["commitment_id"],
                    "recipient": c["recipient"],
                    "planned": c["planned"],
                    "requested": c["requested"],
                    "limited_by": c["limited_by"],
                }
                for c in unmet
            ],
            "best_verified_plan": o.get("run_id")
            if o.get("verdict", "").startswith("verified")
            else None,
        }
    }


@node("escalate_to_operator")
def escalate_to_operator(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    reasons = list(state.get("validation_errors") or [])
    if state.get("decision") == "unverifiable":
        reasons.append("no candidate plan passed independent validation")
    inv = state.get("investigation") or {}
    if inv:
        reasons.append(inv["explanation"])
    return {
        "decision": "escalated",
        "outcome": {
            "status": "escalated",
            "reasons": reasons,
            "proposal_run_id": inv.get("best_verified_plan"),
        },
    }


@node("request_approval")
def request_approval(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    o = state["optimization"]
    decision = interrupt(
        {
            "kind": "approval_required",
            "run_id": o["run_id"],
            "fingerprint": o["fingerprint"],
            "state_version": o["state_version"],
            "report": state["report"],
        }
    )
    return {"approval": decision if isinstance(decision, dict) else {"raw": decision}}


@node("commit_approved_plan")
def commit_approved_plan(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    approval = state.get("approval") or {}
    if approval.get("decision") != "approved":
        return {"decision": "rejected", "outcome": {"status": "rejected", "approval": approval}}
    result = _tools(config).commit_plan(UUID(state["optimization"]["run_id"]), approval)
    return {"decision": "committed", "outcome": {"status": "committed", "commit": result}}


@node("record_outcome")
def record_outcome(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    if state.get("decision") == "no_action":
        return {
            "outcome": {
                "status": "completed",
                "reason": "no commitment affected by this event is at risk",
                "preexisting_shortfall_meals": (state.get("assessment") or {}).get(
                    "preexisting_shortfall_meals", 0
                ),
            }
        }
    return {"outcome": state.get("outcome") or {"status": state.get("decision", "completed")}}


# ---------------------------------------------------------------- routing
def after_validate_event(state: AgentState) -> Literal["classify_event", "escalate_to_operator"]:
    return "escalate_to_operator" if state.get("validation_errors") else "classify_event"


def after_strategy(state: AgentState) -> Literal["generate_candidate_plan", "record_outcome"]:
    return "record_outcome" if state.get("decision") == "no_action" else "generate_candidate_plan"


def after_validate_candidate(
    state: AgentState,
) -> Literal["compare_plan_versions", "generate_candidate_plan", "investigate_infeasibility"]:
    d = state.get("decision")
    if d == "verified":
        return "compare_plan_versions"
    if d == "retry":
        return "generate_candidate_plan"
    return "investigate_infeasibility"


def after_report(state: AgentState) -> Literal["request_approval", "investigate_infeasibility"]:
    return (
        "request_approval"
        if state.get("decision") == "request_approval"
        else "investigate_infeasibility"
    )


NODES: dict[str, Node] = {
    f.__name__: f
    for f in (
        receive_event,
        validate_event,
        classify_event,
        update_operational_state,
        analyze_dependencies,
        assess_impact,
        select_recovery_strategy,
        generate_candidate_plan,
        run_cpsat_optimizer,
        validate_candidate,
        compare_plan_versions,
        generate_decision_report,
        request_approval,
        commit_approved_plan,
        record_outcome,
        investigate_infeasibility,
        escalate_to_operator,
    )
}


def build_agent_graph(checkpointer: Any) -> Any:
    g: StateGraph[AgentState] = StateGraph(AgentState)
    retry = RetryPolicy(
        max_attempts=3, initial_interval=0.5, backoff_factor=2.0, retry_on=_transient
    )
    for name, fn in NODES.items():
        g.add_node(name, fn, retry_policy=retry)  # type: ignore[call-overload]
    g.add_edge(START, "receive_event")
    g.add_edge("receive_event", "validate_event")
    g.add_conditional_edges("validate_event", after_validate_event)
    g.add_edge("classify_event", "update_operational_state")
    g.add_edge("update_operational_state", "analyze_dependencies")
    g.add_edge("analyze_dependencies", "assess_impact")
    g.add_edge("assess_impact", "select_recovery_strategy")
    g.add_conditional_edges("select_recovery_strategy", after_strategy)
    g.add_edge("generate_candidate_plan", "run_cpsat_optimizer")
    g.add_edge("run_cpsat_optimizer", "validate_candidate")
    g.add_conditional_edges("validate_candidate", after_validate_candidate)
    g.add_edge("compare_plan_versions", "generate_decision_report")
    g.add_conditional_edges("generate_decision_report", after_report)
    g.add_edge("request_approval", "commit_approved_plan")
    g.add_edge("commit_approved_plan", "record_outcome")
    g.add_edge("investigate_infeasibility", "escalate_to_operator")
    g.add_edge("escalate_to_operator", END)
    g.add_edge("record_outcome", END)
    return g.compile(checkpointer=checkpointer)
