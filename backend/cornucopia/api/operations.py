"""Phase 2 HTTP surface: resources, inventory, operational events, audit."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cornucopia.auth import OperatorIdentity, decode_session
from cornucopia.domain.events import (
    DonationCreated,
    EventPayload,
    IngredientExpired,
    IngredientInfo,
    InventoryAdjusted,
    LotInfo,
    normalise,
    to_base,
)
from cornucopia.domain.inventory import Lot, summarize
from cornucopia.domain.resources import (
    RESOURCES,
    DonationOut,
    LotOut,
    ResourceSpec,
)
from cornucopia.domain.units import ConversionError, Unit
from cornucopia.persistence.client import SupabaseError
from cornucopia.persistence.repositories.operations import (
    OperationsRepository,
    Organization,
    new_correlation_id,
)

# custom SQLSTATEs raised by our RPCs, plus the Postgres ones we expect
_SQLSTATE_HTTP = {
    "P0403": 403,
    "P0404": 404,
    "P0409": 409,
    "P0422": 422,
    "23505": 409,
    "23503": 409,
    "23514": 422,
    "22P02": 422,
    "42501": 403,
}


def db_error(exc: SupabaseError) -> HTTPException:
    body = exc.body if isinstance(exc.body, dict) else {}
    code = str(body.get("code", ""))
    http = _SQLSTATE_HTTP.get(code)
    if http is None:
        return HTTPException(502, "database request failed")
    return HTTPException(
        http, {"code": code, "message": body.get("message"), "details": body.get("details")}
    )


def ops_repo(request: Request) -> OperationsRepository:
    repo: OperationsRepository = request.app.state.ops_repo
    return repo


def organization(request: Request) -> Organization:
    org: Organization = request.app.state.organization
    return org


_OP_CACHE: dict[tuple[str, str], tuple[float, OperatorIdentity | None]] = {}
_OP_CACHE_TTL_S = 30.0


def current_operator(
    request: Request,
    x_cornucopia_session: Annotated[str | None, Header()] = None,
) -> OperatorIdentity:
    """The signed-in operator. The frontend server forwards the session token
    from its HttpOnly cookie; the API verifies signature, expiry and org, and
    that the operator is still active (cached for 30 s to spare round trips)."""
    if not x_cornucopia_session:
        raise HTTPException(401, "sign in required")
    settings = request.app.state.settings
    org: Organization = request.app.state.organization
    try:
        op_id = decode_session(
            x_cornucopia_session, settings.session_secret.get_secret_value(), org.id
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "session invalid or expired") from exc
    key = (str(org.id), str(op_id))
    hit = _OP_CACHE.get(key)
    if hit and time.monotonic() - hit[0] < _OP_CACHE_TTL_S:
        ident = hit[1]
    else:
        repo: OperationsRepository = request.app.state.ops_repo
        row = repo.get("operators", org.id, op_id)
        ident = (
            OperatorIdentity.model_validate(row) if row is not None and row.get("active") else None
        )
        _OP_CACHE[key] = (time.monotonic(), ident)
    if ident is None:
        raise HTTPException(401, "operator inactive or unknown")
    return ident


def require_role(role: str) -> Any:
    def dep(op: Annotated[OperatorIdentity, Depends(current_operator)]) -> OperatorIdentity:
        if not op.at_least(role):  # type: ignore[arg-type]
            raise HTTPException(403, f"requires the {role} role")
        return op

    return dep


def actor(op: Annotated[OperatorIdentity, Depends(require_role("operator"))]) -> str:
    """Who is acting: always the authenticated operator, never a client claim."""
    return op.actor


Repo = Annotated[OperationsRepository, Depends(ops_repo)]
Org = Annotated[Organization, Depends(organization)]
Actor = Annotated[str, Depends(actor)]
Viewer = Annotated[OperatorIdentity, Depends(current_operator)]
Approver = Annotated[OperatorIdentity, Depends(require_role("approver"))]


class OrgOut(BaseModel):
    id: UUID
    slug: str
    name: str
    state_version: int


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: Annotated[
        str, Field(min_length=8, max_length=200, pattern=r"^[A-Za-z0-9._:-]+$")
    ]
    correlation_id: UUID | None = None
    event: EventPayload


class EventOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: UUID
    idempotency_key: str
    event_type: str
    payload: dict[str, Any]
    actor: str
    correlation_id: UUID
    effect: dict[str, Any]
    state_version: int
    processing_status: str
    processing_note: str | None = None
    processed_at: datetime | None = None
    created_at: datetime


class IngestOut(BaseModel):
    duplicate: bool
    event: EventOut


class StockOut(BaseModel):
    ingredient_id: UUID
    ingredient_name: str
    base_unit: Unit
    available_base: Decimal
    pledged_base: Decimal
    expiring_within_48h_base: Decimal
    available_display: str
    lots_available: int
    lots_unusable: int
    earliest_expiry: datetime | None


class AuditOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    table_name: str
    record_id: str
    action: str
    actor: str
    event_id: UUID | None = None
    at: datetime


def _spec(kind: str) -> ResourceSpec:
    spec = RESOURCES.get(kind)
    if spec is None:
        raise HTTPException(404, f"unknown resource {kind}")
    return spec


def _ingredient(repo: OperationsRepository, org: UUID, ingredient_id: UUID) -> IngredientInfo:
    row = repo.get("ingredients", org, ingredient_id)
    if row is None:
        raise HTTPException(422, f"ingredient {ingredient_id} not found")
    return IngredientInfo.model_validate(row)


def _prepare(
    repo: OperationsRepository,
    org: UUID,
    table: str,
    values: dict[str, Any],
    current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Cross-record validation and derived fields before a write."""
    if table == "recipe_ingredients":
        merged = {**(current or {}), **values}
        if {"quantity", "unit"} & values.keys() or current is None:
            ing = _ingredient(repo, org, UUID(str(merged["ingredient_id"])))
            try:
                values["quantity_base"] = str(
                    to_base(Decimal(str(merged["quantity"])), Unit(merged["unit"]), ing)
                )
            except (ConversionError, ValueError) as exc:
                raise HTTPException(422, str(exc)) from exc
        if current is None and repo.get("recipes", org, UUID(str(values["recipe_id"]))) is None:
            raise HTTPException(422, "recipe not found")
    if table == "ingredient_substitutions" and current is None:
        for col in ("ingredient_id", "substitute_id"):
            _ingredient(repo, org, UUID(str(values[col])))
    if table == "commitments" and current is None:
        if repo.get("meals", org, UUID(str(values["meal_id"]))) is None:
            raise HTTPException(422, "meal not found")
    if table in ("commitments",) and values.get("delivery_id"):
        if repo.get("deliveries", org, UUID(str(values["delivery_id"]))) is None:
            raise HTTPException(422, "delivery not found")
    if table == "meal_components" and current is None:
        if repo.get("meals", org, UUID(str(values["meal_id"]))) is None:
            raise HTTPException(422, "meal not found")
        if repo.get("recipes", org, UUID(str(values["recipe_id"]))) is None:
            raise HTTPException(422, "recipe not found")
    return values


def build_router() -> APIRouter:
    r = APIRouter(prefix="/api/v1", tags=["operations"])

    @r.get("/organization", response_model=OrgOut)
    def get_org(repo: Repo, org: Org) -> OrgOut:
        return OrgOut(**org.model_dump(), state_version=repo.state_version(org.id))

    # ------------------------------------------------------------ resources
    @r.get("/resources/{kind}")
    def list_resources(kind: str, repo: Repo, org: Org) -> list[dict[str, Any]]:
        spec = _spec(kind)
        rows = repo.list(spec.table, org.id, order=spec.order)
        return [spec.out.model_validate(x).model_dump(mode="json") for x in rows]

    @r.post("/resources/{kind}", status_code=201)
    async def create_resource(
        kind: str, request: Request, repo: Repo, org: Org, who: Actor
    ) -> dict[str, Any]:
        spec = _spec(kind)
        try:
            body = spec.create.model_validate_json(await request.body())
        except ValidationError as exc:
            raise HTTPException(422, exc.errors(include_url=False, include_context=False)) from exc
        values = body.model_dump(mode="json", exclude_none=True)
        values = _prepare(repo, org.id, spec.table, values)
        try:
            row = repo.write(org.id, who, spec.table, "insert", None, values)
        except SupabaseError as exc:
            raise db_error(exc) from exc
        return spec.out.model_validate(row).model_dump(mode="json")

    @r.patch("/resources/{kind}/{row_id}")
    async def update_resource(
        kind: str, row_id: UUID, request: Request, repo: Repo, org: Org, who: Actor
    ) -> dict[str, Any]:
        spec = _spec(kind)
        try:
            body = spec.update.model_validate_json(await request.body())
        except ValidationError as exc:
            raise HTTPException(422, exc.errors(include_url=False, include_context=False)) from exc
        values = body.model_dump(mode="json", exclude_unset=True)
        if not values:
            raise HTTPException(422, "nothing to update")
        current = repo.get(spec.table, org.id, row_id)
        if current is None:
            raise HTTPException(404, f"{kind} {row_id} not found")
        values = _prepare(repo, org.id, spec.table, values, current)
        try:
            row = repo.write(org.id, who, spec.table, "update", row_id, values)
        except SupabaseError as exc:
            raise db_error(exc) from exc
        return spec.out.model_validate(row).model_dump(mode="json")

    @r.delete("/resources/{kind}/{row_id}", status_code=204)
    def delete_resource(kind: str, row_id: UUID, repo: Repo, org: Org, who: Actor) -> Response:
        spec = _spec(kind)
        try:
            repo.write(org.id, who, spec.table, "delete", row_id, {})
        except SupabaseError as exc:
            raise db_error(exc) from exc
        return Response(status_code=204)

    # ------------------------------------------------------------ inventory
    @r.get("/inventory/donations", response_model=list[DonationOut])
    def donations(repo: Repo, org: Org) -> list[DonationOut]:
        rows = repo.list("donations", org.id, order="created_at.desc")
        return [DonationOut.model_validate(x) for x in rows]

    @r.get("/inventory/lots", response_model=list[LotOut])
    def lots(repo: Repo, org: Org) -> list[LotOut]:
        rows = repo.list("inventory_lots", org.id, order="created_at.desc")
        return [LotOut.model_validate(x) for x in rows]

    @r.get("/inventory/summary", response_model=list[StockOut])
    def summary(repo: Repo, org: Org) -> list[StockOut]:
        ingredients = {UUID(str(i["id"])): i for i in repo.list("ingredients", org.id)}
        lots = [
            Lot(
                id=UUID(str(x["id"])),
                ingredient_id=UUID(str(x["ingredient_id"])),
                quantity_base=Decimal(str(x["quantity_base"])),
                base_unit=Unit(x["base_unit"]),
                status=str(x["status"]),
                expires_at=datetime.fromisoformat(str(x["expires_at"]))
                if x.get("expires_at")
                else None,
            )
            for x in repo.list("inventory_lots", org.id)
        ]
        now = datetime.now(UTC)
        stock = summarize(lots, now=now, cutoff=now + timedelta(hours=48))
        out = []
        for ing_id, ing in ingredients.items():
            s = stock.get(ing_id)
            base = Unit(ing["base_unit"])
            out.append(
                StockOut(
                    ingredient_id=ing_id,
                    ingredient_name=str(ing["name"]),
                    base_unit=base,
                    available_base=s.available if s else Decimal(0),
                    pledged_base=s.pledged if s else Decimal(0),
                    expiring_within_48h_base=s.expiring_before_cutoff if s else Decimal(0),
                    available_display=s.display(s.available) if s else "0",
                    lots_available=s.lots_available if s else 0,
                    lots_unusable=s.lots_unusable if s else 0,
                    earliest_expiry=s.earliest_expiry if s else None,
                )
            )
        return sorted(out, key=lambda x: x.ingredient_name.lower())

    # --------------------------------------------------------------- events
    @r.post("/events", response_model=IngestOut, status_code=201)
    def submit_event(
        body: EventIn, response: Response, repo: Repo, org: Org, who: Actor
    ) -> IngestOut:
        ev = body.event
        try:
            if isinstance(ev, DonationCreated):
                ings = {
                    i: _ingredient(repo, org.id, i) for i in {lot.ingredient_id for lot in ev.lots}
                }
                payload = normalise(ev, ingredients=ings)
            elif isinstance(ev, InventoryAdjusted | IngredientExpired):
                lot_row = repo.get("inventory_lots", org.id, ev.lot_id)
                if lot_row is None:
                    raise HTTPException(404, f"inventory lot {ev.lot_id} not found")
                ing = _ingredient(repo, org.id, UUID(str(lot_row["ingredient_id"])))
                payload = normalise(ev, lot=LotInfo(id=ev.lot_id, ingredient=ing))
            else:
                payload = normalise(ev)
        except (ConversionError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        try:
            result = repo.ingest_event(
                org.id,
                body.idempotency_key,
                ev.type.value,
                payload,
                who,
                body.correlation_id or new_correlation_id(),
            )
        except SupabaseError as exc:
            raise db_error(exc) from exc
        if result.duplicate:
            response.status_code = status.HTTP_200_OK
        return IngestOut(duplicate=result.duplicate, event=EventOut.model_validate(result.event))

    @r.get("/events", response_model=list[EventOut])
    def list_events(repo: Repo, org: Org, limit: int = 100) -> list[EventOut]:
        rows = repo.list(
            "operational_events", org.id, order="created_at.desc", limit=max(1, min(limit, 500))
        )
        return [EventOut.model_validate(x) for x in rows]

    @r.get("/events/{event_id}", response_model=EventOut)
    def get_event(event_id: UUID, repo: Repo, org: Org) -> EventOut:
        row = repo.get("operational_events", org.id, event_id)
        if row is None:
            raise HTTPException(404, "event not found")
        return EventOut.model_validate(row)

    @r.get("/audit", response_model=list[AuditOut])
    def audit(repo: Repo, org: Org, limit: int = 100) -> list[AuditOut]:
        rows = repo.list("audit_records", org.id, order="id.desc", limit=max(1, min(limit, 500)))
        return [AuditOut.model_validate(x) for x in rows]

    return r
