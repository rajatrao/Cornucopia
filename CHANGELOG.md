# Changelog

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
