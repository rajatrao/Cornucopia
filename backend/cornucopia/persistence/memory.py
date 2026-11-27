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
