"""Postgres-level tests for agent leases, fencing and checkpoint RPCs (0006)."""

from __future__ import annotations

import json
import threading
import uuid
from typing import Any

import pytest

from tests.db.test_ingest_event_sql import ADMIN_URL, Svc, db_url  # noqa: F401 - fixture

psycopg = pytest.importorskip("psycopg")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="CORNUCOPIA_TEST_PG_ADMIN_URL not set")


@pytest.fixture(scope="module")
def org(db_url: str) -> str:  # noqa: F811
    return str(Svc(db_url).one("select (cornucopia.ensure_organization('agent-org','Agent')).id"))


def _event(svc: Svc, org: str) -> str:
    ing = svc.one(
        "select (cornucopia.write_resource(%s,'op:test','ingredients','insert',null,"
        "%s::jsonb))->>'id'",
        org,
        json.dumps({"name": f"Ing {uuid.uuid4().hex[:6]}", "base_unit": "g"}),
    )
    res = svc.rpc_ingest(
        org,
        f"k-{uuid.uuid4()}",
        "DONATION_CREATED",
        {
            "description": "test donation",
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
    return str(res["event"]["id"])


def _claim(svc: Svc, org: str, worker: str, lease: int = 30) -> dict[str, Any] | None:
    out: dict[str, Any] | None = svc.one(
        "select cornucopia.claim_next_execution(%s, %s, %s)", org, worker, lease
    )
    return out


def _drain_pending(svc: Svc, org: str) -> None:
    while (c := _claim(svc, org, "drainer")) is not None:
        ex = c["execution"]
        svc.one(
            "select cornucopia.finish_execution(%s,'drainer',%s,'completed','{}'::jsonb,null)",
            ex["id"],
            ex["attempt"],
        )


def test_claim_is_exclusive_under_concurrency(db_url: str, org: str) -> None:  # noqa: F811
    svc = Svc(db_url)
    _drain_pending(svc, org)
    events = {_event(svc, org) for _ in range(5)}
    got: list[str] = []
    lock = threading.Lock()

    def worker(name: str) -> None:
        s = Svc(db_url)
        while (c := _claim(s, org, name)) is not None:
            with lock:
                got.append(c["event"]["id"])

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(got) == sorted(events)  # every event claimed exactly once
    assert (
        svc.one(
            "select count(*) from cornucopia.agent_executions where event_id = any(%s::uuid[])",
            list(events),
        )
        == 5
    )


def test_expired_lease_is_reclaimed_and_old_worker_fenced(db_url: str, org: str) -> None:  # noqa: F811
    svc = Svc(db_url)
    _drain_pending(svc, org)
    _event(svc, org)
    c1 = _claim(svc, org, "old", lease=5)
    assert c1 is not None and c1["resumed"] is False
    ex = c1["execution"]
    assert (
        svc.one(
            "select cornucopia.record_execution_step(%s,'old',1,'receive_event','completed','{}')",
            ex["id"],
        )
        is True
    )
    admin = psycopg.connect(db_url, autocommit=True)  # simulate time passing
    admin.execute(
        "update cornucopia.agent_executions set lease_expires_at = now() - interval '1 second' "
        "where id = %s",
        (ex["id"],),
    )
    c2 = _claim(svc, org, "new")
    assert c2 is not None and c2["resumed"] is True and c2["execution"]["attempt"] == 2
    # the old worker comes back: all its writes are refused
    assert (
        svc.one(
            "select cornucopia.record_execution_step(%s,'old',1,'validate_event','completed','{}')",
            ex["id"],
        )
        is False
    )
    assert svc.one("select cornucopia.heartbeat_execution(%s,'old',1,30)", ex["id"]) is False
    assert (
        svc.one(
            "select cornucopia.finish_execution(%s,'old',1,'completed','{}'::jsonb,null)", ex["id"]
        )
        is False
    )
    assert (
        svc.one(
            "select cornucopia.finish_execution(%s,'new',2,'escalated','{}'::jsonb,'x')", ex["id"]
        )
        is True
    )
    assert (
        svc.one(
            "select processing_status from cornucopia.operational_events where id = %s",
            ex["event_id"],
        )
        == "escalated"
    )
    assert _claim(svc, org, "anyone") is None  # finished work is never handed out again


def test_steps_and_checkpoints_are_append_only_and_idempotent(db_url: str, org: str) -> None:  # noqa: F811
    svc = Svc(db_url)
    row = {
        "thread_id": "event:t1",
        "checkpoint_ns": "",
        "checkpoint_id": "0001",
        "organization_id": org,
        "parent_checkpoint_id": None,
        "checkpoint_type": "msgpack",
        "checkpoint": "AA==",
        "metadata_type": "msgpack",
        "metadata": "AA==",
        "summary": {},
    }
    for _ in range(2):
        svc.one("select cornucopia.put_checkpoint(%s::jsonb)", json.dumps(row))
    assert (
        svc.one("select count(*) from cornucopia.agent_checkpoints where thread_id='event:t1'") == 1
    )
    w = {k: row[k] for k in ("thread_id", "checkpoint_ns", "checkpoint_id", "organization_id")}
    regular = {**w, "task_id": "t", "idx": 0, "channel": "a", "value_type": "json", "value": "MQ=="}
    special = {
        **w,
        "task_id": "t",
        "idx": -1,
        "channel": "__error__",
        "value_type": "json",
        "value": "MQ==",
    }
    svc.one("select cornucopia.put_checkpoint_writes(%s::jsonb)", json.dumps([regular, special]))
    svc.one(
        "select cornucopia.put_checkpoint_writes(%s::jsonb)",
        json.dumps([{**regular, "value": "Mg=="}, {**special, "value": "Mg=="}]),
    )
    vals = dict(
        svc.conn.execute(
            "select idx, value from cornucopia.agent_checkpoint_writes where thread_id='event:t1'"
        ).fetchall()
    )
    assert vals == {0: "MQ==", -1: "Mg=="}  # regular writes immutable, special replaceable
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        svc.conn.execute("delete from cornucopia.agent_checkpoints")


def test_optimization_run_idempotency_key(db_url: str, org: str) -> None:  # noqa: F811
    svc = Svc(db_url)
    run = {
        "state_version": 1,
        "config": {},
        "solver_status": "OPTIMAL",
        "verdict": "verified_partial",
        "objectives": {},
        "stages": [],
        "model_stats": {},
        "diagnosis": {},
        "wall_ms": 1,
        "idempotency_key": "exec-1:full_recovery:0",
    }
    results = [
        {
            "candidate": "recommended",
            "recommended": True,
            "verdict": "verified_partial",
            "fingerprint": "f",
            "meals_planned": 1,
            "plan": None,
            "summary": {},
        }
    ]
    a = svc.one(
        "select cornucopia.record_optimization_run(%s,'agent:x',%s::jsonb,%s::jsonb)",
        org,
        json.dumps(run),
        json.dumps(results),
    )
    b = svc.one(
        "select cornucopia.record_optimization_run(%s,'agent:x',%s::jsonb,%s::jsonb)",
        org,
        json.dumps(run),
        json.dumps(results),
    )
    assert a["run_id"] == b["run_id"] and b["duplicate"] is True
