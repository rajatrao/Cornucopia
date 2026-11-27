"""In-app demo reset: role gate, operator copy, org switch, sample data."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

from cornucopia.api.app import create_app
from cornucopia.config import Settings
from cornucopia.persistence.memory import InMemorySupabaseClient
from tests.auth_helpers import TEST_PASSWORD, add_operator, sign_in


def _app(tmp_path: Path, role: str | None) -> tuple[TestClient, InMemorySupabaseClient]:
    env: dict[str, Any] = {
        "CORNUCOPIA_TRANSPORT": "memory",
        "CORNUCOPIA_ACTIVE_ORG_FILE": str(tmp_path / "active_org.json"),
    }
    if role:
        env["CORNUCOPIA_DEMO_RESET_ROLE"] = role
    s = Settings(_env_file=None, **env)  # type: ignore[call-arg]
    db = InMemorySupabaseClient()
    app = create_app(s, client=db)
    app.state.demo_reset_background = False
    c = TestClient(app)
    c.__enter__()

    def factory(headers: dict[str, str]) -> httpx.Client:
        t = TestClient(app, base_url="http://testserver/api/v1")
        t.headers.update(headers)
        return t

    app.state.demo_reset._factory = factory
    return c, db


def test_reset_disabled_by_default(tmp_path: Path) -> None:
    c, db = _app(tmp_path, None)
    sign_in(c, db)
    assert c.get("/api/v1/admin/demo-reset").json()["enabled"] is False
    assert c.post("/api/v1/admin/demo-reset").status_code == 404


def test_viewer_cannot_reset(tmp_path: Path) -> None:
    c, db = _app(tmp_path, "approver")
    sign_in(c, db, "watcher", "viewer")
    assert c.post("/api/v1/admin/demo-reset").status_code == 403


def test_reset_moves_to_fresh_seeded_org_and_keeps_accounts(tmp_path: Path) -> None:
    c, db = _app(tmp_path, "approver")
    sign_in(c, db, "judge", "approver")
    org0 = c.get("/api/v1/organization").json()
    add_operator(db, org0["id"], "judge-viewer", "viewer")

    r = c.post("/api/v1/admin/demo-reset")
    assert r.status_code == 202, r.text
    st = c.get("/api/v1/admin/demo-reset").json()
    assert st["state"] == "done", st
    assert st["organization"].startswith("thanksgiving-2026-")
    assert "500/500" in st["summary"]
    assert (tmp_path / "active_org.json").read_text().find(st["organization"]) > 0

    # old sessions belong to the old organization
    assert c.get("/api/v1/organization").status_code == 401
    for user in ("judge", "judge-viewer"):
        r = c.post("/api/v1/auth/login", json={"username": user, "password": TEST_PASSWORD})
        assert r.status_code == 200, (user, r.text)
    c.headers["X-Cornucopia-Session"] = c.post(
        "/api/v1/auth/login", json={"username": "judge", "password": TEST_PASSWORD}
    ).json()["token"]
    org1 = c.get("/api/v1/organization").json()
    assert org1["id"] != org0["id"]
    assert len(c.get("/api/v1/inventory/donations").json()) == 3

    # a second reset works too, and keeps the same prefix
    assert c.post("/api/v1/admin/demo-reset").status_code == 202
    assert c.get("/api/v1/admin/demo-reset").json()["state"] == "done"
