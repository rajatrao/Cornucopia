"""Inventory arithmetic. Pure functions over lots, all in base units."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from cornucopia.domain.units import Quantity, Unit, dimension_of


@dataclass(frozen=True)
class Lot:
    id: UUID
    ingredient_id: UUID
    quantity_base: Decimal
    base_unit: Unit
    status: str
    expires_at: datetime | None = None


@dataclass
class IngredientStock:
    ingredient_id: UUID
    base_unit: Unit
    available: Decimal = Decimal("0")
    pledged: Decimal = Decimal("0")
    expiring_before_cutoff: Decimal = Decimal("0")
    lots_available: int = 0
    lots_unusable: int = 0
    earliest_expiry: datetime | None = None
    lot_ids: list[UUID] = field(default_factory=list)

    def display(self, amount: Decimal) -> str:
        """Human-friendly rendering: pounds for mass, litres for big volumes."""
        q = Quantity(amount, self.base_unit)
        dim = dimension_of(self.base_unit)
        if dim == "mass":
            return f"{q.to(Unit.LB).amount.quantize(Decimal('0.1'))} lb"
        if dim == "volume" and amount >= 1000:
            return f"{q.to(Unit.L).amount.quantize(Decimal('0.1'))} l"
        return f"{amount.normalize():f} {self.base_unit.value}"


def summarize(
    lots: Iterable[Lot], *, now: datetime, cutoff: datetime | None = None
) -> dict[UUID, IngredientStock]:
    """Per-ingredient stock.

    * ``available`` counts lots with status ``available`` that have not
      expired by ``now``. An expiry date in the past makes a lot unusable even
      if nobody has reported it yet.
    * ``pledged`` counts donations promised but not received; planners may
      choose whether to rely on them.
    * Mixed base units for one ingredient indicate corrupted data and raise.
    """
    out: dict[UUID, IngredientStock] = {}
    for lot in lots:
        s = out.setdefault(lot.ingredient_id, IngredientStock(lot.ingredient_id, lot.base_unit))
        if s.base_unit != lot.base_unit:
            raise ValueError(f"ingredient {lot.ingredient_id} has lots in mixed base units")
        expired = lot.expires_at is not None and lot.expires_at <= now
        if lot.status == "available" and not expired and lot.quantity_base > 0:
            s.available += lot.quantity_base
            s.lots_available += 1
            s.lot_ids.append(lot.id)
            if cutoff is not None and lot.expires_at is not None and lot.expires_at <= cutoff:
                s.expiring_before_cutoff += lot.quantity_base
            if lot.expires_at and (s.earliest_expiry is None or lot.expires_at < s.earliest_expiry):
                s.earliest_expiry = lot.expires_at
        elif lot.status == "pledged":
            s.pledged += lot.quantity_base
        else:
            s.lots_unusable += 1
    return out
