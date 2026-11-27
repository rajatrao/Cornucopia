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

## 2026-11-27 Phase 3: deterministic resource compiler (branch `phase-3-resource-compiler`)

### Files created
- Backend: `compiler/{snapshot,diet,calculators,plan,planner,validator,substitutions,compare}.py`, `depgraph/graph.py`, `api/compiler.py`, `tests/{compiler_fixtures,test_compiler}.py`
- DB: `db/sql/0004_snapshot.sql`, `db/alembic/versions/0004_snapshot.py`, `supabase/migrations/20261127032000_snapshot.sql`
- Frontend: `app/compiler/page.tsx`, `components/compiler-view.tsx`, `e2e/phase3.spec.ts`
- `scripts/seed_sample.py`, `OPTIMIZATION_ENGINE.md`, `docs/img/phase3-compiler.png`

### Files modified
`persistence/repositories/operations.py` (snapshot), `persistence/memory.py` (snapshot + server defaults), `api/app.py`, `pyproject.toml` (networkx), BFF proxy whitelist, nav, Playwright config (serial), docs.

### Architecture decisions
- The compiler is pure and works on one consistent snapshot read in a single RPC. That gives one gateway round trip and no torn reads.
- The baseline planner is deliberately simple (greedy, earliest due first). The independent validator is what certifies feasibility.
- Consumption is rounded up to milligrams, so the plan never under-allocates.
- A late delivery route is a risk, not a hard constraint. Minimising delivery disruption is a soft objective for Phase 4.
- Sample data is labelled `[sample]` and loaded only through the public API.

### Verification
See TESTING.md "Phase 3 results".

### Known limitations
- The baseline uses no substitutions and may serve early commitments at the expense of later ones. Phase 4 optimises globally.
- Every team can cook every recipe (MVP); there is no per-recipe skill mapping.
- Plans are computed on demand and not stored yet. PlanVersion and OptimizationRun persistence arrive with Phases 4 to 6.

### Acceptance checklist
- [x] Initial operational plan can be generated (live: 500/500, validator valid)
- [x] Resource shortages are identified (rice short 120.0 lb after cancellation)
- [x] Affected dependencies are identified (NetworkX impact; tested for every event kind)
- [x] Infeasible commitments are detected (with the binding resource)
- [x] Ingredient substitutions are validated (scope, diet, spare stock, ratio)
- [x] All calculations have reproducible tests (determinism and order-independence tests)

Recommendation: proceed to Phase 4.

## 2026-11-27 Phase 4: OR-Tools CP-SAT optimization engine (branch `phase-4-optimizer`)

### Files created
- Backend: `optimizer/{model,diagnosis,service}.py`, `api/optimizer.py`, `tests/test_optimizer.py`
- DB: `db/sql/0005_optimization_runs.sql`, `db/alembic/versions/0005_optimization_runs.py`, `supabase/migrations/20261127034000_optimization_runs.sql`
- Frontend: `app/optimizer/page.tsx`, `components/optimizer-view.tsx`, `e2e/phase4.spec.ts`; `docs/img/phase4-optimizer.png`

### Files modified
`compiler/plan.py` (routing), `compiler/planner.py`, `compiler/validator.py` (routing checks), `persistence/{models,memory}.py`, repositories, `api/app.py`, `pyproject.toml` (ortools), BFF whitelist, `lib/api/server.ts` (read retry), nav, docs.

### Architecture decisions
- Lexicographic optimisation in six stages rather than weighted sums, so no priority can be bought with another.
- Ingredient needs are modelled as exact rationals, so the solver can fully replace an ingredient without rounding gaps. Substitute use is pinned to exactly ceil(r·ratio).
- Feasibility is labelled only by the independent validator (`verdict`), never by solver status.
- Rerouting is a recovery option and counts toward delivery disruption. Diets are enforced structurally.
- The diagnosis model answers "what would it take?" in concrete units.
- Determinism comes from a single worker, a fixed seed and deterministic-time limits.

### Known limitations
- The reference plan (minimal change) needs approved plans (Phase 6). Until then stage 3 counts only substitution rules used.
- When there isn't enough for everyone, the optimizer maximises commitments fully met, then meals. A "fair share" policy across recipients is not modelled.
- The no-substitution and no-rerouting candidates are re-solved per run. That is cheap at the demo scale (≈ 30 ms each).

### Acceptance checklist
- [x] Solver produces verified feasible plans (verified_feasible with full resources, or with 125 lb quinoa)
- [x] Solver identifies infeasible scenarios (0/500 after rice cancellation without substitutes)
- [x] Constraint violations are explained (binding resources per commitment, diagnosis shortfalls, blocked diets)
- [x] Alternative plans can be compared (4 candidates with verdicts and deterministic diffs)
- [x] Optimization is deterministic for fixed inputs and configuration (tests + live)
- [x] Performance is measured on the demonstration dataset (OPTIMIZATION_ENGINE.md)

Recommendation: proceed to Phase 5.

## 2026-11-27 Phase 5: LangGraph autonomous agent (branch `phase-5-agent`)

### Files created
- Backend: `agent/{checkpointer,tools,graph,supervisor}.py`, `worker.py`, `api/agent.py`, `tests/test_agent.py`, `tests/db/test_agent_sql.py`
- DB: `db/sql/0006_agent.sql`, `db/alembic/versions/0006_agent.py`, `supabase/migrations/20261127040000_agent.sql`
- Frontend: `app/executions/page.tsx`, `components/executions-view.tsx`, `e2e/phase5.spec.ts`
- `AGENT_WORKFLOW.md`, `docs/img/phase5-agent.png`

### Files modified
`persistence/{models,memory}.py`, repositories, `api/app.py`, `pyproject.toml` (langgraph), `scripts/deploy_sprite.sh` (worker service), BFF whitelist, nav, `e2e/phase4.spec.ts` (data-independent), docs.

### Architecture decisions
- **Custom checkpointer.** LangGraph's Postgres saver needs SQL; the connector is REST-only. `SupabaseCheckpointSaver` stores each checkpoint as one serde blob through idempotent RPCs.
- **Leases with fencing tokens.** `attempt` increments on every claim, and all writes are refused unless `(worker, attempt)` still holds the lease.
- **Facts applied once.** Events are applied at ingest. The agent's `update_operational_state` only verifies, so re-running it is harmless.
- **Idempotent side effects.** Optimization runs are keyed by `execution:strategy:retry`.
- **Impact scoped to the event.** Pre-existing shortfalls are not blamed on unrelated events. This was found in the live backlog run and fixed.
- **Separate service.** The agent is its own Sprite service, uses the Tasks API to stay awake while busy, and lets the Sprite pause when idle.

### Known limitations
- Each event is handled against the *current* operational state, so a backlog of old events is reconciled against today's reality.
- Several proposals can be awaiting approval at once (one per event). Phase 6 marks superseded ones STALE through state-version and fingerprint binding.
- `commit_approved_plan` raises until the Phase 6 approval engine exists.
- The gateway adds roughly 0.3 s per round trip, so an execution takes about 8 to 18 s with sync checkpointing.

### Acceptance checklist
- [x] Agent processes events (live: 48 + new events, autonomous, independent of the UI)
- [x] Agent generates recovery proposals (verified 500/500 proposal awaiting approval)
- [x] Checkpoints survive process restart (kill -9 drill on the Sprite; crash test)
- [x] Duplicate execution does not duplicate operational changes (unique execution per event, fenced writes, idempotent runs; tests)
- [x] Infeasible cases escalate (partial plans escalate with diagnosis; invalid events escalate)
- [x] Execution history is visible in the UI (Agent page timeline; Playwright)

Recommendation: proceed to Phase 6.

## 2026-11-27 Phases 6–9 (branch `phase-6-approvals`, delivered together at Raj's request)

### Phase 6: approval and transactional commit engine
- Migrations 0007 (approvals), 0008 (operator changes do not bump the operational version) and 0009 (outbox delivery, worker liveness), all applied.
- `backend/cornucopia/{auth,admin}.py`, `api/approvals.py`. Operator sessions; roles enforced; actor derived from the session.
- The agent proposes at `request_approval`, resumes on decisions and commits through `commit_approved_plan`. Partial-but-better plans go to humans flagged as escalations.
- Acceptance:
  - [x] approval and rejection work
  - [x] stale approvals fail (at decision and at commit)
  - [x] unauthorized operators cannot approve (recorded)
  - [x] concurrent approvals are safe (one wins)
  - [x] committed plans have complete audit history (row audit under the approver, decision log, plan version, outbox)

### Phase 7: command center
- New pages: Command Center (`/`), Reality Recompilation (React Flow), Approval Center, Simulation Lab (`/simulation`), Sign in. The older Phase 1 page moved to `/system`.
- Acceptance:
  - [x] all screens functional with live data
  - [x] forms validate
  - [x] approvals work end to end
  - [x] responsive (Playwright mobile project)
  - [x] Playwright passes

### Phase 8: persistence, resilience, deployment
- Outbox delivery into the notification feed, `agent_workers` heartbeats, `/health/agent`, JSON logs, supervisor backoff, session secret generated on the Sprite, Sprite URL switched to public (all routes need the token, operational routes also need a session).
- Drills: worker KILL → resumed attempt 2 (Phase 5 and again here); API restart; graceful stop.
- Vercel: steps documented. **Needs Raj's Vercel login** (CLI not installed or authenticated on this machine).
- Acceptance:
  - [x] agent executes inside the Sprite
  - [x] frontend reaches the Sprite API
  - [x] connector works in production
  - [x] restarts lose nothing
  - [x] interrupted workflows recover
  - [x] no duplicate commits
  - [x] health checks
  - [x] independently verifiable (public URL + DEMO_SCRIPT)

### Phase 9: demonstration
- `scripts/run_scenarios.py` and `DEMO_SCRIPT.md`. The rehearsal org ran both scenarios end to end in 70 s. The clean demo org `thanksgiving-2026-demo` is seeded and live on the Sprite, waiting for the operator's first event.

### Known limitations / risks
- **Public Sprite URL stalls.** Through the public URL, some requests from a laptop stalled until client timeout (they never reached the API). The same calls through `sprite proxy`, and API calls inside the Sprite, were reliable. The frontend retries idempotent reads once; writes are idempotent by key, so a retried event submission is safe. Re-check after deploying to Vercel.
- No sign-in rate limiting yet.
- A demo video is not recorded yet (requested for after development).
- Gateway latency (~0.3 s per call) keeps an agent execution around 10–20 s.
