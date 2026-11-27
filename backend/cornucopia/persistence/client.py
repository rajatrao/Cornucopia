"""Supabase data access behind one interface.

``SupabaseClient`` is the only thing repositories depend on. Two
implementations exist:

* ``RestSupabaseClient`` speaks PostgREST over HTTP. Pointed at the Sprites
  gateway it sends no credentials (the gateway authenticates the Sprite and
  injects the key). Pointed directly at the project (local dev) it sends the
  ``apikey`` header from ``.env``.
* ``InMemorySupabaseClient`` (``memory.py``) implements the same contract for
  tests.

Consequential multi-row writes are RPC calls to plpgsql functions, because
separate REST requests are not one transaction.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

import httpx

JSON = Any


class SupabaseError(RuntimeError):
    def __init__(self, status: int, body: JSON, *, method: str, path: str) -> None:
        self.status = status
        self.body = body
        self.method = method
        self.path = path
        code = body.get("code") if isinstance(body, dict) else None
        msg = body.get("message") if isinstance(body, dict) else body
        super().__init__(f"{method} {path} -> {status} {code or ''} {msg}".strip())


class SupabaseClient(ABC):
    """Minimal PostgREST surface used by repositories."""

    @abstractmethod
    def select(
        self,
        table: str,
        *,
        filters: Mapping[str, str] | None = None,
        columns: str = "*",
        order: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, JSON]]: ...

    @abstractmethod
    def insert(self, table: str, rows: list[dict[str, JSON]]) -> list[dict[str, JSON]]: ...

    @abstractmethod
    def rpc(self, function: str, args: Mapping[str, JSON] | None = None) -> JSON: ...

    def close(self) -> None:  # noqa: B027 - optional hook
        pass


_RETRYABLE_STATUS = {502, 503, 504}


class RestSupabaseClient(SupabaseClient):
    def __init__(
        self,
        base_url: str,
        *,
        schema: str,
        headers: Mapping[str, str] | None = None,
        timeout_s: float = 15.0,
        retries: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._schema = schema
        self._retries = retries
        self._http = httpx.Client(
            base_url=base_url.rstrip("/") + "/rest/v1",
            headers={"Accept": "application/json", **(headers or {})},
            timeout=timeout_s,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json: JSON = None,
        write: bool = False,
        prefer: str | None = None,
    ) -> JSON:
        headers = {"Accept-Profile": self._schema}
        if write:
            headers["Content-Profile"] = self._schema
        if prefer:
            headers["Prefer"] = prefer
        # Only idempotent reads are retried automatically. Writes are retried
        # only by callers that pass an idempotency key into an RPC.
        attempts = 1 + (self._retries if method == "GET" else 0)
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                resp = self._http.request(method, path, params=params, json=json, headers=headers)
            except httpx.TransportError as exc:  # connection dropped, e.g. Sprite pause
                last = exc
            else:
                if resp.status_code in _RETRYABLE_STATUS and attempt + 1 < attempts:
                    last = SupabaseError(resp.status_code, resp.text, method=method, path=path)
                elif resp.is_error:
                    raise SupabaseError(resp.status_code, _body(resp), method=method, path=path)
                else:
                    return _body(resp) if resp.content else None
            time.sleep(min(0.25 * 2**attempt, 2.0))
        assert last is not None
        raise last

    def select(
        self,
        table: str,
        *,
        filters: Mapping[str, str] | None = None,
        columns: str = "*",
        order: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, JSON]]:
        params: dict[str, str] = {"select": columns, **(filters or {})}
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = str(limit)
        result = self._request("GET", f"/{table}", params=params)
        return list(result or [])

    def insert(self, table: str, rows: list[dict[str, JSON]]) -> list[dict[str, JSON]]:
        result = self._request(
            "POST", f"/{table}", json=rows, write=True, prefer="return=representation"
        )
        return list(result or [])

    def rpc(self, function: str, args: Mapping[str, JSON] | None = None) -> JSON:
        return self._request("POST", f"/rpc/{function}", json=dict(args or {}), write=True)

    def openapi_root(self) -> httpx.Response:
        """Raw schema probe used by connectivity checks."""
        return self._http.get(
            "/", headers={"Accept": "application/openapi+json", "Accept-Profile": self._schema}
        )


def _body(resp: httpx.Response) -> JSON:
    try:
        return resp.json()
    except ValueError:
        return resp.text
