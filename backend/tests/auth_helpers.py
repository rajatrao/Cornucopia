"""Test helper: create an operator in the in-memory store and sign in."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from cornucopia.auth import hash_password
from cornucopia.persistence.memory import InMemorySupabaseClient

TEST_PASSWORD = "correct-horse-battery-staple"  # test value only  # noqa: S105


def add_operator(db: InMemorySupabaseClient, org_id: str, username: str, role: str) -> str:
    op_id = str(uuid.uuid4())
    db.tables.setdefault("operators", []).append(
        {
            "id": op_id,
            "organization_id": org_id,
            "username": username,
            "display_name": username.title(),
            "role": role,
            "active": True,
            "password_hash": hash_password(TEST_PASSWORD),
            "created_at": "2026-01-01T00:00:00Z",
        }
    )
    return op_id


def sign_in(
    c: TestClient, db: InMemorySupabaseClient, username: str = "tester", role: str = "admin"
) -> str:
    org = db.rpc(
        "ensure_organization",
        {"p_slug": "thanksgiving-2026", "p_name": "Thanksgiving Community Food Rescue"},
    )
    if not any(o["username"] == username for o in db.tables.get("operators", [])):
        add_operator(db, str(org["id"]), username, role)
    r = c.post("/api/v1/auth/login", json={"username": username, "password": TEST_PASSWORD})
    assert r.status_code == 200, r.text
    token = str(r.json()["token"])
    c.headers["X-Cornucopia-Session"] = token
    return token
