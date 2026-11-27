"""In-memory SupabaseClient for unit tests.

Implements only the subset of PostgREST that repositories use: ``eq.``
filters, ``order=<col>.<asc|desc>``, ``limit``, inserts with server-side
defaults, and RPC functions registered as Python callables. It is never
selected outside tests (``CORNUCOPIA_TRANSPORT=memory``).
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from cornucopia.persistence.client import JSON, SupabaseClient, SupabaseError

RpcFn = Callable[["InMemorySupabaseClient", Mapping[str, Any]], JSON]


class InMemorySupabaseClient(SupabaseClient):
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, JSON]]] = {}
        self._rpcs: dict[str, RpcFn] = {}
        self.register_rpc("health_check", _health_check)
        self.register_rpc("record_probe", _record_probe)
        self.register_rpc("ensure_organization", _ensure_organization)
        self.register_rpc("write_resource", _write_resource)
        self.register_rpc("ingest_event", _ingest_event)
        self.register_rpc("get_operational_snapshot", _snapshot)
        self.register_rpc("record_optimization_run", _record_run)
        self.register_rpc("put_checkpoint", _put_checkpoint)
        self.register_rpc("put_checkpoint_writes", _put_checkpoint_writes)
        self.register_rpc("claim_next_execution", _claim)
        self.register_rpc("heartbeat_execution", _heartbeat)
        self.register_rpc("record_execution_step", _record_step)
        self.register_rpc("finish_execution", _finish)

    def register_rpc(self, name: str, fn: RpcFn) -> None:
        self._rpcs[name] = fn

    def select(
        self,
        table: str,
        *,
        filters: Mapping[str, str] | None = None,
        columns: str = "*",
        order: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, JSON]]:
        rows = [r for r in self.tables.get(table, []) if _matches(r, filters or {})]
        if order:
            col, _, direction = order.partition(".")
            rows.sort(key=lambda r: str(r.get(col)), reverse=direction == "desc")
        if limit is not None:
            rows = rows[:limit]
        return copy.deepcopy(rows)

    def insert(self, table: str, rows: list[dict[str, JSON]]) -> list[dict[str, JSON]]:
        out = []
        for row in rows:
            full = {"id": str(uuid.uuid4()), "created_at": _now(), **row}
            self.tables.setdefault(table, []).append(full)
            out.append(copy.deepcopy(full))
        return out

    def rpc(self, function: str, args: Mapping[str, JSON] | None = None) -> JSON:
        fn = self._rpcs.get(function)
        if fn is None:
            raise SupabaseError(404, {"code": "PGRST202"}, method="POST", path=f"/rpc/{function}")
        return fn(self, dict(args or {}))


def _matches(row: Mapping[str, JSON], filters: Mapping[str, str]) -> bool:
    for col, expr in filters.items():
        op, _, value = expr.partition(".")
        if op != "eq":
            raise NotImplementedError(f"memory client supports eq filters only, got {op}")
        if str(row.get(col)) != value:
            return False
    return True


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _health_check(_: InMemorySupabaseClient, __: Mapping[str, Any]) -> JSON:
    return {"ok": True, "schema": "cornucopia", "server_time": _now(), "backend": "memory"}


def _record_probe(db: InMemorySupabaseClient, args: Mapping[str, Any]) -> JSON:
    return db.insert("system_probes", [{"note": args["p_note"], "source": args["p_source"]}])[0]


# --- Phase 2 test doubles. The authoritative semantics live in SQL and are
# --- tested against real Postgres in tests/db; these only let API tests run.

_ORG_SCOPED_EXEMPT = {"recipe_ingredients", "meal_components"}

# Server-side column defaults the real schema provides (see models.py).
_DEFAULTS: dict[str, dict[str, Any]] = {
    "deliveries": {"status": "scheduled", "delay_minutes": 0, "status_reason": None},
    "commitments": {"status": "active", "version": 1, "diet_requirements": [], "delivery_id": None},
    "volunteers": {
        "available": True,
        "available_hours": "4",
        "unavailable_reason": None,
        "team_id": None,
    },
    "preparation_teams": {"active": True},
    "ingredients": {
        "attributes": [],
        "category": "other",
        "density_g_per_ml": None,
        "unit_weight_g": None,
        "perishable_days": None,
    },
    "recipe_ingredients": {"optional": False},
    "ingredient_substitutions": {"recipe_id": None, "notes": None},
    "meal_components": {"portions": "1"},
    "recipes": {"instructions": None},
    "donors": {"kind": "individual", "contact": None},
    "meals": {"description": None},
}


def _ensure_organization(db: InMemorySupabaseClient, args: Mapping[str, Any]) -> JSON:
    for org in db.tables.get("organizations", []):
        if org["slug"] == args["p_slug"]:
            return copy.deepcopy(org)
    org = db.insert("organizations", [{"slug": args["p_slug"], "name": args["p_name"]}])[0]
    db.tables.setdefault("operational_state", []).append(
        {"organization_id": org["id"], "version": 0}
    )
    return org


def _bump(db: InMemorySupabaseClient, org: str) -> int:
    for s in db.tables.setdefault("operational_state", []):
        if s["organization_id"] == org:
            s["version"] += 1
            return int(s["version"])
    db.tables["operational_state"].append({"organization_id": org, "version": 1})
    return 1


def _write_resource(db: InMemorySupabaseClient, args: Mapping[str, Any]) -> JSON:
    table, action, org = args["p_table"], args["p_action"], args["p_organization_id"]
    values = dict(args["p_values"] or {})
    rows = db.tables.setdefault(table, [])
    scoped = table not in _ORG_SCOPED_EXEMPT
    if action == "insert":
        if scoped:
            values["organization_id"] = org
        row = db.insert(table, [{"updated_at": _now(), **_DEFAULTS.get(table, {}), **values}])[0]
    else:
        match = [
            r
            for r in rows
            if r["id"] == args["p_id"] and (not scoped or r.get("organization_id") == org)
        ]
        if not match:
            raise SupabaseError(
                400,
                {"code": "P0404", "message": f"{table} not found"},
                method="POST",
                path="/rpc/write_resource",
            )
        if action == "update":
            match[0].update(values, updated_at=_now())
            row = copy.deepcopy(match[0])
        else:
            rows.remove(match[0])
            row = match[0]
    db.tables.setdefault("audit_records", []).append(
        {
            "id": len(db.tables.get("audit_records", [])) + 1,
            "organization_id": org,
            "table_name": table,
            "record_id": row["id"],
            "action": action.upper(),
            "actor": args["p_actor"],
            "at": _now(),
        }
    )
    _bump(db, org)
    return row


def _ingest_event(db: InMemorySupabaseClient, args: Mapping[str, Any]) -> JSON:
    import hashlib
    import json

    org, key, payload = args["p_organization_id"], args["p_idempotency_key"], args["p_payload"]
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    for ev in db.tables.get("operational_events", []):
        if ev["organization_id"] == org and ev["idempotency_key"] == key:
            if ev["payload_hash"] != digest:
                raise SupabaseError(
                    400,
                    {"code": "P0409", "message": "key reused"},
                    method="POST",
                    path="/rpc/ingest_event",
                )
            return {"duplicate": True, "event": copy.deepcopy(ev)}
    effect: dict[str, Any] = {}
    etype = args["p_event_type"]
    if etype == "DONATION_CREATED":
        donation = db.insert(
            "donations",
            [
                {
                    "organization_id": org,
                    "description": payload["description"],
                    "status": "received" if payload["received"] else "pledged",
                    "donor_id": payload.get("donor_id"),
                    "expected_at": None,
                    "received_at": None,
                    "cancelled_at": None,
                    "cancel_reason": None,
                    "source_event_id": None,
                }
            ],
        )[0]
        for lot in payload["lots"]:
            db.insert(
                "inventory_lots",
                [
                    {
                        "organization_id": org,
                        "ingredient_id": lot["ingredient_id"],
                        "donation_id": donation["id"],
                        "reported_quantity": lot["quantity"],
                        "reported_unit": lot["unit"],
                        "initial_quantity_base": lot["quantity_base"],
                        "quantity_base": lot["quantity_base"],
                        "base_unit": lot["base_unit"],
                        "status": "available" if payload["received"] else "pledged",
                        "expires_at": lot.get("expires_at"),
                    }
                ],
            )
        effect = {"donation_id": donation["id"], "lots_created": len(payload["lots"])}
    elif etype == "DONATION_CANCELLED":
        for d in db.tables.get("donations", []):
            if d["id"] == payload["donation_id"]:
                d["status"] = "cancelled"
        for lot in db.tables.get("inventory_lots", []):
            if lot["donation_id"] == payload["donation_id"]:
                lot["status"], lot["quantity_base"] = "cancelled", "0"
        effect = {"donation_id": payload["donation_id"]}
    elif etype == "INVENTORY_ADJUSTED":
        from decimal import Decimal

        for lot in db.tables.get("inventory_lots", []):
            if lot["id"] == payload["lot_id"]:
                after = Decimal(str(lot["quantity_base"])) + Decimal(payload["delta_base"])
                if after < 0:
                    raise SupabaseError(
                        400,
                        {"code": "P0422", "message": "negative"},
                        method="POST",
                        path="/rpc/ingest_event",
                    )
                lot["quantity_base"] = str(after)
                effect = {"lot_id": lot["id"], "after_base": str(after)}
    version = _bump(db, org)
    ev = db.insert(
        "operational_events",
        [
            {
                "organization_id": org,
                "idempotency_key": key,
                "event_type": etype,
                "payload": payload,
                "payload_hash": digest,
                "actor": args["p_actor"],
                "correlation_id": args["p_correlation_id"],
                "effect": effect,
                "state_version": version,
                "processing_status": "pending",
                "processing_note": None,
                "processed_at": None,
            }
        ],
    )[0]
    return {"duplicate": False, "event": ev}


_SNAPSHOT_TABLES = {
    "ingredients": "ingredients",
    "lots": "inventory_lots",
    "donations": "donations",
    "recipes": "recipes",
    "recipe_ingredients": "recipe_ingredients",
    "substitutions": "ingredient_substitutions",
    "meals": "meals",
    "meal_components": "meal_components",
    "commitments": "commitments",
    "teams": "preparation_teams",
    "volunteers": "volunteers",
    "deliveries": "deliveries",
}


def _snapshot(db: InMemorySupabaseClient, args: Mapping[str, Any]) -> JSON:
    org = args["p_organization_id"]
    state = [s for s in db.tables.get("operational_state", []) if s["organization_id"] == org]
    out: dict[str, Any] = {
        "organization_id": org,
        "as_of": _now(),
        "state_version": state[0]["version"] if state else 0,
    }
    for key, table in _SNAPSHOT_TABLES.items():
        rows = db.tables.get(table, [])
        if table not in _ORG_SCOPED_EXEMPT:
            rows = [r for r in rows if r.get("organization_id") == org]
        out[key] = copy.deepcopy(rows)
    return out


def _record_run(db: InMemorySupabaseClient, args: Mapping[str, Any]) -> JSON:
    run = dict(args["p_run"])
    key = run.get("idempotency_key")
    if key:
        for r in db.tables.get("optimization_runs", []):
            if r.get("idempotency_key") == key:
                return {"run_id": r["id"], "duplicate": True}
    row = db.insert(
        "optimization_runs",
        [
            {
                "organization_id": args["p_organization_id"],
                "requested_by": args["p_actor"],
                "correlation_id": run.get("correlation_id"),
                **{k: v for k, v in run.items() if k != "correlation_id"},
            }
        ],
    )[0]
    db.insert("optimization_results", [{"run_id": row["id"], **r} for r in args["p_results"]])
    return {"run_id": row["id"]}


# --- Phase 5 test doubles (authoritative semantics: db/sql/0006_agent.sql,
# --- tested against Postgres in tests/db/test_agent_sql.py)


def _put_checkpoint(db: InMemorySupabaseClient, args: Mapping[str, Any]) -> JSON:
    row = dict(args["p_row"])
    rows = db.tables.setdefault("agent_checkpoints", [])
    key = (row["thread_id"], row["checkpoint_ns"], row["checkpoint_id"])
    if not any((r["thread_id"], r["checkpoint_ns"], r["checkpoint_id"]) == key for r in rows):
        rows.append({**row, "created_at": _now()})
    return True


def _put_checkpoint_writes(db: InMemorySupabaseClient, args: Mapping[str, Any]) -> JSON:
    rows = db.tables.setdefault("agent_checkpoint_writes", [])
    n = 0
    for w in args["p_rows"]:
        key = (w["thread_id"], w["checkpoint_ns"], w["checkpoint_id"], w["task_id"], w["idx"])
        existing = [
            r
            for r in rows
            if (r["thread_id"], r["checkpoint_ns"], r["checkpoint_id"], r["task_id"], r["idx"])
            == key
        ]
        if existing and w["idx"] >= 0:
            continue
        for e in existing:
            rows.remove(e)
        rows.append(dict(w))
        n += 1
    return n


def _lease_ok(ex: dict[str, Any], worker: str, attempt: int) -> bool:
    return bool(
        ex["lease_owner"] == worker
        and ex["attempt"] == attempt
        and ex["status"] == "running"
        and ex["lease_expires_at"] >= datetime.now(UTC)
    )


def _step(
    db: InMemorySupabaseClient,
    ex: dict[str, Any],
    node: str,
    status: str,
    detail: Mapping[str, Any],
) -> None:
    steps = db.tables.setdefault("agent_execution_steps", [])
    steps.append(
        {
            "id": len(steps) + 1,
            "execution_id": ex["id"],
            "attempt": ex["attempt"],
            "node": node,
            "status": status,
            "detail": dict(detail),
            "at": _now(),
        }
    )


def _claim(db: InMemorySupabaseClient, args: Mapping[str, Any]) -> JSON:
    from datetime import timedelta

    org, worker = args["p_organization_id"], args["p_worker"]
    lease = timedelta(seconds=int(args["p_lease_seconds"]))
    now = datetime.now(UTC)
    execs = db.tables.setdefault("agent_executions", [])
    events = db.tables.setdefault("operational_events", [])
    for ex in sorted(execs, key=lambda e: e["created_at"]):
        if (
            ex["organization_id"] == org
            and ex["status"] == "running"
            and ex["lease_expires_at"] < now
        ):
            ex.update(
                lease_owner=worker,
                attempt=ex["attempt"] + 1,
                lease_expires_at=now + lease,
                heartbeat_at=now,
            )
            _step(db, ex, ex.get("current_node") or "supervisor", "resumed", {"worker": worker})
            ev = next(e for e in events if e["id"] == ex["event_id"])
            return {"resumed": True, "execution": _jsonable(ex), "event": copy.deepcopy(ev)}
    for ev in sorted(events, key=lambda e: (e["created_at"], e["id"])):
        if ev["organization_id"] != org or ev["processing_status"] != "pending":
            continue
        if any(x["event_id"] == ev["id"] for x in execs):
            ev["processing_status"] = "processed"
            return None
        ex = {
            "id": str(uuid.uuid4()),
            "organization_id": org,
            "event_id": ev["id"],
            "thread_id": f"event:{ev['id']}",
            "correlation_id": ev["correlation_id"],
            "status": "running",
            "current_node": None,
            "last_completed_node": None,
            "retry_count": 0,
            "attempt": 1,
            "lease_owner": worker,
            "lease_expires_at": now + lease,
            "heartbeat_at": now,
            "result": None,
            "error": None,
            "created_at": _now(),
            "finished_at": None,
        }
        execs.append(ex)
        ev["processing_status"] = "processing"
        _step(db, ex, "supervisor", "claimed", {"worker": worker})
        return {"resumed": False, "execution": _jsonable(ex), "event": copy.deepcopy(ev)}
    return None


def _jsonable(ex: dict[str, Any]) -> dict[str, Any]:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in ex.items()}


def _find_exec(db: InMemorySupabaseClient, exec_id: str) -> dict[str, Any]:
    return next(x for x in db.tables.get("agent_executions", []) if x["id"] == exec_id)


def _heartbeat(db: InMemorySupabaseClient, args: Mapping[str, Any]) -> JSON:
    from datetime import timedelta

    ex = _find_exec(db, args["p_execution_id"])
    if (
        ex["lease_owner"] != args["p_worker"]
        or ex["attempt"] != args["p_attempt"]
        or ex["status"] != "running"
    ):
        return False
    ex["lease_expires_at"] = datetime.now(UTC) + timedelta(seconds=int(args["p_lease_seconds"]))
    ex["heartbeat_at"] = datetime.now(UTC)
    return True


def _record_step(db: InMemorySupabaseClient, args: Mapping[str, Any]) -> JSON:
    ex = _find_exec(db, args["p_execution_id"])
    if not _lease_ok(ex, args["p_worker"], args["p_attempt"]):
        return False
    _step(db, ex, args["p_node"], args["p_status"], args.get("p_detail") or {})
    ex["current_node"] = args["p_node"]
    if args["p_status"] == "completed":
        ex["last_completed_node"] = args["p_node"]
    if args["p_status"] == "retry":
        ex["retry_count"] += 1
    return True


def _finish(db: InMemorySupabaseClient, args: Mapping[str, Any]) -> JSON:
    ex = _find_exec(db, args["p_execution_id"])
    if not _lease_ok(ex, args["p_worker"], args["p_attempt"]):
        return False
    status = args["p_status"]
    ex.update(
        status=status,
        result=args.get("p_result"),
        error=args.get("p_error"),
        finished_at=_now(),
        lease_owner=None,
    )
    for ev in db.tables.get("operational_events", []):
        if ev["id"] == ex["event_id"]:
            ev["processing_status"] = {"escalated": "escalated", "failed": "failed"}.get(
                status, "processed"
            )
    return True
