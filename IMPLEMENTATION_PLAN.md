# CORNUCOPIA Implementation Plan

Each phase ends with a verification report in `JOURNAL.md` and waits for Raj's explicit approval before the next one starts.

## Phase 1: Foundation and Supabase connector
Build: `backend/` (uv project, FastAPI `/health`, `/health/db`, settings), `SupabaseTransport` with gateway/direct/memory implementations, repository interfaces, SQLAlchemy models for a first slice (organizations, operators, `system_probes`), offline Alembic → `db/migrations/0001_*.sql`, `frontend/` Next.js shell with a server-side call to `/health`.
Verify:
- `pytest` + `ruff` + `mypy` green.
- On the Sprite: insert and read a `system_probes` row through the gateway (logged response codes).
- Drop + re-apply migrations onto an empty `cornucopia` schema reproduces the same schema (compare `information_schema` dump).
- `grep` the built frontend bundle for `sb_secret`, `supabase.co`, `api.sprites.dev`: zero hits.
Needs from Raj first: A1 (exposed schema), A2 (migration path).

## Phase 2: Domain model and event engine
Build: all core tables, unit conversion engine (mass, volume, count, portion; density-gated cross-dimension), CRUD endpoints + UI forms, the nine event types with Pydantic payloads, `ingest_event` RPC with idempotency, append-only journal trigger.
Verify: unit conversion property tests, duplicate submission test (same idempotency key → one row, one effect), inventory arithmetic tests, Playwright CRUD smoke.

## Phase 3: Deterministic resource compiler
Build: recipe requirements, availability, FIFO-by-expiry allocation, prep and delivery capacity, substitution validation, NetworkX graph `Donation → InventoryLot → Ingredient → Recipe → MealBatch → Commitment → Delivery`, baseline plan, deterministic plan diff.
Verify: fixture-based tests for shortages, affected-node sets, infeasible commitments, substitution legality.

## Phase 4: CP-SAT optimizer
Build: integer-scaled model; hard constraints (diet, inventory, prep, volunteers, delivery); lexicographic objectives (preserve commitments → minimize plan changes → minimize waste → minimize delivery disruption); timeout; infeasibility diagnosis via assumption literals / sufficient assumptions; independent post-solve validator.
Verify: feasible + infeasible fixtures, violation explanations, determinism (same input → byte-identical result), timing on demo dataset.

## Phase 5: LangGraph agent
Build: the 17 nodes from the brief with conditional routing, bounded retries, `SupabaseCheckpointSaver`, lease-based supervisor, execution history API + UI.
Verify: kill the worker mid-graph and restart → resumes from checkpoint with no duplicate side effects; infeasible scenario routes to `escalate_to_operator`.

## Phase 6: Approval and transactional commit
Build: approval lifecycle (PENDING, APPROVED, REJECTED, EXPIRED, STALE, COMMITTED), fingerprints, `decide_approval`, `commit_approved_plan` (verify + apply + audit + outbox in one transaction), explicit confirmation step.
Verify: stale, duplicate, unauthorized, expired and concurrent approval tests against the real database.

## Phase 7: Command center UI
Build: Command Center, Resources, Event Center, Reality Recompilation (React Flow), Approval Center, Execution History, Simulation Lab.
Verify: Playwright end-to-end including approve/reject, responsive checks, forms validation.

## Phase 8: Deployment and resilience
Build: `scripts/deploy_sprite.sh` (documented `sprite` commands only), two Sprite services, Tasks heartbeat, startup recovery, outbox delivery, structured logs, graceful shutdown, frontend deploy, URL auth switch.
Verify: restart drills (`sprite-env services restart`, kill -9, forced cold), no lost history, no duplicate commits, health checks from outside.

## Phase 9: Demonstration
Build: demo seed (500 commitments, 180 lb rice, 120 lb potatoes, 100 lb carrots, 12 volunteers, 3 routes), rice-cancellation scenario, insufficient-resources escalation scenario, `DEMO_SCRIPT.md`, all required docs.
Verify: scripted run end to end from the UI; outcome computed by the optimizer, not hardcoded.
