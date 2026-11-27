"""Operational events: typed payloads and deterministic normalisation.

An operator reports a fact ("the rice donation was cancelled"). The API
validates the payload against the model for its type, refuses anything
missing or ambiguous (no defaults are invented for facts), converts every
quantity to the ingredient's base unit, and hands the normalised payload to
the ``ingest_event`` RPC, which applies it atomically and idempotently.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cornucopia.domain.units import IngredientPhysics, Quantity, Unit, dimension_of

Reason = Annotated[str, Field(min_length=3, max_length=500)]
PositiveAmount = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)]


class EventType(StrEnum):
    DONATION_CREATED = "DONATION_CREATED"
    DONATION_CANCELLED = "DONATION_CANCELLED"
    INVENTORY_ADJUSTED = "INVENTORY_ADJUSTED"
    INGREDIENT_EXPIRED = "INGREDIENT_EXPIRED"
    VOLUNTEER_UNAVAILABLE = "VOLUNTEER_UNAVAILABLE"
    DELIVERY_DELAYED = "DELIVERY_DELAYED"
    DELIVERY_CANCELLED = "DELIVERY_CANCELLED"
    COMMITMENT_CHANGED = "COMMITMENT_CHANGED"
    PREPARATION_CAPACITY_CHANGED = "PREPARATION_CAPACITY_CHANGED"


class Diet(StrEnum):
    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"
    GLUTEN_FREE = "gluten_free"
    NUT_FREE = "nut_free"
    DAIRY_FREE = "dairy_free"
    HALAL = "halal"


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DonationLotIn(_Payload):
    ingredient_id: UUID
    quantity: PositiveAmount
    unit: Unit
    expires_at: datetime | None = None


class DonationCreated(_Payload):
    type: Literal[EventType.DONATION_CREATED] = EventType.DONATION_CREATED
    donor_id: UUID | None = None
    description: Annotated[str, Field(min_length=3, max_length=300)]
    received: bool
    expected_at: datetime | None = None
    lots: Annotated[list[DonationLotIn], Field(min_length=1, max_length=50)]

    @model_validator(mode="after")
    def _distinct(self) -> DonationCreated:
        ids = [lot.ingredient_id for lot in self.lots]
        if len(ids) != len(set(ids)):
            raise ValueError("each ingredient may appear once per donation")
        return self


class DonationCancelled(_Payload):
    type: Literal[EventType.DONATION_CANCELLED] = EventType.DONATION_CANCELLED
    donation_id: UUID
    reason: Reason


class InventoryAdjusted(_Payload):
    type: Literal[EventType.INVENTORY_ADJUSTED] = EventType.INVENTORY_ADJUSTED
    lot_id: UUID
    direction: Literal["add", "remove"]
    quantity: PositiveAmount
    unit: Unit
    reason: Reason


class IngredientExpired(_Payload):
    type: Literal[EventType.INGREDIENT_EXPIRED] = EventType.INGREDIENT_EXPIRED
    lot_id: UUID
    # omit both to expire the whole lot; give both for a partial expiry
    quantity: PositiveAmount | None = None
    unit: Unit | None = None
    reason: Reason

    @model_validator(mode="after")
    def _pair(self) -> IngredientExpired:
        if (self.quantity is None) != (self.unit is None):
            raise ValueError("quantity and unit must be given together")
        return self


class VolunteerUnavailable(_Payload):
    type: Literal[EventType.VOLUNTEER_UNAVAILABLE] = EventType.VOLUNTEER_UNAVAILABLE
    volunteer_id: UUID
    reason: Reason


class DeliveryDelayed(_Payload):
    type: Literal[EventType.DELIVERY_DELAYED] = EventType.DELIVERY_DELAYED
    delivery_id: UUID
    delay_minutes: Annotated[int, Field(gt=0, le=24 * 60)]
    reason: Reason


class DeliveryCancelled(_Payload):
    type: Literal[EventType.DELIVERY_CANCELLED] = EventType.DELIVERY_CANCELLED
    delivery_id: UUID
    reason: Reason


class CommitmentChanged(_Payload):
    type: Literal[EventType.COMMITMENT_CHANGED] = EventType.COMMITMENT_CHANGED
    commitment_id: UUID
    meals_count: Annotated[int, Field(gt=0, le=100_000)] | None = None
    diet_requirements: list[Diet] | None = None
    due_at: datetime | None = None
    status: Literal["cancelled", "fulfilled"] | None = None
    reason: Reason

    @model_validator(mode="after")
    def _something_changes(self) -> CommitmentChanged:
        fields = (self.meals_count, self.diet_requirements, self.due_at, self.status)
        if all(v is None for v in fields):
            raise ValueError("a commitment change must change at least one field")
        return self


class PreparationCapacityChanged(_Payload):
    type: Literal[EventType.PREPARATION_CAPACITY_CHANGED] = EventType.PREPARATION_CAPACITY_CHANGED
    team_id: UUID
    capacity_portions_per_hour: (
        Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)] | None
    ) = None
    available_hours: (
        Annotated[Decimal, Field(ge=0, le=24, max_digits=6, decimal_places=2)] | None
    ) = None
    active: bool | None = None
    reason: Reason

    @model_validator(mode="after")
    def _something_changes(self) -> PreparationCapacityChanged:
        if (self.capacity_portions_per_hour, self.available_hours, self.active) == (None,) * 3:
            raise ValueError("a capacity change must change at least one field")
        return self


EventPayload = Annotated[
    DonationCreated
    | DonationCancelled
    | InventoryAdjusted
    | IngredientExpired
    | VolunteerUnavailable
    | DeliveryDelayed
    | DeliveryCancelled
    | CommitmentChanged
    | PreparationCapacityChanged,
    Field(discriminator="type"),
]


class IngredientInfo(BaseModel):
    """What normalisation needs to know about an ingredient."""

    id: UUID
    base_unit: Unit
    density_g_per_ml: Decimal | None = None
    unit_weight_g: Decimal | None = None

    @property
    def physics(self) -> IngredientPhysics:
        return IngredientPhysics(self.density_g_per_ml, self.unit_weight_g)


class LotInfo(BaseModel):
    id: UUID
    ingredient: IngredientInfo


def to_base(amount: Decimal, unit: Unit, ing: IngredientInfo) -> Decimal:
    """Convert to the ingredient's base unit; raises ConversionError if unsafe."""
    base = Quantity(amount, unit).to_base(ing.base_unit, ing.physics).amount
    if base <= 0:
        raise ValueError(f"{amount} {unit} rounds to zero {ing.base_unit}")
    return base


def _s(v: Decimal) -> str:
    return format(v.normalize(), "f")


def normalise(
    event: EventPayload,
    *,
    ingredients: dict[UUID, IngredientInfo] | None = None,
    lot: LotInfo | None = None,
) -> dict[str, object]:
    """Produce the JSON payload stored in the journal and applied by the RPC.

    The operator's original quantity and unit are kept next to the base
    quantity so the journal shows exactly what was reported.
    """
    data = event.model_dump(mode="json", exclude_none=True, exclude={"type"})
    match event:
        case DonationCreated():
            assert ingredients is not None
            lots = []
            for item in event.lots:
                ing = ingredients[item.ingredient_id]
                lots.append(
                    {
                        **item.model_dump(mode="json", exclude_none=True),
                        "quantity": _s(item.quantity),
                        "quantity_base": _s(to_base(item.quantity, item.unit, ing)),
                        "base_unit": ing.base_unit.value,
                    }
                )
            data["lots"] = lots
        case InventoryAdjusted():
            assert lot is not None
            base = to_base(event.quantity, event.unit, lot.ingredient)
            data["quantity"] = _s(event.quantity)
            data["delta_base"] = _s(base if event.direction == "add" else -base)
            data["base_unit"] = lot.ingredient.base_unit.value
        case IngredientExpired() if event.quantity is not None and event.unit is not None:
            assert lot is not None
            data["quantity"] = _s(event.quantity)
            data["quantity_base"] = _s(to_base(event.quantity, event.unit, lot.ingredient))
        case _:
            pass
    return data


def needs_conversion_unit_check(unit: Unit, ing: IngredientInfo) -> bool:
    """True when converting ``unit`` to the ingredient base crosses dimensions."""
    return dimension_of(unit) != dimension_of(ing.base_unit)
