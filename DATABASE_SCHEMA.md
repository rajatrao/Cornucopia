# Database schema

Schema: `cornucopia` (Supabase Postgres 17). Source of truth: SQLAlchemy models in `backend/cornucopia/persistence/models.py` plus `db/sql/*.sql`. Applied migrations live in `supabase/migrations/`.

## Conventions

- UUID primary keys (`gen_random_uuid()`), `timestamptz` columns, `now()` defaults; all times are UTC.
- Constraint names follow `pk_/uq_/ck_/fk_/ix_<table>_...`.
- RLS is enabled on every table with no policies, so `anon` and `authenticated` see nothing. Only `service_role` (the connector's key) has table and function privileges.
- Multi-row or invariant-bearing writes are plpgsql/SQL functions called through `POST /rest/v1/rpc/<fn>`.
- `cornucopia.alembic_version` records the Alembic revision. Supabase records applied files in `supabase_migrations.schema_migrations`.

## Tables (migration 20261127000100_foundation)

| Table | Purpose | Key constraints |
|---|---|---|
| `organizations` | Operating organization (one for the demo) | `slug` unique, `^[a-z0-9-]+$` |
| `system_probes` | Connectivity test records written through the connector | `source in (gateway, direct, test, cli)`, note 1 to 500 chars |

## Functions

| Function | Returns | Notes |
|---|---|---|
| `health_check()` | `jsonb {ok, schema, server_time, backend}` | stable, `search_path=''` |
| `record_probe(p_note text, p_source text)` | `system_probes` row | write path used by connectivity checks |

The domain tables listed in `ARCHITECTURE.md` §4 arrive in Phase 2 onward.
