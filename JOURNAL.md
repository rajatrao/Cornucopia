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
