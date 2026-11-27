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
