# CORNUCOPIA Architecture

> When resources change, the feast goes on.

Status: approved 2026-11-27 (Phase 0). Frontend host: Vercel. Schema changes: Supabase CLI. Platform facts referenced here are verified in `docs/PHASE0_DISCOVERY.md`.

## 1. Runtime topology

| Component | Where it runs | Responsibility |
|---|---|---|
| Next.js command center | Vercel | Renders backend-authoritative state. Server-side route handlers call the Sprite API with the operator's token. Makes no operational decisions. |
| `cornucopia-api` | Sprite service, `--http-port 8000` | Auth, input validation, CRUD, event intake, approval decisions, read models, simulations. |
| `cornucopia-worker` | Sprite service, `--needs cornucopia-api` | Agent supervisor: claims events by lease, runs the LangGraph workflow, writes checkpoints, heartbeats via the Sprites Tasks API while busy. |
| Sprites gateway | Fly.io | Authenticates the Sprite, applies the connector policy, injects the Supabase `sb_secret_` key. |
| Supabase Postgres | Supabase | Schema `cornucopia`: domain tables, append-only journal, checkpoints, outbox, audit, RPC functions. |

The agent never depends on the frontend: events submitted through the API are journaled first, and the worker processes them from the journal.

## 2. Repository structure (planned)

```
Cornucopia/
├─ backend/
│  ├─ pyproject.toml
│  ├─ cornucopia/
│  │  ├─ config.py              # pydantic-settings; transport selection
│  │  ├─ api/                   # FastAPI app, routers, auth, schemas (DTOs)
│  │  ├─ domain/                # pure: entities, units, events, plans (no I/O)
│  │  ├─ compiler/              # requirements, allocation, capacity, feasibility, substitutions
│  │  ├─ depgraph/              # NetworkX graph build + impact analysis
│  │  ├─ optimizer/             # CP-SAT model, lexicographic solve, diagnosis
│  │  ├─ approvals/             # fingerprints, lifecycle rules
│  │  ├─ agent/                 # LangGraph state, nodes, routing, supervisor, checkpointer
│  │  ├─ persistence/
│  │  │  ├─ transport.py        # SupabaseTransport protocol
│  │  │  ├─ gateway.py          # production: Sprites gateway
│  │  │  ├─ direct.py           # local dev only: direct REST with .env key
│  │  │  ├─ memory.py           # tests: in-memory PostgREST subset
│  │  │  ├─ models.py           # SQLAlchemy models (schema source of truth)
│  │  │  └─ repositories/       # repository interfaces + Supabase implementations
│  │  └─ worker.py              # supervisor entrypoint
│  └─ tests/
├─ db/
│  ├─ alembic.ini, alembic/     # Alembic env + revisions (generation + drift check)
│  └─ sql/                      # hand-written grants, RLS and plpgsql RPC functions
├─ supabase/
│  ├─ config.toml               # declares only the API schema exposure
│  └─ migrations/               # GENERATED SQL, applied by `supabase db push`
├─ contracts/openapi.json       # shared API contract (frontend types generated from it)
├─ frontend/                    # Next.js (App Router), TypeScript strict, Tailwind, React Flow, Recharts
├─ scripts/
│  ├─ deploy_sprite.sh          # documented sprite CLI steps only
│  └─ apply_migrations.sh
├─ docs/
└─ README.md ARCHITECTURE.md IMPLEMENTATION_PLAN.md DEPLOYMENT.md CONNECTOR_SETUP.md
   DATABASE_SCHEMA.md AGENT_WORKFLOW.md OPTIMIZATION_ENGINE.md SECURITY.md
   DEMO_SCRIPT.md TESTING.md CHANGELOG.md JOURNAL.md
```

Layering rule: `domain`, `compiler`, `depgraph`, `optimizer`, `approvals` import nothing from `api`, `agent`, or `persistence`. The agent calls them through explicit tool functions.

## 3. Persistence through the connector

- Base URL: `https://api.sprites.dev/v1/gateway/supabase/<connection_id>` (configured as `SUPABASE_GATEWAY_URL`). Requests carry `Accept-Profile`/`Content-Profile: cornucopia`, no Authorization header.
- Reads: PostgREST `GET /rest/v1/<table>?select=...` or read RPCs (`get_operational_snapshot`).
- Writes that touch more than one row or need invariants: RPCs (`POST /rest/v1/rpc/<fn>`), each one plpgsql function = one transaction.
- No DDL through the connector. Schema changes ship as versioned SQL applied out of band.

Planned RPCs: `ingest_event`, `claim_next_event`, `renew_lease`, `complete_event`, `put_checkpoint`, `get_operational_snapshot`, `record_optimization_run`, `propose_plan`, `decide_approval`, `commit_approved_plan`, `expire_stale_approvals`, `claim_outbox`, `demo_reset` (demo org only).

## 4. Data model outline

All tables: `uuid` PK (`gen_random_uuid()`), `created_at timestamptz default now()` (UTC), `updated_at` where mutable. Quantities stored as `numeric` + `unit` text checked against an enum; canonical internal unit per dimension (grams for mass, millilitres for volume, `each`, `portion`).

Core entities follow the master prompt list. Notable integrity rules:
- `operational_events`: append-only (trigger rejects UPDATE of payload / DELETE), unique `(organization_id, idempotency_key)`, `status` transitions only through RPCs.
- `operational_state_version` counter per organization, bumped by any committed change; plans record the version they were computed against.
- `plan_versions` immutable once proposed; `approval_requests` bind `(plan_id, plan_version, fingerprint, execution_id, expires_at)`.
- `audit_records` and `outbox_messages` written in the same transaction as the change they describe.
- `agent_checkpoints` keyed by `(thread_id, checkpoint_ns, checkpoint_id)` plus pending writes, matching LangGraph's saver contract.

Full DDL lands in `DATABASE_SCHEMA.md` in Phase 1/2.

## 5. Agent execution model

1. API `POST /events` calls `ingest_event` (idempotent). Returns event id.
2. Worker loop: `claim_next_event(worker_id, lease=60s)` (SKIP LOCKED). While processing it refreshes the lease and a Sprites task hold (`expire: 5m`, refreshed every 60 s).
3. LangGraph runs with `thread_id = event correlation id`, checkpoint after each node through `SupabaseCheckpointSaver`.
4. On restart the supervisor looks for executions with expired leases and resumes them from the latest checkpoint. Side-effecting nodes are idempotent (keyed by execution id + node).
5. The graph stops at `request_approval`. Commits happen only when an approver decides through the API and `commit_approved_plan` succeeds.

## 6. Security model

- The Supabase key exists only in the connector (production) and the gitignored `.env` (local dev).
- The Sprite holds only an app token-signing secret (stored on the Sprite disk outside the repo, never served).
- Browser → Next.js server → Sprite API. CORS restricted to the frontend origin. Every route requires a role; approvals require `approver`.
- Approval state is never taken from the client: the server re-reads the plan, fingerprint, and state version.
