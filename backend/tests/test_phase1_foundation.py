from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from cornucopia.api.app import create_app
from cornucopia.config import Settings
from cornucopia.persistence.client import RestSupabaseClient, SupabaseError
from cornucopia.persistence.factory import build_client
from cornucopia.persistence.memory import InMemorySupabaseClient

GATEWAY = "https://api.sprites.dev/v1/gateway/supabase/conn123"


def settings(**kw: object) -> Settings:
    base: dict[str, object] = {"CORNUCOPIA_TRANSPORT": "memory", "_env_file": None}
    base.update(kw)
    return Settings(**base)  # type: ignore[arg-type]


# ---------- configuration ----------


def test_gateway_requires_url() -> None:
    with pytest.raises(ValidationError, match="SUPABASE_GATEWAY_URL"):
        settings(CORNUCOPIA_TRANSPORT="gateway")


def test_direct_forbidden_in_production() -> None:
    with pytest.raises(ValidationError, match="not allowed in production"):
        settings(
            CORNUCOPIA_TRANSPORT="direct",
            CORNUCOPIA_ENV="production",
            SUPABASE_URL="https://x.supabase.co",
            SUPABASE_SECRET_KEY="k",
            CORNUCOPIA_API_TOKEN="t",
        )


def test_production_requires_api_token() -> None:
    with pytest.raises(ValidationError, match="CORNUCOPIA_API_TOKEN"):
        settings(
            CORNUCOPIA_TRANSPORT="gateway",
            CORNUCOPIA_ENV="production",
            SUPABASE_GATEWAY_URL=GATEWAY,
        )


def test_factory_has_no_silent_fallback() -> None:
    assert isinstance(build_client(settings()), InMemorySupabaseClient)
    gw = build_client(settings(CORNUCOPIA_TRANSPORT="gateway", SUPABASE_GATEWAY_URL=GATEWAY))
    assert isinstance(gw, RestSupabaseClient)


# ---------- REST client wire format ----------


def _recording_client(
    base: str, responses: list[httpx.Response], **kw: object
) -> tuple[RestSupabaseClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    it = iter(responses)

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return next(it)

    client = RestSupabaseClient(
        base,
        schema="cornucopia",
        transport=httpx.MockTransport(handler),
        **kw,  # type: ignore[arg-type]
    )
    return client, seen


def test_gateway_requests_carry_no_credentials_and_use_schema_profile() -> None:
    client, seen = _recording_client(GATEWAY, [httpx.Response(200, json={"ok": True})])
    client.rpc("health_check")
    req = seen[0]
    assert str(req.url) == f"{GATEWAY}/rest/v1/rpc/health_check"
    assert "authorization" not in req.headers and "apikey" not in req.headers
    assert req.headers["content-profile"] == "cornucopia"


def test_select_builds_postgrest_query() -> None:
    client, seen = _recording_client(GATEWAY, [httpx.Response(200, json=[])])
    client.select("system_probes", filters={"id": "eq.abc"}, order="created_at.desc", limit=5)
    q = seen[0].url.params
    assert q["select"] == "*" and q["id"] == "eq.abc" and q["order"] == "created_at.desc"
    assert q["limit"] == "5" and seen[0].headers["accept-profile"] == "cornucopia"


def test_reads_retry_on_gateway_errors_but_writes_do_not() -> None:
    client, seen = _recording_client(
        GATEWAY, [httpx.Response(503), httpx.Response(200, json=[{"id": 1}])], retries=2
    )
    assert client.select("t") == [{"id": 1}]
    assert len(seen) == 2

    client, seen = _recording_client(GATEWAY, [httpx.Response(503, json={"message": "x"})])
    with pytest.raises(SupabaseError) as exc:
        client.rpc("record_probe", {"p_note": "n", "p_source": "test"})
    assert exc.value.status == 503 and len(seen) == 1


def test_postgrest_error_is_surfaced() -> None:
    body = {"code": "PGRST106", "message": "Invalid schema: cornucopia"}
    client, _ = _recording_client(GATEWAY, [httpx.Response(406, json=body)])
    with pytest.raises(SupabaseError, match="PGRST106"):
        client.select("system_probes")


def test_direct_mode_sends_apikey_only_from_settings() -> None:
    s = settings(
        CORNUCOPIA_TRANSPORT="direct",
        SUPABASE_URL="https://x.supabase.co",
        SUPABASE_SECRET_KEY="sb_secret_test",
    )
    assert "sb_secret_test" not in repr(s)  # SecretStr masks it
    client = build_client(s)
    assert isinstance(client, RestSupabaseClient)


# ---------- API ----------


@pytest.fixture
def api() -> TestClient:
    return TestClient(create_app(settings(), client=InMemorySupabaseClient()))


def test_health(api: TestClient) -> None:
    with api as c:
        body = c.get("/health").json()
    assert body["status"] == "ok" and body["transport"] == "memory"


def test_db_health(api: TestClient) -> None:
    with api as c:
        body = c.get("/health/db").json()
    assert body["status"] == "ok" and body["db_schema"] == "cornucopia"


def test_probe_insert_and_retrieve(api: TestClient) -> None:
    with api as c:
        created = c.post("/api/v1/system/probes", json={"note": "hello"})
        assert created.status_code == 201
        pid = created.json()["id"]
        got = c.get(f"/api/v1/system/probes/{pid}")
        assert got.status_code == 200 and got.json()["note"] == "hello"
        assert c.get("/api/v1/system/probes").json()[0]["id"] == pid


def test_probe_validation_rejects_unknown_fields_and_empty(api: TestClient) -> None:
    with api as c:
        assert c.post("/api/v1/system/probes", json={"note": ""}).status_code == 422
        bad = c.post("/api/v1/system/probes", json={"note": "x", "source": "gateway"})
        assert bad.status_code == 422


def test_token_required_when_configured() -> None:
    app = create_app(settings(CORNUCOPIA_API_TOKEN="s3cret"), client=InMemorySupabaseClient())
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200  # liveness stays open
        assert c.get("/health/db").status_code == 401
        bad = c.get("/health/db", headers={"Authorization": "Bearer nope"})
        assert bad.status_code == 401
        ok = c.get("/health/db", headers={"Authorization": "Bearer s3cret"})
        assert ok.status_code == 200


def test_db_health_reports_errors_without_leaking_config() -> None:
    db = InMemorySupabaseClient()

    def boom(*_: object) -> object:
        raise SupabaseError(401, {"error": "authentication failed"}, method="POST", path="/rpc")

    db.register_rpc("health_check", boom)
    s = settings(SUPABASE_SECRET_KEY="fake-test-secret-value")
    with TestClient(create_app(s, client=db)) as c:
        body = c.get("/health/db").json()
    assert body["status"] == "error" and "fake-test-secret" not in json.dumps(body)
