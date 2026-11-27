"""Dietary rules: each diet forbids a fixed set of ingredient attributes."""

from __future__ import annotations

from collections.abc import Iterable

FORBIDDEN: dict[str, frozenset[str]] = {
    "vegetarian": frozenset({"meat", "pork", "poultry", "fish", "shellfish"}),
    "vegan": frozenset(
        {"meat", "pork", "poultry", "fish", "shellfish", "dairy", "egg", "animal_product"}
    ),
    "gluten_free": frozenset({"gluten"}),
    "nut_free": frozenset({"nuts", "peanuts"}),
    "dairy_free": frozenset({"dairy"}),
    "halal": frozenset({"pork", "alcohol"}),
}


def forbidden_for(diets: Iterable[str]) -> frozenset[str]:
    out: set[str] = set()
    for d in diets:
        if d not in FORBIDDEN:
            raise ValueError(f"unknown diet {d!r}")
        out |= FORBIDDEN[d]
    return frozenset(out)


def violations(attributes: Iterable[str], diets: Iterable[str]) -> list[str]:
    """Return the attributes that break any of the diets (sorted)."""
    return sorted(set(attributes) & forbidden_for(diets))
