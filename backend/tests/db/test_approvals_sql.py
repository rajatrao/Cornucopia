"""Postgres-level tests of the approval engine (migration 0007)."""

from __future__ import annotations

import json
import threading
import uuid
from typing import Any

import pytest

from cornucopia.auth import hash_password
from tests.db.test_ingest_event_sql import ADMIN_URL, Svc, db_url  # noqa: F401 - fixture

psycopg = pytest.importorskip("psycopg")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="CORNUCOPIA_TEST_PG_ADMIN_URL not set")


def w(svc: Svc, org: str, table: str, values: dict[str, Any]) -> str:
    return str(
        svc.one(
            "select (cornucopia.write_resource(%s,'op:test',%s,'insert',null,%s::jsonb))->>'id'",
            org,
            table,
            json.dumps(values),
        )
    )


@pytest.fixture
def world(db_url: str) -> dict[str, Any]:  # noqa: F811
    svc = Svc(db_url)
    org = str(
        svc.one(f"select (cornucopia.ensure_organization('appr-{uuid.uuid4().hex[:8]}','A')).id")
    )
    ing = w(svc, org, "ingredients", {"name": "Rice", "base_unit": "g"})
    rec = w(svc, org, "recipes", {"name": "Pilaf", "yield_portions": "10", "prep_minutes": 10})
    w(
        svc,
        org,
        "recipe_ingredients",
        {
            "recipe_id": rec,
            "ingredient_id": ing,
            "quantity": "1",
            "unit": "kg",
            "quantity_base": "1000",
        },
    )
    meal = w(svc, org, "meals", {"name": "Plate"})
    team = w(
        svc,
        org,
        "preparation_teams",
        {"name": "K", "capacity_portions_per_hour": "10", "available_hours": "5"},
    )
    route = w(
        svc,
        org,
        "deliveries",
        {"route_name": "A", "capacity_meals": 50, "departs_at": "2030-01-01T10:00:00Z"},
    )
    com = w(
        svc,
        org,
        "commitments",
        {
            "recipient": "Shelter",
            "meal_id": meal,
            "meals_count": 10,
            "due_at": "2030-01-01T12:00:00Z",
            "delivery_id": route,
        },
    )
    ev = svc.rpc_ingest(
        org,
        f"k-{uuid.uuid4()}",
        "DONATION_CREATED",
        {
            "description": "rice",
            "received": True,
            "lots": [
                {
                    "ingredient_id": ing,
                    "quantity": "1",
                    "unit": "kg",
                    "quantity_base": "1000",
                    "base_unit": "g",
                }
            ],
        },
    )
    lot = str(
        svc.one(
            "select id from cornucopia.inventory_lots where donation_id = %s",
            ev["event"]["effect"]["donation_id"],
        )
    )
    claim = svc.one("select cornucopia.claim_next_execution(%s,'worker-1',60)", org)
    ex = claim["execution"]
    state = svc.one(
        "select version from cornucopia.operational_state where organization_id=%s", org
    )
    plan = {
        "commitments": [{"commitment_id": com, "planned": 10}],
        "recipes": [{"recipe_id": rec, "portions": "10", "batches": "1"}],
        "allocations": [{"lot_id": lot, "ingredient_id": ing, "quantity_base": "1000"}],
        "routing": [{"commitment_id": com, "delivery_id": route, "meals": 10}],
        "teams": [{"team_id": team, "portions": 10, "capacity": 50}],
        "metrics": {"meals_planned": 10, "meals_requested": 10},
    }
    run = {
        "state_version": state,
        "config": {},
        "solver_status": "OPTIMAL",
        "verdict": "verified_feasible",
        "objectives": {},
        "stages": [],
        "model_stats": {},
        "diagnosis": {},
        "wall_ms": 1,
    }
    res = [
        {
            "candidate": "recommended",
            "recommended": True,
            "verdict": "verified_feasible",
            "fingerprint": "f" * 64,
            "meals_planned": 10,
            "plan": plan,
            "summary": {},
        }
    ]
    run_id = svc.one(
        "select cornucopia.record_optimization_run(%s,'agent',%s::jsonb,%s::jsonb)",
        org,
        json.dumps(run),
        json.dumps(res),
    )["run_id"]
    prop = svc.one(
        "select cornucopia.propose_plan(%s,%s,'worker-1',1,%s,'{}'::jsonb,'[]'::jsonb,false,60)",
        org,
        ex["id"],
        run_id,
    )
    ops = {}
    for name, role in (("alice", "approver"), ("bob", "approver"), ("olga", "operator")):
        ops[name] = svc.one(
            "select (cornucopia.create_operator(%s,%s,%s,%s,%s))->>'id'",
            org,
            name,
            name,
            role,
            hash_password("x" * 16),
        )
    return {
        "svc": svc,
        "org": org,
        "exec": ex,
        "prop": prop,
        "ops": ops,
        "com": com,
        "state": state,
        "url": db_url,
    }


def decide(
    svc: Svc,
    wd: dict[str, Any],
    who: str,
    decision: str = "approve",
    confirm: bool = True,
    fp: str | None = None,
    sv: int | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = svc.one(
        "select cornucopia.decide_approval(%s,%s,%s,%s,%s,%s,%s,null)",
        wd["org"],
        wd["prop"]["request_id"],
        wd["ops"][who],
        decision,
        fp or wd["prop"]["fingerprint"],
        sv if sv is not None else wd["prop"]["state_version"],
        confirm,
    )
    return out


def commit(
    svc: Svc, wd: dict[str, Any], worker: str = "worker-1", attempt: int = 1
) -> dict[str, Any]:
    out: dict[str, Any] = svc.one(
        "select cornucopia.commit_approved_plan(%s,%s,%s)",
        wd["prop"]["request_id"],
        worker,
        attempt,
    )
    return out


def test_happy_path_commit_is_atomic_and_audited(world: dict[str, Any]) -> None:
    svc = world["svc"]
    assert decide(svc, world, "alice", confirm=False)["code"] == "confirmation_required"
    assert decide(svc, world, "alice")["accepted"] is True
    out = commit(svc, world)
    assert out["committed"] is True and out["approved_by"] == "alice"
    assert (
        svc.one("select planned_meals from cornucopia.commitments where id=%s", world["com"]) == 10
    )
    assert (
        svc.one(
            "select status from cornucopia.approval_requests where id=%s",
            world["prop"]["request_id"],
        )
        == "committed"
    )
    assert (
        svc.one(
            "select count(*) from cornucopia.outbox_messages where organization_id=%s", world["org"]
        )
        == 1
    )
    actors = svc.one(
        "select array_agg(distinct actor) from cornucopia.audit_records "
        "where table_name in ('commitments','lot_allocations','plan_routing','meal_batches') "
        "and organization_id=%s and actor like 'operator:alice%%'",
        world["org"],
    )
    assert actors and actors[0].startswith("operator:alice (approved plan v")
    assert commit(svc, world)["duplicate"] is True  # replay is a no-op


def test_commit_fenced_by_execution_lease(world: dict[str, Any]) -> None:
    svc = world["svc"]
    decide(svc, world, "alice")
    with pytest.raises(psycopg.Error, match="lease"):
        commit(svc, world, worker="someone-else")


def test_unauthorized_duplicate_and_fingerprint_refusals_are_recorded(
    world: dict[str, Any],
) -> None:
    svc = world["svc"]
    assert decide(svc, world, "olga")["code"] == "unauthorized"
    assert decide(svc, world, "alice", fp="0" * 64)["code"] == "fingerprint_mismatch"
    assert decide(svc, world, "alice")["accepted"] is True
    assert decide(svc, world, "bob")["code"] == "duplicate"
    rows = svc.conn.execute(
        "select operator_username, accepted, refusal_reason from cornucopia.approval_decisions "
        "where approval_request_id=%s order by created_at",
        (world["prop"]["request_id"],),
    ).fetchall()
    assert rows == [
        ("olga", False, "unauthorized"),
        ("alice", False, "fingerprint_mismatch"),
        ("alice", True, None),
        ("bob", False, "duplicate"),
    ]


def test_stale_approval_and_stale_commit(world: dict[str, Any]) -> None:
    svc = world["svc"]
    w(svc, world["org"], "donors", {"name": "Someone"})  # operations changed
    assert decide(svc, world, "alice")["code"] == "stale"
    assert (
        svc.one(
            "select status from cornucopia.approval_requests where id=%s",
            world["prop"]["request_id"],
        )
        == "stale"
    )


def test_state_change_between_approval_and_commit_blocks_commit(world: dict[str, Any]) -> None:
    svc = world["svc"]
    assert decide(svc, world, "alice")["accepted"] is True
    w(svc, world["org"], "donors", {"name": "Someone else"})
    assert commit(svc, world)["code"] == "stale"
    assert (
        svc.one("select planned_meals from cornucopia.commitments where id=%s", world["com"])
        is None
    )  # nothing partially applied


def test_expired_request(world: dict[str, Any]) -> None:
    svc = world["svc"]
    admin = psycopg.connect(world["url"], autocommit=True)
    admin.execute(
        "update cornucopia.approval_requests set expires_at = now() - interval '1 minute' "
        "where id = %s",
        (world["prop"]["request_id"],),
    )
    assert decide(svc, world, "alice")["code"] == "expired"


def test_concurrent_approvals_only_one_wins(world: dict[str, Any]) -> None:
    results: list[dict[str, Any]] = []
    lock = threading.Lock()

    def go(who: str) -> None:
        r = decide(Svc(world["url"]), world, who)
        with lock:
            results.append(r)

    threads = [threading.Thread(target=go, args=(n,)) for n in ("alice", "bob", "alice", "bob")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(r["accepted"] for r in results) == 1
    assert sorted(r.get("code") or "" for r in results) == [
        "",
        "duplicate",
        "duplicate",
        "duplicate",
    ]


def test_planned_meals_cannot_change_outside_a_commit(world: dict[str, Any]) -> None:
    svc = world["svc"]
    with pytest.raises(psycopg.Error, match="approved plan commit"):
        svc.one(
            "select cornucopia.write_resource(%s,'op:x','commitments','update',%s,"
            "'{\"planned_meals\": 5}'::jsonb)",
            world["org"],
            world["com"],
        )


def test_newer_proposal_supersedes_pending_one(world: dict[str, Any]) -> None:
    svc = world["svc"]
    # second execution + proposal for the same organization
    ev2 = svc.rpc_ingest(
        world["org"],
        f"k-{uuid.uuid4()}",
        "VOLUNTEER_UNAVAILABLE",
        {
            "volunteer_id": w(svc, world["org"], "volunteers", {"name": "V", "role": "cook"}),
            "reason": "sick",
        },
    )
    assert ev2["duplicate"] is False
    claim = svc.one("select cornucopia.claim_next_execution(%s,'worker-2',60)", world["org"])
    run_id = svc.one(
        "select run_id from cornucopia.optimization_results r join cornucopia.optimization_runs o "
        "on o.id = r.run_id where o.organization_id=%s limit 1",
        world["org"],
    )
    svc.one(
        "select cornucopia.propose_plan(%s,%s,'worker-2',1,%s,'{}'::jsonb,'[]'::jsonb,false,60)",
        world["org"],
        claim["execution"]["id"],
        run_id,
    )
    assert (
        svc.one(
            "select status from cornucopia.approval_requests where id=%s",
            world["prop"]["request_id"],
        )
        == "stale"
    )
