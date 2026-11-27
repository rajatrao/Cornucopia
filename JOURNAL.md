# Implementation journal

## 2026-11-27 Phase 0: discovery

- Repo is greenfield (no commits; only the master prompt).
- Added `.gitignore` and gitignored `.env` (mode 600) before any commit.
- Verified Sprite `cornucopia` and Supabase connector `4mTfP1SN5GkJtGuDrHCE-A` exist.
- Live probes from the Sprite: REST root 200 (PostgREST 14.18), RPC reaches PostgREST, `/auth/v1` blocked (403), custom schema requires exposure (PGRST106). Laptop call gets 401.
- Wrote `docs/PHASE0_DISCOVERY.md`, `ARCHITECTURE.md`, `IMPLEMENTATION_PLAN.md`, `CONNECTOR_SETUP.md`.
- Waiting on Raj: architecture approval and assumptions A1 to A5.

## 2026-11-27 Phase 1: foundation and Supabase connector

Raj approved Phase 0 with: dedicated `cornucopia` schema, Supabase CLI for schema changes, Vercel for the frontend.

### Files created
- `backend/` (pyproject, uv.lock, `cornucopia/{config,main}.py`, `api/{app,schemas}.py`, `persistence/{client,memory,factory,models}.py`, `persistence/repositories/`, `tests/test_phase1_foundation.py`)
- `db/alembic.ini`, `db/alembic/{env.py,script.py.mako,versions/0001_foundation.py}`, `db/sql/0001_foundation.sql`
- `supabase/config.toml`, `supabase/migrations/20261127000100_foundation.sql`
- `frontend/` (Next.js 16 app: `src/lib/api/{server.ts,contract.gen.ts}`, `src/app/{page,layout}.tsx`, `src/app/api/probes/route.ts`, `src/components/probe-form.tsx`, Playwright config + `e2e/phase1.spec.ts`, `.env.example`)
- `contracts/openapi.json`; `scripts/{deploy_sprite,gen_migration,verify_migrations_local,export_contracts}.sh`
- `README.md`, `DEPLOYMENT.md`, `DATABASE_SCHEMA.md`, `SECURITY.md`, `TESTING.md`, `CHANGELOG.md`, `docs/img/phase1-runtime-link.png`

### Files modified
`.gitignore`, `ARCHITECTURE.md` (Vercel, repo layout), `CONNECTOR_SETUP.md` (schema exposure via CLI).

### Architecture decisions
- One `SupabaseClient` interface; transport chosen explicitly by config, no fallback. Production refuses `direct`.
- Only GET requests are auto-retried; writes go through RPCs and will carry idempotency keys from Phase 2.
- Alembic generates, the Supabase CLI applies. `alembic check` guards drift between models and migrations.
- `config.toml` declares only `[api]` so `config push` cannot alter auth/storage settings.
- Frontend calls the API only from server code (`server-only`), so the token never reaches the browser.

### Verification (all against real services)
- Schema created and exposed: `supabase db push --remote`, `supabase config push`.
- From the Sprite through the connector: `rpc/health_check` 200; probe inserted and read back via the deployed API (`source=gateway`).
- Laptop direct mode: health + insert + read OK.
- Tests: pytest 15 passed; ruff, ruff format, mypy strict clean; `alembic check` clean; migrations reproduce identical schemas; Playwright 8/8 (desktop and mobile); client bundle contains no token, `sb_secret`, `supabase.co` or `api.sprites.dev`.

### Known limitations
- Frontend not yet on Vercel: the Sprite URL is org-private until operator auth exists (Phase 8). Verified locally via `sprite proxy`.
- Single shared bearer token; per-operator auth and roles are Phase 6/8.
- Worker service not created yet (Phase 5/8).

### Remaining risks
- Supabase key and DB password were shared in chat: rotate both.
- Connector policy still allow-all.
- Gateway latency measured at ~300 to 520 ms per call from the Sprite. Phase 3+ must batch reads into snapshot RPCs.

### Acceptance checklist
- [x] Backend starts (locally and as a Sprite service)
- [x] Frontend starts (production build, `next start`)
- [x] Sprite can access Supabase through the connector
- [x] A test record can be inserted
- [x] A test record can be retrieved
- [x] Database migrations are reproducible
- [x] No privileged secret reaches the browser

Recommendation: proceed to Phase 2.

## 2026-11-27 Phase 2: domain model and operational event engine (branch `phase-2-domain-events`)

### Files created
- Backend: `domain/{units,events,inventory,resources}.py`, `persistence/repositories/operations.py`, `api/operations.py`, `tests/{test_units,test_phase2_api}.py`, `tests/db/test_ingest_event_sql.py`
- DB: `db/sql/{0002_domain_events,0003_resource_writes}.sql`, `db/alembic/versions/{0002_domain_events,0003_resource_writes}.py`, `supabase/migrations/{20261127030000_domain_events,20261127031500_resource_writes}.sql`
- Frontend: `app/{resources,inventory,events,history}/page.tsx`, `app/api/ops/[...path]/route.ts`, `components/{field-input,resource-manager,event-center,inventory-view,audit-view,site-nav}.tsx`, `lib/{ops,resource-config}.ts`, `e2e/phase2.spec.ts`
- `docs/img/phase2-{event-center,inventory}.png`

### Files modified
`persistence/models.py`, `persistence/memory.py`, `api/app.py`, `config.py`, `scripts/deploy_sprite.sh` (org config), `frontend/src/lib/api/server.ts`, `app/layout.tsx`, docs.

### Architecture decisions
- **Facts vs. plans.** Events record what happened in the world, such as a cancelled donation or a sick volunteer, and update operational state immediately and atomically. Plan changes that respond to those facts are proposals that need approval (Phases 5 and 6).
- **One write path per kind.** Master data goes through `write_resource` and operational facts through `ingest_event`. Direct table writes are revoked, so every change is audited with its actor.
- **Gateway finding:** custom headers are not forwarded, so the actor travels as an RPC argument.
- Quantities keep the operator's report and a base-unit value. Unsafe conversions are refused with a clear message.
- Lots and donations are event-sourced, not CRUD.
- Deployment operates org `cornucopia-dev`. The Phase 9 demo will use a clean org.

### Verification
See TESTING.md "Phase 2 results": 54 backend tests (11 on real Postgres incl. concurrent duplicate submissions), live connector check on the Sprite, 16 Playwright tests against the real stack.

### Known limitations
- Actor identity is asserted by the frontend server (single shared token). Per-operator auth comes in Phase 6/8.
- The in-memory test double implements only some event effects. Authoritative semantics are tested in SQL.
- The dev org contains `[e2e]` and `[verify]` records from automated tests.
- The UI is functional, not yet the Phase 7 command-center design.

### Acceptance checklist
- [x] CRUD operations work through the UI (Playwright, desktop + mobile)
- [x] Event creation works (all 9 types have structured forms; DB effects tested)
- [x] Event history is persistent (Supabase journal, append-only)
- [x] Duplicate event submissions do not create duplicate effects (API, DB, concurrency, UI double-submit)
- [x] Inventory calculations are validated (summary tests, live 180 lb → 0 lb)
- [x] Unit conversions pass tests (19)

Recommendation: proceed to Phase 3.
