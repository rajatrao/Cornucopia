"""Agent graph + supervisor tests over the in-memory connector double.

Durability is exercised by abandoning a worker mid-graph (simulated crash),
expiring its lease, and letting a brand-new worker (new saver, new graph,
same storage) resume from the checkpoints.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from cornucopia.agent.supervisor import SpriteHold, Worker
from cornucopia.agent.tools import LeaseLost, SupabaseAgentTools
from cornucopia.api.app import create_app
from cornucopia.config import Settings
from cornucopia.persistence.memory import InMemorySupabaseClient


class NoHold(SpriteHold):
    def __init__(self) -> None:
        self.enabled = False
        self._client = None


class Crash(BaseException):
    """Simulates the process dying (not an Exception, so nothing catches it)."""


def _post(c: TestClient, path: str, body: dict[str, Any], status: int = 201) -> Any:
    r = c.post(path, json=body)
    assert r.status_code == status, r.text
    return r.json()


@pytest.fixture
def env() -> tuple[TestClient, InMemorySupabaseClient, dict[str, str]]:
    db = InMemorySupabaseClient()
    c = TestClient(
        create_app(
            Settings(CORNUCOPIA_TRANSPORT="memory", _env_file=None),  # type: ignore[call-arg]
            client=db,
        )
    )
    c.__enter__()
    ids: dict[str, str] = {}
    ids["rice"] = _post(
        c, "/api/v1/resources/ingredients", {"name": "Rice", "category": "grain", "base_unit": "g"}
    )["id"]
    ids["quinoa"] = _post(
        c,
        "/api/v1/resources/ingredients",
        {"name": "Quinoa", "category": "grain", "base_unit": "g"},
    )["id"]
    ids["recipe"] = _post(
        c,
        "/api/v1/resources/recipes",
        {"name": "Pilaf", "yield_portions": "50", "prep_minutes": 30},
    )["id"]
    _post(
        c,
        "/api/v1/resources/recipe-ingredients",
        {"recipe_id": ids["recipe"], "ingredient_id": ids["rice"], "quantity": "12", "unit": "lb"},
    )
    _post(
        c,
        "/api/v1/resources/substitutions",
        {"ingredient_id": ids["rice"], "substitute_id": ids["quinoa"], "ratio": "1"},
    )
    meal = _post(c, "/api/v1/resources/meals", {"name": "Plate"})["id"]
    _post(
        c,
        "/api/v1/resources/meal-components",
        {"meal_id": meal, "recipe_id": ids["recipe"], "portions": "1"},
    )
    _post(
        c,
        "/api/v1/resources/teams",
        {"name": "Kitchen", "capacity_portions_per_hour": "100", "available_hours": "5"},
    )
    route = _post(
        c,
        "/api/v1/resources/deliveries",
        {"route_name": "A", "capacity_meals": 300, "departs_at": "2030-01-01T10:00:00Z"},
    )["id"]
    ids["commitment"] = _post(
        c,
        "/api/v1/resources/commitments",
        {
            "recipient": "Shelter",
            "meal_id": meal,
            "meals_count": 100,
            "due_at": "2030-01-01T12:00:00Z",
            "delivery_id": route,
        },
    )["id"]
    ev = _post(
        c,
        "/api/v1/events",
        {
            "idempotency_key": "seed-rice-donation",
            "event": {
                "type": "DONATION_CREATED",
                "description": "Rice",
                "received": True,
                "lots": [{"ingredient_id": ids["rice"], "quantity": "24", "unit": "lb"}],
            },
        },
    )
    ids["rice_donation_event"] = ev["event"]["id"]
    ids["rice_donation"] = ev["event"]["effect"]["donation_id"]
    return c, db, ids


def _org(c: TestClient) -> UUID:
    return UUID(c.get("/api/v1/organization").json()["id"])


def _worker(c: TestClient, db: InMemorySupabaseClient, name: str) -> Worker:
    return Worker(db, _org(c), worker_id=name, lease_seconds=30, hold=NoHold())


def _drain(w: Worker) -> list[str]:
    out = []
    while (claim := w.claim()) is not None:
        out.append(w.process(claim))
    return out


def _execution(db: InMemorySupabaseClient, event_id: str) -> dict[str, Any]:
    return next(x for x in db.tables["agent_executions"] if x["event_id"] == event_id)


def _steps(db: InMemorySupabaseClient, ex: dict[str, Any], status: str = "completed") -> list[str]:
    return [
        s["node"]
        for s in db.tables["agent_execution_steps"]
        if s["execution_id"] == ex["id"] and s["status"] == status
    ]


def _cancel_rice(c: TestClient, ids: dict[str, str], key: str = "cancel-rice-1") -> str:
    ev = _post(
        c,
        "/api/v1/events",
        {
            "idempotency_key": key,
            "event": {
                "type": "DONATION_CANCELLED",
                "donation_id": ids["rice_donation"],
                "reason": "rice donation cancelled",
            },
        },
    )
    return str(ev["event"]["id"])


def test_donation_with_everything_feasible_needs_no_action(env) -> None:  # type: ignore[no-untyped-def]
    c, db, ids = env
    w = _worker(c, db, "w1")
    assert _drain(w) == ["completed"]
    ex = _execution(db, ids["rice_donation_event"])
    assert ex["status"] == "completed"
    assert _steps(db, ex)[-3:] == ["assess_impact", "select_recovery_strategy", "record_outcome"]
    assert db.tables.get("optimization_runs", []) == []  # nothing to recover, no solve


def test_infeasible_rice_cancellation_escalates_with_diagnosis(env) -> None:  # type: ignore[no-untyped-def]
    c, db, ids = env
    w = _worker(c, db, "w1")
    _drain(w)
    ev_id = _cancel_rice(c, ids)
    assert _drain(w) == ["escalated"]
    ex = _execution(db, ev_id)
    nodes = _steps(db, ex)
    assert nodes == [
        "receive_event",
        "validate_event",
        "classify_event",
        "update_operational_state",
        "analyze_dependencies",
        "assess_impact",
        "select_recovery_strategy",
        "generate_candidate_plan",
        "run_cpsat_optimizer",
        "validate_candidate",
        "compare_plan_versions",
        "generate_decision_report",
        "investigate_infeasibility",
        "escalate_to_operator",
    ]
    reasons = ex["result"]["outcome"]["reasons"]
    assert any("Rice 24.0 lb" in r for r in reasons)  # 24 lb rice needed, no quinoa in stock
    ev = next(e for e in db.tables["operational_events"] if e["id"] == ev_id)
    assert ev["processing_status"] == "escalated"


def test_recoverable_cancellation_requests_approval_and_pauses(env) -> None:  # type: ignore[no-untyped-def]
    c, db, ids = env
    _post(
        c,
        "/api/v1/events",
        {
            "idempotency_key": "quinoa-1",
            "event": {
                "type": "DONATION_CREATED",
                "description": "Quinoa",
                "received": True,
                "lots": [{"ingredient_id": ids["quinoa"], "quantity": "30", "unit": "lb"}],
            },
        },
    )
    w = _worker(c, db, "w1")
    _drain(w)
    ev_id = _cancel_rice(c, ids)
    assert _drain(w) == ["awaiting_approval"]
    ex = _execution(db, ev_id)
    proposal = ex["result"]["proposal"]
    assert proposal["kind"] == "approval_required" and proposal["run_id"]
    assert _steps(db, ex, "interrupted") == ["request_approval"]
    run = next(r for r in db.tables["optimization_runs"] if r["id"] == proposal["run_id"])
    assert run["verdict"] == "verified_feasible"
    # the paused graph is durable: a fresh worker sees the same interrupt
    w2 = _worker(c, db, "w2")
    state = w2.graph.get_state({"configurable": {"thread_id": ex["thread_id"]}})
    assert state.next == ("request_approval",) and state.interrupts


def test_crash_mid_graph_resumes_from_checkpoint_without_duplicates(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    c, db, ids = env
    w1 = _worker(c, db, "w1")
    _drain(w1)
    ev_id = _cancel_rice(c, ids)

    real_optimize = SupabaseAgentTools.optimize
    crashed = {"done": False}

    def optimize_then_die(self, cfg, key):  # type: ignore[no-untyped-def]
        out = real_optimize(self, cfg, key)  # the run IS persisted ...
        if not crashed["done"]:
            crashed["done"] = True
            raise Crash("process killed after persisting, before checkpoint")  # ... then we die
        return out

    monkeypatch.setattr(SupabaseAgentTools, "optimize", optimize_then_die)
    with pytest.raises(Crash):
        _drain(w1)
    ex = _execution(db, ev_id)
    assert ex["status"] == "running" and ex["last_completed_node"] == "generate_candidate_plan"
    assert len(db.tables["optimization_runs"]) == 1

    # restart: the old lease expires, a new process claims and resumes
    ex["lease_expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
    w2 = _worker(c, db, "w2")
    claim = w2.claim()
    assert claim is not None and claim.resumed and claim.execution["attempt"] == 2
    assert w2.process(claim) == "escalated"
    assert len(db.tables["optimization_runs"]) == 1  # idempotency key reused, no duplicate
    completed = _steps(db, ex)
    assert completed.count("receive_event") == 1  # finished nodes were not re-run
    assert completed.count("run_cpsat_optimizer") == 1
    assert [
        s["status"] for s in db.tables["agent_execution_steps"] if s["execution_id"] == ex["id"]
    ].count("resumed") == 1


def test_stale_worker_is_fenced_off(env) -> None:  # type: ignore[no-untyped-def]
    c, db, ids = env
    w1 = _worker(c, db, "w1")
    claim1 = w1.claim()
    assert claim1 is not None
    ex = _execution(db, ids["rice_donation_event"])
    ex["lease_expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
    w2 = _worker(c, db, "w2")
    claim2 = w2.claim()
    assert claim2 is not None and claim2.resumed
    # w1 wakes up and tries to continue: every write is refused
    assert w1.process(claim1) == "lease_lost"
    assert w2.process(claim2) == "completed"
    assert _execution(db, ids["rice_donation_event"])["status"] == "completed"


def test_each_event_is_executed_once(env) -> None:  # type: ignore[no-untyped-def]
    c, db, ids = env
    w = _worker(c, db, "w1")
    assert _drain(w) == ["completed"]
    assert _drain(w) == []  # nothing left; the finished execution is never reclaimed
    # resubmitting the same event (same idempotency key) is a duplicate, not new work
    again = c.post(
        "/api/v1/events",
        json={
            "idempotency_key": "seed-rice-donation",
            "event": {
                "type": "DONATION_CREATED",
                "description": "Rice",
                "received": True,
                "lots": [{"ingredient_id": ids["rice"], "quantity": "24", "unit": "lb"}],
            },
        },
    )
    assert again.status_code == 200 and again.json()["duplicate"] is True
    assert _drain(w) == []
    assert len(db.tables["agent_executions"]) == 1


def test_malformed_event_is_escalated_not_guessed(env) -> None:  # type: ignore[no-untyped-def]
    c, db, ids = env
    w = _worker(c, db, "w1")
    _drain(w)
    org = str(_org(c))
    bad = db.insert(
        "operational_events",
        [
            {
                "organization_id": org,
                "idempotency_key": "corrupt-1",
                "event_type": "DELIVERY_DELAYED",
                "payload": {"reason": "late"},
                "payload_hash": "x",
                "actor": "test",
                "correlation_id": "00000000-0000-0000-0000-000000000001",
                "effect": {},
                "state_version": 1,
                "processing_status": "pending",
            }
        ],
    )[0]
    assert _drain(w) == ["escalated"]
    ex = _execution(db, bad["id"])
    assert "payload missing delivery_id, delay_minutes" in ex["result"]["outcome"]["reasons"][0]


def test_lease_lost_raises_in_tools(env) -> None:  # type: ignore[no-untyped-def]
    c, db, ids = env
    w1 = _worker(c, db, "w1")
    claim = w1.claim()
    assert claim is not None
    ex = _execution(db, ids["rice_donation_event"])
    ex["attempt"] = 99  # someone else took over
    from cornucopia.agent.tools import ExecutionContext

    ctx = ExecutionContext(
        _org(c),
        UUID(ex["id"]),
        UUID(ex["event_id"]),
        UUID(str(ex["correlation_id"])),
        ex["thread_id"],
        "w1",
        1,
    )
    with pytest.raises(LeaseLost):
        SupabaseAgentTools(db, w1.repo, ctx).record_step("receive_event", "completed", {})


def test_execution_history_api(env) -> None:  # type: ignore[no-untyped-def]
    c, db, ids = env
    w = _worker(c, db, "w1")
    _drain(w)
    lst = c.get("/api/v1/agent/executions").json()
    assert lst[0]["event_type"] == "DONATION_CREATED" and lst[0]["status"] == "completed"
    detail = c.get(f"/api/v1/agent/executions/{lst[0]['id']}").json()
    assert [s["node"] for s in detail["steps"]][:2] == ["supervisor", "receive_event"]
    assert len(detail["checkpoints"]) >= 9
    st = c.get("/api/v1/agent/status").json()
    assert st["executions_by_status"] == {"completed": 1} and st["pending_events"] == 0


def test_unrelated_event_does_not_reescalate_preexisting_shortfall(env) -> None:  # type: ignore[no-untyped-def]
    c, db, ids = env
    w = _worker(c, db, "w1")
    _drain(w)
    _cancel_rice(c, ids)
    assert _drain(w) == ["escalated"]
    driver = _post(c, "/api/v1/resources/volunteers", {"name": "Dana", "role": "driver"})
    ev = _post(
        c,
        "/api/v1/events",
        {
            "idempotency_key": "driver-sick-1",
            "event": {
                "type": "VOLUNTEER_UNAVAILABLE",
                "volunteer_id": driver["id"],
                "reason": "flu",
            },
        },
    )
    assert _drain(w) == ["completed"]
    outcome = _execution(db, ev["event"]["id"])["result"]["outcome"]
    assert outcome["reason"] == "no commitment affected by this event is at risk"
    assert outcome["preexisting_shortfall_meals"] == 100
