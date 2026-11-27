# Changelog


## Unreleased

- **Reset demo** button in the sidebar for approvers and admins (`POST /api/v1/admin/demo-reset`). Moves to a fresh demonstration organization, keeps accounts and passwords, reloads the sample data, and keeps the Sprite awake while it runs. Off unless `CORNUCOPIA_DEMO_RESET_ROLE` is set.
- `scripts/reset_demo.sh` for the same reset from a terminal; the sample data now lives in `cornucopia.demo.seed`.
- `deploy_sprite.sh` keeps the current organization unless `CORNUCOPIA_ORG_SLUG` is given.
## 0.9.0 (2026-11-27): Phases 6–9 delivered together

### Phase 6: approvals and transactional commits
- Operator accounts (argon2id) with roles. HS256 session tokens issued by the API and kept by Next.js in an HttpOnly cookie. The acting operator always comes from the session.
- Versioned plans (`plan_versions`, `plan_changes`) and approval requests bound to plan version, fingerprint, state version, requesting execution and expiry.
- `decide_approval`: role, duplicate, expiry, fingerprint, staleness and explicit-confirmation checks. Every attempt is recorded, including refusals.
- `commit_approved_plan`: one transaction that re-verifies everything, applies batches, reservations, routing and planned meals, records the commit, audits under the approver's name and writes the outbox message.
- The agent proposes at `request_approval`, is resumed by the decision (`Command(resume=…)`) and commits through the fenced RPC. A newer proposal supersedes older ones (STALE).

### Phase 7: command center UI
- Command Center (KPIs, inventory health chart, commitments, shortages, agent status, approvals, events, notifications).
- Reality Recompilation with a React Flow dependency graph, original vs. replacement plan, objectives, risks and agent timeline.
- Approval Center with explicit confirmation and decision history, and a Simulation Laboratory running five isolated what-if scenarios.

### Phase 8: resilience and deployment
- Transactional outbox delivery into the notification feed, worker heartbeats, `/health/agent`, JSON logs and backoff in the supervisor loop.
- Public Sprite URL behind service token plus operator sessions; documented Vercel deployment; restart drills.

### Phase 9: demonstration
- A demonstration organization seeded through the API, the `scripts/run_scenarios.py` driver for both scenarios, and `DEMO_SCRIPT.md`.

## 0.5.0 (2026-11-27): Phase 5 LangGraph autonomous agent

- A 17-node LangGraph recovery agent with conditional routing, bounded strategy retries, node retry policies and explicit tool interfaces.
- `SupabaseCheckpointSaver`: a custom LangGraph checkpointer over the connector's REST/RPC surface (immutable, idempotent).
- Durable executions: lease-based claiming (`SKIP LOCKED`), heartbeat, attempt-fenced writes, crash recovery by lease expiry.
- Idempotent optimization runs keyed by execution, strategy and retry.
- `cornucopia-worker` Sprite service with a Sprites Tasks API keep-awake while running.
- Agent status and execution history API, and an Agent page with a live workflow timeline.

## 0.4.0 (2026-11-27): Phase 4 CP-SAT recovery optimizer

- CP-SAT model with exact rational ingredient needs, substitutions, rerouting and hard diet, stock, kitchen and route limits.
- Six-stage lexicographic optimisation: commitments met, meals served, minimal change, waste, delivery disruption, earlier-due tie-break.
- Exact post-processing plus independent validation; `verdict` is `verified_*` only when the validator agrees.
- Infeasibility diagnosis (minimum extra resources) and alternative plans with diffs.
- Deterministic solving: single worker, fixed seed, deterministic-time limits.
- Append-only `optimization_runs` / `optimization_results` with the `record_optimization_run` RPC.
- Optimizer API and page. Plan model gains `routing`, which the validator checks for every plan.
- Frontend retries idempotent reads once, so a paused Sprite's wake-up is not shown as an outage.

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
