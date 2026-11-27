from decimal import Decimal as D

import pytest

from cornucopia.domain.units import (
    ConversionError,
    IngredientPhysics,
    Quantity,
    Unit,
    convert,
)


@pytest.mark.parametrize(
    ("amount", "src", "dst", "expected"),
    [
        ("1", Unit.LB, Unit.G, "453.59237"),
        ("16", Unit.OZ, Unit.LB, "1"),
        ("1", Unit.KG, Unit.LB, "2.204622621848775806745979"),
        ("180", Unit.LB, Unit.KG, "81.6466266"),
        ("1000", Unit.G, Unit.KG, "1"),
        ("1", Unit.GAL, Unit.QT, "4"),
        ("3", Unit.TSP, Unit.TBSP, "1"),
        ("1", Unit.CUP, Unit.FL_OZ, "8"),
        ("12", Unit.EACH, Unit.EACH, "12"),
        ("500", Unit.PORTION, Unit.PORTION, "500"),
    ],
)
def test_same_dimension(amount: str, src: Unit, dst: Unit, expected: str) -> None:
    got = convert(D(amount), src, dst)
    assert abs(got - D(expected)) < D("1e-18")


def test_round_trip_is_stable() -> None:
    for unit in (Unit.LB, Unit.OZ, Unit.KG, Unit.CUP, Unit.GAL):
        q = Quantity(D("123.456"), unit)
        back = q.to(Unit.G if q.dimension == "mass" else Unit.ML).to(unit)
        assert abs(back.amount - q.amount) < D("1e-20")


def test_mass_volume_refused_without_density() -> None:
    with pytest.raises(ConversionError, match="density"):
        Quantity(D("1"), Unit.CUP).to(Unit.G)
    with pytest.raises(ConversionError, match="density"):
        Quantity(D("1"), Unit.LB).to(Unit.ML)


def test_mass_volume_with_density() -> None:
    rice = IngredientPhysics(density_g_per_ml=D("0.85"))
    assert Quantity(D("100"), Unit.ML).to(Unit.G, rice).amount == D("85.00")
    assert Quantity(D("85"), Unit.G).to(Unit.ML, rice).amount == D("100")


def test_count_mass_requires_unit_weight() -> None:
    with pytest.raises(ConversionError, match="unit weight"):
        Quantity(D("10"), Unit.EACH).to(Unit.G)
    potato = IngredientPhysics(unit_weight_g=D("213"))
    assert Quantity(D("10"), Unit.EACH).to(Unit.G, potato).amount == D("2130")
    assert Quantity(D("1"), Unit.LB).to(Unit.EACH, potato).amount.quantize(D("0.001")) == D("2.130")


def test_volume_count_goes_through_mass_and_needs_both() -> None:
    with pytest.raises(ConversionError):
        Quantity(D("1"), Unit.CUP).to(Unit.EACH, IngredientPhysics(density_g_per_ml=D("1")))
    p = IngredientPhysics(density_g_per_ml=D("1"), unit_weight_g=D("50"))
    assert Quantity(D("100"), Unit.ML).to(Unit.EACH, p).amount == D("2")


def test_portions_never_convert() -> None:
    with pytest.raises(ConversionError, match="recipe"):
        Quantity(D("1"), Unit.PORTION).to(Unit.G, IngredientPhysics(D("1"), D("1")))


def test_to_base_rounds_to_storage_precision() -> None:
    q = Quantity(D("1"), Unit.OZ).to_base(Unit.G)
    assert q.amount == D("28.350") and q.unit is Unit.G


def test_arithmetic_respects_dimensions() -> None:
    total = Quantity(D("1"), Unit.LB) + Quantity(D("8"), Unit.OZ)
    assert total.unit is Unit.LB and total.amount == D("1.5")
    left = Quantity(D("1"), Unit.KG) - Quantity(D("250"), Unit.G)
    assert left.amount == D("0.75")
    with pytest.raises(ConversionError):
        _ = Quantity(D("1"), Unit.LB) + Quantity(D("1"), Unit.CUP)


def test_rejects_non_finite() -> None:
    with pytest.raises(ValueError, match="finite"):
        Quantity(D("NaN"), Unit.G)
