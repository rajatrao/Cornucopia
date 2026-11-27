# Database schema

Schema: `cornucopia` (Supabase Postgres 17). Source of truth: SQLAlchemy models in `backend/cornucopia/persistence/models.py` plus `db/sql/*.sql`. Applied migrations live in `supabase/migrations/`.

| Migration | Contents |
|---|---|
| `20261127000100_foundation` | `organizations`, `system_probes`, `health_check()`, `record_probe()` |
| `20261127030000_domain_events` | domain tables, operational journal, audit log, triggers, `ensure_organization()`, `ingest_event()` |
| `20261127031500_resource_writes` | `write_resource()`, removal of direct table writes |

## Conventions

- UUID primary keys, `timestamptz` everywhere (UTC), `updated_at` maintained by trigger.
- Every quantity has an explicit unit. Lots and recipe lines keep the **reported** quantity and unit, plus a **base** quantity in the ingredient's base unit (`g`, `ml` or `each`). All arithmetic uses the base quantity.
- Vocabularies (units, dietary attributes, diets, statuses, event types) are enforced with CHECK constraints that mirror the Python enums.
- RLS enabled with no policies. `anon` and `authenticated` have nothing. `service_role` may read tables and execute RPCs; it cannot write domain tables directly.

## Tables

| Table | Purpose | Notable rules |
|---|---|---|
| `organizations` | operating organization | slug unique |
| `operational_state` | per-org monotonic `version` | bumped by every planning-relevant change |
| `donors` | who gives food | unique name per org |
| `ingredients` | catalog | immutable `base_unit`; optional `density_g_per_ml`, `unit_weight_g`; `attributes` ⊆ known dietary attributes |
| `donations` | donation records | created/cancelled only by events; cancelled ⇔ `cancelled_at` set |
| `inventory_lots` | stock | `quantity_base ≥ 0`; status `pledged/available/depleted/expired/cancelled`; changed only by events |
| `recipes`, `recipe_ingredients` | recipes per batch | yield > 0; one line per ingredient |
| `ingredient_substitutions` | allowed swaps | ratio > 0, not self, unique per (ingredient, substitute, recipe scope) |
| `meals`, `meal_components` | a meal = recipe portions | portions > 0 |
| `preparation_teams` | kitchen capacity | capacity/hours ≥ 0 |
| `volunteers` | people | role ∈ cook/driver/packer/coordinator |
| `deliveries` | route runs | status `scheduled/delayed/cancelled/completed` |
| `commitments` | promised meals | count > 0, diets ⊆ known diets, `version` increments on change |
| `meal_batches` | planned cooking | populated from Phase 3 |
| `operational_events` | append-only journal | unique `(organization_id, idempotency_key)`; only processing columns may change |
| `audit_records` | row-level audit | append-only, written by trigger in the same transaction |

## Functions

| Function | Behaviour |
|---|---|
| `ensure_organization(slug, name)` | idempotent org bootstrap |
| `ingest_event(org, key, type, payload, actor, correlation_id)` | Serialises on the idempotency key (advisory lock). Returns the original event for a duplicate with the same payload, and raises `P0409` for a reused key with a different payload. Otherwise it applies the fact, journals it with its `effect` and the new state version, and audits every row it touched. All of this happens in one transaction. |
| `write_resource(org, actor, table, action, id, values)` | Insert/update/delete for master data on a whitelist of tables. Enforces org ownership (including through parent rows), sets the actor and refuses server-managed fields. |
| `current_actor()` | actor for audit triggers |

Custom SQLSTATEs: `P0403` forbidden, `P0404` not found, `P0409` conflict, `P0422` invalid. The API maps them to HTTP status codes.
