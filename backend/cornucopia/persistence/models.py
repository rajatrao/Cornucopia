"""SQLAlchemy models: the source of truth for generated DDL.

These models describe the schema; the application does not open a SQL
connection with them (the connector is REST only). Alembic renders them to
SQL migrations that the Supabase CLI applies.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "cornucopia"

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA, naming_convention=NAMING)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    __table_args__ = (CheckConstraint("slug ~ '^[a-z0-9-]+$'", name="slug_format"),)


class SystemProbe(Base):
    """Connectivity test records written through the connector."""

    __tablename__ = "system_probes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    note: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    __table_args__ = (
        CheckConstraint("source in ('gateway','direct','test','cli')", name="source_known"),
        CheckConstraint("length(note) between 1 and 500", name="note_length"),
    )


# --------------------------------------------------------------------------
# Phase 2: domain model. Shared vocabularies are enforced with CHECKs so the
# database rejects anything the Python enums would reject.
# --------------------------------------------------------------------------

UNITS = "('g','kg','oz','lb','ml','l','tsp','tbsp','cup','fl_oz','qt','gal','each','portion')"
BASE_UNITS = "('g','ml','each')"
ATTRIBUTES = (
    "'meat','pork','poultry','fish','shellfish','dairy','egg','gluten','nuts','peanuts',"
    "'soy','sesame','alcohol','animal_product'"
)
DIETS = "'vegetarian','vegan','gluten_free','nut_free','dairy_free','halal'"


def _org_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )


def _fk(table: str, *, nullable: bool = False, ondelete: str = "RESTRICT") -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.{table}.id", ondelete=ondelete),
        nullable=nullable,
        index=True,
    )


def _updated_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def _qty() -> Mapped[Decimal]:
    return mapped_column(Numeric(14, 3), nullable=False)


class Donor(Base):
    __tablename__ = "donors"
    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = _org_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, server_default="individual")
    contact: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    __table_args__ = (
        CheckConstraint("kind in ('individual','business','farm','organization')", name="kind"),
        UniqueConstraint("organization_id", "name"),
    )


class Ingredient(Base):
    __tablename__ = "ingredients"
    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = _org_fk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False, server_default="other")
    base_unit: Mapped[str] = mapped_column(String(8), nullable=False)
    density_g_per_ml: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    unit_weight_g: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    attributes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    perishable_days: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    __table_args__ = (
        UniqueConstraint("organization_id", "name"),
        CheckConstraint(f"base_unit in {BASE_UNITS}", name="base_unit"),
        CheckConstraint("density_g_per_ml is null or density_g_per_ml > 0", name="density_pos"),
        CheckConstraint("unit_weight_g is null or unit_weight_g > 0", name="unit_weight_pos"),
        CheckConstraint(f"attributes <@ array[{ATTRIBUTES}]::text[]", name="attributes_known"),
        CheckConstraint(
            "category in ('grain','vegetable','fruit','protein','dairy','fat','seasoning',"
            "'sauce','bakery','other')",
            name="category",
        ),
    )


class Donation(Base):
    __tablename__ = "donations"
    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = _org_fk()
    donor_id: Mapped[uuid.UUID | None] = _fk("donors", nullable=True)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    expected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    __table_args__ = (
        CheckConstraint("status in ('pledged','received','cancelled')", name="status"),
        CheckConstraint(
            "(status = 'cancelled') = (cancelled_at is not null)", name="cancelled_consistent"
        ),
    )


class InventoryLot(Base):
    __tablename__ = "inventory_lots"
    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = _org_fk()
    ingredient_id: Mapped[uuid.UUID] = _fk("ingredients")
    donation_id: Mapped[uuid.UUID | None] = _fk("donations", nullable=True)
    # as reported (explicit unit) ...
    reported_quantity: Mapped[Decimal] = _qty()
    reported_unit: Mapped[str] = mapped_column(String(8), nullable=False)
    # ... and normalised to the ingredient's base unit, which all math uses.
    initial_quantity_base: Mapped[Decimal] = _qty()
    quantity_base: Mapped[Decimal] = _qty()
    base_unit: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    __table_args__ = (
        CheckConstraint(
            "status in ('pledged','available','depleted','expired','cancelled')", name="status"
        ),
        CheckConstraint("quantity_base >= 0", name="qty_nonneg"),
        CheckConstraint("initial_quantity_base > 0", name="initial_pos"),
        CheckConstraint("reported_quantity > 0", name="reported_pos"),
        CheckConstraint(f"reported_unit in {UNITS}", name="reported_unit"),
        CheckConstraint(f"base_unit in {BASE_UNITS}", name="base_unit"),
        Index("ix_inventory_lots_ingredient_status", "ingredient_id", "status"),
    )


class Recipe(Base):
    __tablename__ = "recipes"
    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = _org_fk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    yield_portions: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    prep_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    __table_args__ = (
        UniqueConstraint("organization_id", "name"),
        CheckConstraint("yield_portions > 0", name="yield_pos"),
        CheckConstraint("prep_minutes >= 0", name="prep_nonneg"),
    )


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"
    id: Mapped[uuid.UUID] = _uuid_pk()
    recipe_id: Mapped[uuid.UUID] = _fk("recipes", ondelete="CASCADE")
    ingredient_id: Mapped[uuid.UUID] = _fk("ingredients")
    quantity: Mapped[Decimal] = _qty()
    unit: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity_base: Mapped[Decimal] = _qty()
    optional: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = _created_at()
    __table_args__ = (
        UniqueConstraint("recipe_id", "ingredient_id"),
        CheckConstraint("quantity > 0 and quantity_base > 0", name="qty_pos"),
        CheckConstraint(f"unit in {UNITS}", name="unit"),
    )


class IngredientSubstitution(Base):
    __tablename__ = "ingredient_substitutions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = _org_fk()
    ingredient_id: Mapped[uuid.UUID] = _fk("ingredients")
    substitute_id: Mapped[uuid.UUID] = _fk("ingredients")
    # substitute base units needed per 1 base unit of the original
    ratio: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    recipe_id: Mapped[uuid.UUID | None] = _fk("recipes", nullable=True, ondelete="CASCADE")
    notes: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    __table_args__ = (
        CheckConstraint("ingredient_id <> substitute_id", name="not_self"),
        CheckConstraint("ratio > 0", name="ratio_pos"),
        Index(
            "uq_ingredient_substitutions_scope",
            "ingredient_id",
            "substitute_id",
            text("coalesce(recipe_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            unique=True,
        ),
    )


class Meal(Base):
    __tablename__ = "meals"
    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = _org_fk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    __table_args__ = (UniqueConstraint("organization_id", "name"),)


class MealComponent(Base):
    """A meal is one or more recipe portions (e.g. rice + potatoes + carrots)."""

    __tablename__ = "meal_components"
    id: Mapped[uuid.UUID] = _uuid_pk()
    meal_id: Mapped[uuid.UUID] = _fk("meals", ondelete="CASCADE")
    recipe_id: Mapped[uuid.UUID] = _fk("recipes")
    portions: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, server_default="1")
    created_at: Mapped[datetime] = _created_at()
    __table_args__ = (
        UniqueConstraint("meal_id", "recipe_id"),
        CheckConstraint("portions > 0", name="portions_pos"),
    )


class PreparationTeam(Base):
    __tablename__ = "preparation_teams"
    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = _org_fk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    capacity_portions_per_hour: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    available_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    __table_args__ = (
        UniqueConstraint("organization_id", "name"),
        CheckConstraint("capacity_portions_per_hour >= 0", name="capacity_nonneg"),
        CheckConstraint("available_hours >= 0", name="hours_nonneg"),
    )


class Volunteer(Base):
    __tablename__ = "volunteers"
    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = _org_fk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    team_id: Mapped[uuid.UUID | None] = _fk("preparation_teams", nullable=True, ondelete="SET NULL")
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    available_hours: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default="4"
    )
    unavailable_reason: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    __table_args__ = (
        CheckConstraint("role in ('cook','driver','packer','coordinator')", name="role"),
        CheckConstraint("available_hours >= 0", name="hours_nonneg"),
    )


class Delivery(Base):
    """A delivery route run with a meal capacity."""

    __tablename__ = "deliveries"
    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = _org_fk()
    route_name: Mapped[str] = mapped_column(String(120), nullable=False)
    capacity_meals: Mapped[int] = mapped_column(Integer, nullable=False)
    departs_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="scheduled")
    delay_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    status_reason: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    __table_args__ = (
        UniqueConstraint("organization_id", "route_name"),
        CheckConstraint("status in ('scheduled','delayed','cancelled','completed')", name="status"),
        CheckConstraint("capacity_meals >= 0", name="capacity_nonneg"),
        CheckConstraint("delay_minutes >= 0", name="delay_nonneg"),
    )


class Commitment(Base):
    __tablename__ = "commitments"
    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = _org_fk()
    recipient: Mapped[str] = mapped_column(String(200), nullable=False)
    meal_id: Mapped[uuid.UUID] = _fk("meals")
    meals_count: Mapped[int] = mapped_column(Integer, nullable=False)
    diet_requirements: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    delivery_id: Mapped[uuid.UUID | None] = _fk("deliveries", nullable=True, ondelete="SET NULL")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    __table_args__ = (
        CheckConstraint("meals_count > 0", name="count_pos"),
        CheckConstraint("status in ('active','cancelled','fulfilled')", name="status"),
        CheckConstraint(f"diet_requirements <@ array[{DIETS}]::text[]", name="diets_known"),
    )


class MealBatch(Base):
    """Planned cooking batches. Populated by the planner from Phase 3."""

    __tablename__ = "meal_batches"
    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = _org_fk()
    recipe_id: Mapped[uuid.UUID] = _fk("recipes")
    team_id: Mapped[uuid.UUID | None] = _fk("preparation_teams", nullable=True)
    planned_portions: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="planned")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    plan_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    __table_args__ = (
        CheckConstraint("planned_portions >= 0", name="portions_nonneg"),
        CheckConstraint("status in ('planned','in_progress','done','cancelled')", name="status"),
    )


class OperationalState(Base):
    """Monotonic version of an organization's operational inputs.

    Bumped by triggers on every planning-relevant change. Plans record the
    version they were computed against; commits (Phase 6) reject stale plans.
    """

    __tablename__ = "operational_state"
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.organizations.id"), primary_key=True
    )
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = _updated_at()


EVENT_TYPES = (
    "'DONATION_CREATED','DONATION_CANCELLED','INVENTORY_ADJUSTED','INGREDIENT_EXPIRED',"
    "'VOLUNTEER_UNAVAILABLE','DELIVERY_DELAYED','DELIVERY_CANCELLED','COMMITMENT_CHANGED',"
    "'PREPARATION_CAPACITY_CHANGED'"
)


class OperationalEvent(Base):
    """Append-only journal. Only processing columns may change (trigger)."""

    __tablename__ = "operational_events"
    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = _org_fk()
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    effect: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    state_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    processing_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending"
    )
    processing_note: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key"),
        CheckConstraint(f"event_type in ({EVENT_TYPES})", name="event_type"),
        CheckConstraint(
            "processing_status in ('pending','processing','processed','failed','escalated',"
            "'ignored')",
            name="processing_status",
        ),
        CheckConstraint("length(idempotency_key) between 8 and 200", name="key_length"),
        Index("ix_operational_events_org_created", "organization_id", "created_at"),
        Index("ix_operational_events_status", "processing_status", "created_at"),
    )


class AuditRecord(Base):
    """Row-level audit written by triggers in the same transaction as the change."""

    __tablename__ = "audit_records"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    table_name: Mapped[str] = mapped_column(String(64), nullable=False)
    record_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(8), nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    old_row: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    new_row: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        CheckConstraint("action in ('INSERT','UPDATE','DELETE')", name="action"),
        Index("ix_audit_records_table_record", "table_name", "record_id"),
    )


# --------------------------------------------------------------------------
# Phase 4: optimization runs (append-only record of every solver execution)
# --------------------------------------------------------------------------


class OptimizationRun(Base):
    __tablename__ = "optimization_runs"
    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = _org_fk()
    state_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    requested_by: Mapped[str] = mapped_column(String(120), nullable=False)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    solver_status: Mapped[str] = mapped_column(String(24), nullable=False)
    verdict: Mapped[str] = mapped_column(String(24), nullable=False)
    objectives: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    stages: Mapped[list[object]] = mapped_column(JSONB, nullable=False)
    model_stats: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    diagnosis: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    wall_ms: Mapped[Decimal] = mapped_column(Numeric(12, 1), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    __table_args__ = (
        CheckConstraint(
            "verdict in ('verified_feasible','verified_partial','unverified','failed')",
            name="verdict",
        ),
        Index("ix_optimization_runs_org_created", "organization_id", "created_at"),
    )


class OptimizationResult(Base):
    """One candidate plan produced by a run; exactly one is ``recommended``."""

    __tablename__ = "optimization_results"
    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = _fk("optimization_runs", ondelete="RESTRICT")
    candidate: Mapped[str] = mapped_column(String(40), nullable=False)
    recommended: Mapped[bool] = mapped_column(Boolean, nullable=False)
    verdict: Mapped[str] = mapped_column(String(24), nullable=False)
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    meals_planned: Mapped[int] = mapped_column(Integer, nullable=False)
    plan: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    summary: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _created_at()
    __table_args__ = (
        UniqueConstraint("run_id", "candidate"),
        Index(
            "uq_optimization_results_one_recommended",
            "run_id",
            unique=True,
            postgresql_where=text("recommended"),
        ),
    )
