"""Explicit, safe quantity units.

Rules:
* Every quantity carries a unit. Arithmetic uses ``Decimal`` (no float drift).
* Conversion inside a dimension (mass, volume, count, portion) is exact
  table lookup.
* Crossing dimensions needs ingredient-specific data: density (g/ml) for
  mass <-> volume, unit weight (g per each) for count <-> mass. Without it,
  conversion is refused, never guessed.
* Portions are produced by recipes, not converted from ingredients.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class Dimension(StrEnum):
    MASS = "mass"
    VOLUME = "volume"
    COUNT = "count"
    PORTION = "portion"


class Unit(StrEnum):
    G = "g"
    KG = "kg"
    OZ = "oz"
    LB = "lb"
    ML = "ml"
    L = "l"
    TSP = "tsp"
    TBSP = "tbsp"
    CUP = "cup"
    FL_OZ = "fl_oz"
    QT = "qt"
    GAL = "gal"
    EACH = "each"
    PORTION = "portion"


# factor to the dimension's base unit (g, ml, each, portion). US customary.
_TABLE: dict[Unit, tuple[Dimension, Decimal]] = {
    Unit.G: (Dimension.MASS, Decimal("1")),
    Unit.KG: (Dimension.MASS, Decimal("1000")),
    Unit.OZ: (Dimension.MASS, Decimal("28.349523125")),
    Unit.LB: (Dimension.MASS, Decimal("453.59237")),
    Unit.ML: (Dimension.VOLUME, Decimal("1")),
    Unit.L: (Dimension.VOLUME, Decimal("1000")),
    Unit.TSP: (Dimension.VOLUME, Decimal("4.92892159375")),
    Unit.TBSP: (Dimension.VOLUME, Decimal("14.78676478125")),
    Unit.CUP: (Dimension.VOLUME, Decimal("236.5882365")),
    Unit.FL_OZ: (Dimension.VOLUME, Decimal("29.5735295625")),
    Unit.QT: (Dimension.VOLUME, Decimal("946.352946")),
    Unit.GAL: (Dimension.VOLUME, Decimal("3785.411784")),
    Unit.EACH: (Dimension.COUNT, Decimal("1")),
    Unit.PORTION: (Dimension.PORTION, Decimal("1")),
}

BASE_UNIT: dict[Dimension, Unit] = {
    Dimension.MASS: Unit.G,
    Dimension.VOLUME: Unit.ML,
    Dimension.COUNT: Unit.EACH,
    Dimension.PORTION: Unit.PORTION,
}

# Base quantities are stored with 3 decimal places (milligram precision).
BASE_QUANT = Decimal("0.001")


class ConversionError(ValueError):
    """Raised when a conversion would require information we do not have."""


@dataclass(frozen=True)
class IngredientPhysics:
    """Ingredient-specific data that permits cross-dimension conversion."""

    density_g_per_ml: Decimal | None = None
    unit_weight_g: Decimal | None = None


def dimension_of(unit: Unit) -> Dimension:
    return _TABLE[unit][0]


@dataclass(frozen=True)
class Quantity:
    amount: Decimal
    unit: Unit

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            object.__setattr__(self, "amount", Decimal(str(self.amount)))
        if not self.amount.is_finite():
            raise ValueError("quantity must be finite")

    @property
    def dimension(self) -> Dimension:
        return dimension_of(self.unit)

    def to(self, target: Unit, physics: IngredientPhysics | None = None) -> Quantity:
        return Quantity(convert(self.amount, self.unit, target, physics), target)

    def to_base(self, base: Unit, physics: IngredientPhysics | None = None) -> Quantity:
        """Convert to an ingredient's base unit, rounded to storage precision."""
        q = self.to(base, physics)
        return Quantity(q.amount.quantize(BASE_QUANT), base)

    def __add__(self, other: Quantity) -> Quantity:
        if other.dimension != self.dimension:
            raise ConversionError(f"cannot add {other.dimension} to {self.dimension}")
        return Quantity(self.amount + other.to(self.unit).amount, self.unit)

    def __sub__(self, other: Quantity) -> Quantity:
        if other.dimension != self.dimension:
            raise ConversionError(f"cannot subtract {other.dimension} from {self.dimension}")
        return Quantity(self.amount - other.to(self.unit).amount, self.unit)

    def __str__(self) -> str:
        return f"{self.amount.normalize():f} {self.unit.value}"


def convert(
    amount: Decimal, source: Unit, target: Unit, physics: IngredientPhysics | None = None
) -> Decimal:
    s_dim, s_factor = _TABLE[source]
    t_dim, t_factor = _TABLE[target]
    base = amount * s_factor  # in source dimension's base unit
    if s_dim != t_dim:
        base = _cross(base, s_dim, t_dim, physics)
    return base / t_factor


def _cross(
    base: Decimal, src: Dimension, dst: Dimension, physics: IngredientPhysics | None
) -> Decimal:
    if Dimension.PORTION in (src, dst):
        raise ConversionError("portions come from recipe yields, not unit conversion")
    p = physics or IngredientPhysics()
    if {src, dst} == {Dimension.MASS, Dimension.VOLUME}:
        if p.density_g_per_ml is None or p.density_g_per_ml <= 0:
            raise ConversionError("mass/volume conversion needs the ingredient's density")
        return base * p.density_g_per_ml if src is Dimension.VOLUME else base / p.density_g_per_ml
    if {src, dst} == {Dimension.MASS, Dimension.COUNT}:
        if p.unit_weight_g is None or p.unit_weight_g <= 0:
            raise ConversionError("count/mass conversion needs the ingredient's unit weight")
        return base * p.unit_weight_g if src is Dimension.COUNT else base / p.unit_weight_g
    if {src, dst} == {Dimension.VOLUME, Dimension.COUNT}:
        grams = _cross(base, src, Dimension.MASS, p)
        return _cross(grams, Dimension.MASS, dst, p)
    raise ConversionError(f"no conversion from {src} to {dst}")  # pragma: no cover
