"""Typed contracts for resource management (operator-maintained master data).

Inventory lots and donations are not here: they change only through
operational events, so the journal is the single source of their history.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from cornucopia.domain.events import Diet
from cornucopia.domain.units import Unit

Name = Annotated[str, Field(min_length=1, max_length=120)]
Money = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]


class Attribute(StrEnum):
    MEAT = "meat"
    PORK = "pork"
    POULTRY = "poultry"
    FISH = "fish"
    SHELLFISH = "shellfish"
    DAIRY = "dairy"
    EGG = "egg"
    GLUTEN = "gluten"
    NUTS = "nuts"
    PEANUTS = "peanuts"
    SOY = "soy"
    SESAME = "sesame"
    ALCOHOL = "alcohol"
    ANIMAL_PRODUCT = "animal_product"


BaseUnit = Literal[Unit.G, Unit.ML, Unit.EACH]
Category = Literal[
    "grain",
    "vegetable",
    "fruit",
    "protein",
    "dairy",
    "fat",
    "seasoning",
    "sauce",
    "bakery",
    "other",
]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Out(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: UUID
    created_at: datetime


# ---------------------------------------------------------------- donors
class DonorCreate(_In):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    kind: Literal["individual", "business", "farm", "organization"] = "individual"
    contact: Annotated[str, Field(max_length=300)] | None = None


class DonorUpdate(_In):
    name: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    kind: Literal["individual", "business", "farm", "organization"] | None = None
    contact: Annotated[str, Field(max_length=300)] | None = None


class DonorOut(_Out):
    name: str
    kind: str
    contact: str | None = None


# ------------------------------------------------------------ ingredients
class IngredientCreate(_In):
    name: Name
    category: Category = "other"
    base_unit: BaseUnit
    density_g_per_ml: Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=4)] | None = None
    unit_weight_g: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=3)] | None = None
    attributes: list[Attribute] = Field(default_factory=list)
    perishable_days: Annotated[int, Field(gt=0, le=3650)] | None = None


class IngredientUpdate(_In):
    """base_unit is immutable: lots and recipes are stored in it."""

    name: Name | None = None
    category: Category | None = None
    density_g_per_ml: Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=4)] | None = None
    unit_weight_g: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=3)] | None = None
    attributes: list[Attribute] | None = None
    perishable_days: Annotated[int, Field(gt=0, le=3650)] | None = None


class IngredientOut(_Out):
    name: str
    category: str
    base_unit: Unit
    density_g_per_ml: Decimal | None = None
    unit_weight_g: Decimal | None = None
    attributes: list[str]
    perishable_days: int | None = None


# ---------------------------------------------------------------- recipes
class RecipeCreate(_In):
    name: Name
    yield_portions: Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]
    prep_minutes: Annotated[int, Field(ge=0, le=24 * 60)]
    instructions: Annotated[str, Field(max_length=5000)] | None = None


class RecipeUpdate(_In):
    name: Name | None = None
    yield_portions: Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)] | None = None
    prep_minutes: Annotated[int, Field(ge=0, le=24 * 60)] | None = None
    instructions: Annotated[str, Field(max_length=5000)] | None = None


class RecipeOut(_Out):
    name: str
    yield_portions: Decimal
    prep_minutes: int
    instructions: str | None = None


class RecipeIngredientCreate(_In):
    recipe_id: UUID
    ingredient_id: UUID
    quantity: Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)]
    unit: Unit
    optional: bool = False


class RecipeIngredientUpdate(_In):
    quantity: Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)] | None = None
    unit: Unit | None = None
    optional: bool | None = None


class RecipeIngredientOut(_Out):
    recipe_id: UUID
    ingredient_id: UUID
    quantity: Decimal
    unit: Unit
    quantity_base: Decimal
    optional: bool


# ----------------------------------------------------------- substitutions
class SubstitutionCreate(_In):
    ingredient_id: UUID
    substitute_id: UUID
    ratio: Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=4)] = Field(
        description="substitute base units needed per 1 base unit of the original"
    )
    recipe_id: UUID | None = None
    notes: Annotated[str, Field(max_length=300)] | None = None


class SubstitutionUpdate(_In):
    ratio: Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=4)] | None = None
    notes: Annotated[str, Field(max_length=300)] | None = None


class SubstitutionOut(_Out):
    ingredient_id: UUID
    substitute_id: UUID
    ratio: Decimal
    recipe_id: UUID | None = None
    notes: str | None = None


# ------------------------------------------------------------------ meals
class MealCreate(_In):
    name: Name
    description: Annotated[str, Field(max_length=500)] | None = None


class MealUpdate(_In):
    name: Name | None = None
    description: Annotated[str, Field(max_length=500)] | None = None


class MealOut(_Out):
    name: str
    description: str | None = None


class MealComponentCreate(_In):
    meal_id: UUID
    recipe_id: UUID
    portions: Annotated[Decimal, Field(gt=0, max_digits=6, decimal_places=2)] = Decimal("1")


class MealComponentUpdate(_In):
    portions: Annotated[Decimal, Field(gt=0, max_digits=6, decimal_places=2)] | None = None


class MealComponentOut(_Out):
    meal_id: UUID
    recipe_id: UUID
    portions: Decimal


# ------------------------------------------------------------ preparation
class TeamCreate(_In):
    name: Name
    capacity_portions_per_hour: Money
    available_hours: Annotated[Decimal, Field(ge=0, le=24, max_digits=6, decimal_places=2)]
    active: bool = True


class TeamUpdate(_In):
    """Capacity changes are operational events (PREPARATION_CAPACITY_CHANGED)."""

    name: Name | None = None


class TeamOut(_Out):
    name: str
    capacity_portions_per_hour: Decimal
    available_hours: Decimal
    active: bool


Role = Literal["cook", "driver", "packer", "coordinator"]


class VolunteerCreate(_In):
    name: Name
    role: Role
    team_id: UUID | None = None
    available_hours: Annotated[Decimal, Field(ge=0, le=24, max_digits=5, decimal_places=2)] = (
        Decimal("4")
    )


class VolunteerUpdate(_In):
    """Unavailability is an operational event (VOLUNTEER_UNAVAILABLE)."""

    name: Name | None = None
    role: Role | None = None
    team_id: UUID | None = None
    available_hours: (
        Annotated[Decimal, Field(ge=0, le=24, max_digits=5, decimal_places=2)] | None
    ) = None


class VolunteerOut(_Out):
    name: str
    role: str
    team_id: UUID | None = None
    available: bool
    available_hours: Decimal
    unavailable_reason: str | None = None


# ------------------------------------------------------------- deliveries
class DeliveryCreate(_In):
    route_name: Name
    capacity_meals: Annotated[int, Field(ge=0, le=100_000)]
    departs_at: datetime


class DeliveryUpdate(_In):
    """Delays and cancellations are operational events."""

    route_name: Name | None = None
    capacity_meals: Annotated[int, Field(ge=0, le=100_000)] | None = None


class DeliveryOut(_Out):
    route_name: str
    capacity_meals: int
    departs_at: datetime
    status: str
    delay_minutes: int
    status_reason: str | None = None


# ------------------------------------------------------------ commitments
class CommitmentCreate(_In):
    recipient: Annotated[str, Field(min_length=1, max_length=200)]
    meal_id: UUID
    meals_count: Annotated[int, Field(gt=0, le=100_000)]
    diet_requirements: list[Diet] = Field(default_factory=list)
    due_at: datetime
    delivery_id: UUID | None = None


class CommitmentUpdate(_In):
    """Count, diet, due time and status change only via COMMITMENT_CHANGED."""

    recipient: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    delivery_id: UUID | None = None


class CommitmentOut(_Out):
    recipient: str
    meal_id: UUID
    meals_count: int
    diet_requirements: list[str]
    due_at: datetime
    delivery_id: UUID | None = None
    status: str
    version: int


# ------------------------------------------------------- read-only views
class DonationOut(_Out):
    donor_id: UUID | None = None
    description: str
    status: str
    expected_at: datetime | None = None
    received_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None
    source_event_id: UUID | None = None


class LotOut(_Out):
    ingredient_id: UUID
    donation_id: UUID | None = None
    reported_quantity: Decimal
    reported_unit: Unit
    initial_quantity_base: Decimal
    quantity_base: Decimal
    base_unit: Unit
    status: str
    expires_at: datetime | None = None


class ResourceSpec(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    table: str
    create: type[_In]
    update: type[_In]
    out: type[_Out]
    order: str = "created_at.asc"


RESOURCES: dict[str, ResourceSpec] = {
    "donors": ResourceSpec(
        table="donors", create=DonorCreate, update=DonorUpdate, out=DonorOut, order="name.asc"
    ),
    "ingredients": ResourceSpec(
        table="ingredients",
        create=IngredientCreate,
        update=IngredientUpdate,
        out=IngredientOut,
        order="name.asc",
    ),
    "recipes": ResourceSpec(
        table="recipes", create=RecipeCreate, update=RecipeUpdate, out=RecipeOut, order="name.asc"
    ),
    "recipe-ingredients": ResourceSpec(
        table="recipe_ingredients",
        create=RecipeIngredientCreate,
        update=RecipeIngredientUpdate,
        out=RecipeIngredientOut,
    ),
    "substitutions": ResourceSpec(
        table="ingredient_substitutions",
        create=SubstitutionCreate,
        update=SubstitutionUpdate,
        out=SubstitutionOut,
    ),
    "meals": ResourceSpec(
        table="meals", create=MealCreate, update=MealUpdate, out=MealOut, order="name.asc"
    ),
    "meal-components": ResourceSpec(
        table="meal_components",
        create=MealComponentCreate,
        update=MealComponentUpdate,
        out=MealComponentOut,
    ),
    "teams": ResourceSpec(
        table="preparation_teams",
        create=TeamCreate,
        update=TeamUpdate,
        out=TeamOut,
        order="name.asc",
    ),
    "volunteers": ResourceSpec(
        table="volunteers",
        create=VolunteerCreate,
        update=VolunteerUpdate,
        out=VolunteerOut,
        order="name.asc",
    ),
    "deliveries": ResourceSpec(
        table="deliveries",
        create=DeliveryCreate,
        update=DeliveryUpdate,
        out=DeliveryOut,
        order="departs_at.asc",
    ),
    "commitments": ResourceSpec(
        table="commitments",
        create=CommitmentCreate,
        update=CommitmentUpdate,
        out=CommitmentOut,
        order="due_at.asc",
    ),
}
CHILD_TABLES = {
    "recipe_ingredients": ("recipes", "recipe_id"),
    "meal_components": ("meals", "meal_id"),
}
