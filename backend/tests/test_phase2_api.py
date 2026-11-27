from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from cornucopia.api.app import create_app
from cornucopia.config import Settings
from cornucopia.domain.events import (
    DonationCreated,
    EventPayload,
    IngredientInfo,
    InventoryAdjusted,
    LotInfo,
    normalise,
)
from cornucopia.domain.inventory import Lot, summarize
from cornucopia.domain.units import ConversionError, Unit
from cornucopia.persistence.memory import InMemorySupabaseClient

EVENT = TypeAdapter(EventPayload)


# ------------------------------------------------------------ inventory math
def test_summary_counts_only_usable_stock() -> None:
    ing = uuid.uuid4()
    now = datetime(2026, 11, 26, 12, tzinfo=UTC)
    lots = [
        Lot(uuid.uuid4(), ing, D("1000"), Unit.G, "available", now + timedelta(days=3)),
        Lot(uuid.uuid4(), ing, D("500"), Unit.G, "available", now + timedelta(hours=10)),
        Lot(uuid.uuid4(), ing, D("700"), Unit.G, "available", now - timedelta(hours=1)),  # stale
        Lot(uuid.uuid4(), ing, D("300"), Unit.G, "pledged"),
        Lot(uuid.uuid4(), ing, D("0"), Unit.G, "cancelled"),
        Lot(uuid.uuid4(), ing, D("0"), Unit.G, "available"),  # empty
    ]
    s = summarize(lots, now=now, cutoff=now + timedelta(hours=48))[ing]
    assert s.available == D("1500") and s.pledged == D("300")
    assert s.expiring_before_cutoff == D("500") and s.lots_available == 2
    assert s.earliest_expiry == now + timedelta(hours=10)
    assert s.display(D("81646.627")) == "180.0 lb"


def test_summary_rejects_mixed_base_units() -> None:
    ing = uuid.uuid4()
    with pytest.raises(ValueError, match="mixed"):
        summarize(
            [
                Lot(uuid.uuid4(), ing, D("1"), Unit.G, "available"),
                Lot(uuid.uuid4(), ing, D("1"), Unit.EACH, "available"),
            ],
            now=datetime.now(UTC),
        )


# ----------------------------------------------------------- event payloads
def test_events_never_invent_missing_facts() -> None:
    with pytest.raises(ValidationError):
        EVENT.validate_python({"type": "DONATION_CANCELLED", "donation_id": str(uuid.uuid4())})
    with pytest.raises(ValidationError):  # quantity without unit
        EVENT.validate_python(
            {
                "type": "INGREDIENT_EXPIRED",
                "lot_id": str(uuid.uuid4()),
                "quantity": "2",
                "reason": "mould",
            }
        )
    with pytest.raises(ValidationError):  # a change that changes nothing
        EVENT.validate_python(
            {"type": "COMMITMENT_CHANGED", "commitment_id": str(uuid.uuid4()), "reason": "call"}
        )
    with pytest.raises(ValidationError):  # unknown fields refused
        EVENT.validate_python(
            {
                "type": "DELIVERY_CANCELLED",
                "delivery_id": str(uuid.uuid4()),
                "reason": "snow",
                "meals": 5,
            }
        )


def test_donation_normalises_to_base_units_and_keeps_report() -> None:
    rice = IngredientInfo(id=uuid.uuid4(), base_unit=Unit.G)
    ev = DonationCreated(
        description="Rice",
        received=True,
        lots=[{"ingredient_id": rice.id, "quantity": D("180"), "unit": "lb"}],
    )
    out = normalise(ev, ingredients={rice.id: rice})
    lot = out["lots"][0]  # type: ignore[index]
    assert lot["quantity"] == "180" and lot["unit"] == "lb"
    assert lot["quantity_base"] == "81646.627" and lot["base_unit"] == "g"


def test_volume_report_for_mass_ingredient_needs_density() -> None:
    oil = IngredientInfo(id=uuid.uuid4(), base_unit=Unit.G)
    ev = InventoryAdjusted(
        lot_id=uuid.uuid4(), direction="remove", quantity=D("2"), unit=Unit.CUP, reason="spilled"
    )
    with pytest.raises(ConversionError):
        normalise(ev, lot=LotInfo(id=ev.lot_id, ingredient=oil))
    oil2 = IngredientInfo(id=oil.id, base_unit=Unit.G, density_g_per_ml=D("0.92"))
    out = normalise(ev, lot=LotInfo(id=ev.lot_id, ingredient=oil2))
    assert out["delta_base"] == "-435.322"


# ----------------------------------------------------------------- API
@pytest.fixture
def client() -> TestClient:
    s = Settings(CORNUCOPIA_TRANSPORT="memory", _env_file=None)  # type: ignore[call-arg]
    return TestClient(create_app(s, client=InMemorySupabaseClient()))


def _post(c: TestClient, path: str, body: dict[str, Any], status: int = 201) -> Any:
    r = c.post(path, json=body, headers={"X-Cornucopia-Actor": "op:test"})
    assert r.status_code == status, r.text
    return r.json()


def test_crud_and_validation(client: TestClient) -> None:
    with client as c:
        rice = _post(
            c,
            "/api/v1/resources/ingredients",
            {"name": "Rice", "category": "grain", "base_unit": "g"},
        )
        assert c.get("/api/v1/resources/ingredients").json()[0]["name"] == "Rice"
        bad = c.post("/api/v1/resources/ingredients", json={"name": "X", "base_unit": "bushel"})
        assert bad.status_code == 422
        immut = c.patch(f"/api/v1/resources/ingredients/{rice['id']}", json={"base_unit": "ml"})
        assert immut.status_code == 422  # base unit is immutable
        upd = c.patch(
            f"/api/v1/resources/ingredients/{rice['id']}", json={"attributes": ["gluten"]}
        )
        assert upd.status_code == 200 and upd.json()["attributes"] == ["gluten"]
        recipe = _post(
            c,
            "/api/v1/resources/recipes",
            {"name": "Pilaf", "yield_portions": "50", "prep_minutes": 45},
        )
        ri = _post(
            c,
            "/api/v1/resources/recipe-ingredients",
            {
                "recipe_id": recipe["id"],
                "ingredient_id": rice["id"],
                "quantity": "10",
                "unit": "lb",
            },
        )
        assert D(str(ri["quantity_base"])) == D("4535.924")
        cup = c.post(
            "/api/v1/resources/recipe-ingredients",
            json={
                "recipe_id": recipe["id"],
                "ingredient_id": rice["id"],
                "quantity": "2",
                "unit": "cup",
            },
        )
        assert cup.status_code == 422 and "density" in cup.text
        assert c.delete(f"/api/v1/resources/recipe-ingredients/{ri['id']}").status_code == 204
        assert c.get("/api/v1/resources/nope").status_code == 404


def test_event_flow_is_idempotent_and_updates_inventory(client: TestClient) -> None:
    with client as c:
        rice = _post(
            c,
            "/api/v1/resources/ingredients",
            {"name": "Rice", "category": "grain", "base_unit": "g"},
        )
        body = {
            "idempotency_key": "donation-rice-0001",
            "event": {
                "type": "DONATION_CREATED",
                "description": "Rice from co-op",
                "received": True,
                "lots": [{"ingredient_id": rice["id"], "quantity": "180", "unit": "lb"}],
            },
        }
        first = _post(c, "/api/v1/events", body, 201)
        second = _post(c, "/api/v1/events", body, 200)
        assert first["duplicate"] is False and second["duplicate"] is True
        assert first["event"]["id"] == second["event"]["id"]
        assert len(c.get("/api/v1/inventory/lots").json()) == 1
        stock = c.get("/api/v1/inventory/summary").json()[0]
        assert stock["available_display"] == "180.0 lb"
        lot = c.get("/api/v1/inventory/lots").json()[0]
        _post(
            c,
            "/api/v1/events",
            {
                "idempotency_key": "adjust-rice-0001",
                "event": {
                    "type": "INVENTORY_ADJUSTED",
                    "lot_id": lot["id"],
                    "direction": "remove",
                    "quantity": "30",
                    "unit": "lb",
                    "reason": "stocktake",
                },
            },
        )
        stock = c.get("/api/v1/inventory/summary").json()[0]
        assert stock["available_display"] == "150.0 lb"
        events = c.get("/api/v1/events").json()
        assert [e["event_type"] for e in events][:2] == ["INVENTORY_ADJUSTED", "DONATION_CREATED"]
        assert events[0]["actor"] == "op:test"
        assert c.get("/api/v1/organization").json()["state_version"] >= 3


def test_event_for_unknown_ingredient_is_rejected(client: TestClient) -> None:
    with client as c:
        r = c.post(
            "/api/v1/events",
            json={
                "idempotency_key": "donation-x-0001",
                "event": {
                    "type": "DONATION_CREATED",
                    "description": "Mystery",
                    "received": True,
                    "lots": [{"ingredient_id": str(uuid.uuid4()), "quantity": "1", "unit": "kg"}],
                },
            },
        )
        assert r.status_code == 422
        assert c.get("/api/v1/events").json() == []


def test_invalid_actor_rejected(client: TestClient) -> None:
    with client as c:
        r = c.get("/api/v1/organization")
        assert r.status_code == 200
        r = c.post(
            "/api/v1/resources/donors",
            json={"name": "A"},
            headers={"X-Cornucopia-Actor": "<script>"},
        )
        assert r.status_code == 422
