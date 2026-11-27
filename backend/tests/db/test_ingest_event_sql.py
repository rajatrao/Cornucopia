"""Database-level tests of the Phase 2 migration on a real local Postgres.

They apply supabase/migrations/*.sql to a fresh scratch database and run as
``service_role``, exactly the role the Sprites connector's key maps to.
Skipped unless CORNUCOPIA_TEST_PG_ADMIN_URL points at a disposable server.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

psycopg = pytest.importorskip("psycopg")

ADMIN_URL = os.environ.get("CORNUCOPIA_TEST_PG_ADMIN_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="CORNUCOPIA_TEST_PG_ADMIN_URL not set")
MIGRATIONS = sorted((Path(__file__).resolve().parents[3] / "supabase" / "migrations").glob("*.sql"))


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    assert ADMIN_URL
    name = f"cn_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f"create database {name}")
    url = ADMIN_URL.rsplit("/", 1)[0] + f"/{name}"
    with psycopg.connect(url, autocommit=True) as conn:
        for f in MIGRATIONS:
            with conn.transaction():
                conn.execute(f.read_text())  # type: ignore[call-overload]
    yield url
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f"drop database {name} with (force)")


class Svc:
    """A connection acting as service_role, like the connector."""

    def __init__(self, url: str) -> None:
        self.conn = psycopg.connect(url, autocommit=True)
        self.conn.execute("set role service_role")

    def one(self, sql: str, *args: Any) -> Any:
        row = self.conn.execute(sql, args).fetchone()  # type: ignore[call-overload]
        return row[0] if row else None

    def rpc_ingest(
        self, org: str, key: str, etype: str, payload: dict[str, Any], actor: str = "op:test"
    ) -> dict[str, Any]:
        result: dict[str, Any] = self.one(
            "select cornucopia.ingest_event(%s, %s, %s, %s::jsonb, %s, %s)",
            org,
            key,
            etype,
            json.dumps(payload),
            actor,
            str(uuid.uuid4()),
        )
        return result


def _write(
    self: Svc,
    org: str,
    table: str,
    action: str,
    rid: str | None,
    values: dict[str, Any],
    actor: str = "op:test",
) -> dict[str, Any]:
    row: dict[str, Any] = self.one(
        "select cornucopia.write_resource(%s, %s, %s, %s, %s, %s::jsonb)",
        org,
        actor,
        table,
        action,
        rid,
        json.dumps(values),
    )
    return row


Svc.write = _write  # type: ignore[attr-defined]


@pytest.fixture(scope="module")
def svc(db_url: str) -> Svc:
    return Svc(db_url)


@pytest.fixture(scope="module")
def org(svc: Svc) -> str:
    row = svc.one("select (cornucopia.ensure_organization('test-org','Test Org')).id")
    return str(row)


@pytest.fixture(scope="module")
def rice(svc: Svc, org: str) -> str:
    return str(
        svc.write(
            org,
            "ingredients",
            "insert",
            None,
            {"name": "Rice", "category": "grain", "base_unit": "g"},
        )["id"]
    )


def _donation(rice: str, grams: str = "81646.627") -> dict[str, Any]:
    return {
        "description": "Rice from Harvest Co-op",
        "received": True,
        "lots": [
            {
                "ingredient_id": rice,
                "quantity": "180",
                "unit": "lb",
                "quantity_base": grams,
                "base_unit": "g",
            }
        ],
    }


def test_donation_created_is_idempotent(svc: Svc, org: str, rice: str) -> None:
    key = f"donation-{uuid.uuid4()}"
    first = svc.rpc_ingest(org, key, "DONATION_CREATED", _donation(rice))
    second = svc.rpc_ingest(org, key, "DONATION_CREATED", _donation(rice))
    assert first["duplicate"] is False and second["duplicate"] is True
    assert first["event"]["id"] == second["event"]["id"]
    donation_id = first["event"]["effect"]["donation_id"]
    assert svc.one("select count(*) from cornucopia.donations where id = %s", donation_id) == 1
    assert (
        svc.one(
            "select count(*) from cornucopia.inventory_lots where donation_id = %s", donation_id
        )
        == 1
    )
    assert (
        svc.one(
            "select count(*) from cornucopia.operational_events where idempotency_key = %s", key
        )
        == 1
    )


def test_key_reuse_with_different_payload_is_rejected(svc: Svc, org: str, rice: str) -> None:
    key = f"donation-{uuid.uuid4()}"
    svc.rpc_ingest(org, key, "DONATION_CREATED", _donation(rice))
    with pytest.raises(psycopg.Error, match="different event"):
        svc.rpc_ingest(org, key, "DONATION_CREATED", _donation(rice, "1000"))


def test_cancellation_removes_inventory_and_is_audited(svc: Svc, org: str, rice: str) -> None:
    created = svc.rpc_ingest(org, f"k-{uuid.uuid4()}", "DONATION_CREATED", _donation(rice))
    donation_id = created["event"]["effect"]["donation_id"]
    v_before = svc.one(
        "select version from cornucopia.operational_state where organization_id=%s", org
    )
    res = svc.rpc_ingest(
        org,
        f"k-{uuid.uuid4()}",
        "DONATION_CANCELLED",
        {"donation_id": donation_id, "reason": "truck broke down"},
        actor="op:raj",
    )
    removed = res["event"]["effect"]["lots_removed"]
    assert len(removed) == 1 and removed[0]["removed_base"] == 81646.627
    assert (
        svc.one("select status from cornucopia.donations where id=%s", donation_id) == "cancelled"
    )
    assert (
        svc.one(
            "select sum(quantity_base) from cornucopia.inventory_lots where donation_id=%s",
            donation_id,
        )
        == 0
    )
    v_after = svc.one(
        "select version from cornucopia.operational_state where organization_id=%s", org
    )
    assert v_after > v_before and res["event"]["state_version"] == v_after
    actors = svc.one(
        "select array_agg(distinct actor) from cornucopia.audit_records where event_id = %s",
        res["event"]["id"],
    )
    assert actors == ["op:raj"]
    # cancelling twice with a new key is a conflict, not a second effect
    with pytest.raises(psycopg.Error, match="already cancelled"):
        svc.rpc_ingest(
            org,
            f"k-{uuid.uuid4()}",
            "DONATION_CANCELLED",
            {"donation_id": donation_id, "reason": "again"},
        )


def test_inventory_cannot_go_negative(svc: Svc, org: str, rice: str) -> None:
    created = svc.rpc_ingest(org, f"k-{uuid.uuid4()}", "DONATION_CREATED", _donation(rice, "1000"))
    lot = svc.one(
        "select id from cornucopia.inventory_lots where donation_id=%s",
        created["event"]["effect"]["donation_id"],
    )
    ok = svc.rpc_ingest(
        org,
        f"k-{uuid.uuid4()}",
        "INVENTORY_ADJUSTED",
        {
            "lot_id": str(lot),
            "delta_base": "-400",
            "base_unit": "g",
            "direction": "remove",
            "quantity": "400",
            "unit": "g",
            "reason": "spill",
        },
    )
    assert ok["event"]["effect"]["after_base"] == 600
    with pytest.raises(psycopg.Error, match="negative"):
        svc.rpc_ingest(
            org,
            f"k-{uuid.uuid4()}",
            "INVENTORY_ADJUSTED",
            {
                "lot_id": str(lot),
                "delta_base": "-601",
                "base_unit": "g",
                "direction": "remove",
                "quantity": "601",
                "unit": "g",
                "reason": "spill",
            },
        )
    zero = svc.rpc_ingest(
        org,
        f"k-{uuid.uuid4()}",
        "INVENTORY_ADJUSTED",
        {
            "lot_id": str(lot),
            "delta_base": "-600",
            "base_unit": "g",
            "direction": "remove",
            "quantity": "600",
            "unit": "g",
            "reason": "used",
        },
    )
    assert zero["event"]["effect"]["after_base"] == 0
    assert svc.one("select status from cornucopia.inventory_lots where id=%s", lot) == "depleted"


def test_failed_event_leaves_no_trace(svc: Svc, org: str) -> None:
    before = svc.one("select count(*) from cornucopia.operational_events")
    with pytest.raises(psycopg.Error):
        svc.rpc_ingest(
            org,
            f"k-{uuid.uuid4()}",
            "VOLUNTEER_UNAVAILABLE",
            {"volunteer_id": str(uuid.uuid4()), "reason": "sick"},
        )
    assert svc.one("select count(*) from cornucopia.operational_events") == before


def test_journal_and_audit_are_append_only(svc: Svc, org: str, rice: str) -> None:
    ev = svc.rpc_ingest(org, f"k-{uuid.uuid4()}", "DONATION_CREATED", _donation(rice))["event"]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        svc.conn.execute(
            "update cornucopia.operational_events set payload='{}' where id=%s", (ev["id"],)
        )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        svc.conn.execute("delete from cornucopia.operational_events where id=%s", (ev["id"],))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        svc.conn.execute(
            "update cornucopia.operational_events set processing_status='processed' where id=%s",
            (ev["id"],),
        )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        svc.conn.execute("delete from cornucopia.audit_records")


def test_concurrent_duplicate_submissions_apply_once(db_url: str, org: str, rice: str) -> None:
    key = f"race-{uuid.uuid4()}"
    results: list[dict[str, Any]] = []
    errors: list[BaseException] = []

    def submit() -> None:
        try:
            results.append(Svc(db_url).rpc_ingest(org, key, "DONATION_CREATED", _donation(rice)))
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=submit) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert sorted(r["duplicate"] for r in results) == [False] + [True] * 5
    svc = Svc(db_url)
    assert (
        svc.one("select count(*) from cornucopia.operational_events where idempotency_key=%s", key)
        == 1
    )
    assert len({r["event"]["id"] for r in results}) == 1


def test_anon_has_no_access(db_url: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("set role anon")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("select * from cornucopia.inventory_lots")


def test_direct_table_writes_are_refused(svc: Svc, org: str) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        svc.conn.execute(
            "insert into cornucopia.donors (organization_id, name) values (%s, 'x')", (org,)
        )


def test_write_resource_records_actor_and_bumps_version(svc: Svc, org: str) -> None:
    v0 = svc.one("select version from cornucopia.operational_state where organization_id=%s", org)
    team = svc.write(
        org,
        "preparation_teams",
        "insert",
        None,
        {
            "name": f"Kitchen {uuid.uuid4().hex[:4]}",
            "capacity_portions_per_hour": "60",
            "available_hours": "6",
        },
        actor="op:raj",
    )
    upd = svc.write(
        org, "preparation_teams", "update", team["id"], {"available_hours": "5"}, actor="op:sam"
    )
    assert upd["available_hours"] == 5 and upd["updated_at"] >= team["updated_at"]
    rows = svc.conn.execute(
        "select action, actor from cornucopia.audit_records where record_id=%s order by id",
        (team["id"],),
    ).fetchall()
    assert rows == [("INSERT", "op:raj"), ("UPDATE", "op:sam")]
    v1 = svc.one("select version from cornucopia.operational_state where organization_id=%s", org)
    assert v1 >= v0 + 2


def test_write_resource_enforces_boundaries(svc: Svc, org: str, rice: str) -> None:
    other = str(svc.one("select (cornucopia.ensure_organization('other-org','Other')).id"))
    with pytest.raises(psycopg.Error, match="not writable"):
        svc.write(org, "inventory_lots", "insert", None, {"ingredient_id": rice})
    with pytest.raises(psycopg.Error, match="server-managed"):
        svc.write(org, "donors", "insert", None, {"id": str(uuid.uuid4()), "name": "x"})
    with pytest.raises(psycopg.Error, match="not found"):
        svc.write(other, "ingredients", "update", rice, {"category": "other"})
    recipe = svc.write(
        org,
        "recipes",
        "insert",
        None,
        {"name": f"Pilaf {uuid.uuid4().hex[:4]}", "yield_portions": "10", "prep_minutes": 30},
    )
    with pytest.raises(psycopg.Error, match="another organization"):
        svc.write(
            other,
            "recipe_ingredients",
            "insert",
            None,
            {
                "recipe_id": recipe["id"],
                "ingredient_id": rice,
                "quantity": "1",
                "unit": "kg",
                "quantity_base": "1000",
            },
        )
    ri = svc.write(
        org,
        "recipe_ingredients",
        "insert",
        None,
        {
            "recipe_id": recipe["id"],
            "ingredient_id": rice,
            "quantity": "1",
            "unit": "kg",
            "quantity_base": "1000",
        },
    )
    assert ri["quantity_base"] == 1000
    with pytest.raises(psycopg.Error, match="unit"):
        svc.write(org, "recipe_ingredients", "update", ri["id"], {"unit": "bushel"})
