# Changelog

## 0.3.0 (2026-11-27): Phase 3 deterministic resource compiler

- `get_operational_snapshot` RPC: one consistent read of all planning inputs.
- Calculators for recipe requirements, dietary rules, availability (including expiry by date), FIFO allocation, preparation capacity (staffing-aware) and delivery capacity.
- Baseline planner that records the binding resource per commitment.
- Independent plan validator, canonical plan fingerprint and deterministic plan comparison.
- Substitution engine checked against recipe scope, every affected diet and spare stock.
- NetworkX dependency graph with impact analysis for all nine event types.
- API: `/compiler/plan`, `/compiler/impact/{event}`, `/compiler/graph`. New Compiler page.
- `scripts/seed_sample.py`: labelled sample Thanksgiving operation loaded through the API.

## 0.2.0 (2026-11-27): Phase 2 domain model and operational event engine

- Unit engine with exact Decimal conversions. Mass/volume needs a density and count/mass needs a unit weight; portions never convert.
- Domain schema: donors, ingredients, donations, inventory lots, recipes, substitutions, meals, teams, volunteers, deliveries, commitments, meal batches.
- Nine typed operational events with an idempotent, transactional `ingest_event` RPC and an append-only journal.
- Row-level audit trail and operational state version, both maintained by triggers.
- All writes go through RPCs carrying the actor, because the gateway does not forward custom headers.
- API: resources CRUD, inventory summary/lots/donations, events, audit.
- UI: Resources, Inventory, Event Center, Audit history; BFF proxy with a path whitelist.

## 0.1.0 (2026-11-27): Phase 1 foundation

- FastAPI service with `/health`, `/health/db` and connectivity probe endpoints; bearer-token auth.
- Supabase access behind `SupabaseClient`: gateway (production), direct (local dev only), in-memory (tests).
- `cornucopia` schema: `organizations`, `system_probes`, `health_check()` and `record_probe()` RPCs. Privileges locked to `service_role`, RLS on.
- Migration pipeline: SQLAlchemy models → Alembic → `supabase/migrations` → `supabase db push`.
- Sprite deploy script and `cornucopia-api` Sprite service.
- Next.js frontend with server-only API client, BFF route handler and live runtime panel; Playwright e2e.
- Shared API contract (`contracts/openapi.json`) with generated TypeScript types.

## 0.0.0 (2026-11-27): Phase 0 discovery

- Discovery report, architecture, implementation plan, connector notes.
