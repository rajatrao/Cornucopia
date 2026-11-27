# CORNUCOPIA: Phase 0 Discovery Report

Date: 2026-11-27 (UTC). Author: Claude (coding agent), for Raj.

Status: **Awaiting approval.** Nothing beyond `.gitignore`, a gitignored `.env`, and these docs has been created. No commits yet.

---

## 1. Repository inspection

| Item | Finding |
|---|---|
| Path | `/Users/rajat/Downloads/hackathon/Cornucopia` |
| Git | Initialized, branch `main`, **no commits**. Remote `origin = git@github.com:rajatrao/Cornucopia.git` |
| Existing code | None. Only `CORNUCOPIA_MASTER_PROMPT.md` (no secrets in it; verified by grep). |
| Working implementation to preserve | None. Greenfield. |
| Added in Phase 0 | `.gitignore` (ignores `.env`, `.env.*` except `.env.example`), `.env` (mode 600, holds Supabase URL + secret key for local dev only), `docs/*` |

Local toolchain (Raj's Mac): `sprite` CLI 2026-11-03 (authenticated, org `rajat-752`), Python 3.13.12, Node 26.9.0, npm. **Not installed:** `flyctl`, `uv`, Supabase CLI.

## 2. Existing Fly.io resources (verified live)

| Resource | State |
|---|---|
| Sprite `cornucopia` | Exists, org `rajat-752`, URL `https://cornucopia-b6zug.sprites.app`, URL auth `sprite` (org-only). Ubuntu 26.04, Python 3.13.17, Node 24, `uv`, git, 8 vCPU, ~15 GiB reported memory, 99 GB disk. |
| Supabase Database connector | Exists. id `4mTfP1SN5GkJtGuDrHCE-A`, provider `supabase`, base `https://relcvfkydpafyaqrvalv.supabase.co`, **access policy `allow_all: true`** (see risk R2). |

## 3. Verified platform facts

Sources: [Connectors](https://docs.fly.io/sprites/concepts/connectors.md), [Sprites ecosystem catalog, Supabase Database entry](https://fly.io/sprites/ecosystem/), [Services](https://docs.fly.io/sprites/concepts/services.md), [Lifecycle](https://docs.fly.io/sprites/concepts/lifecycle.md), [Networking](https://docs.fly.io/sprites/concepts/networking.md), [Keeping a Sprite Running](https://docs.fly.io/sprites/keeping-sprites-running.md), [Working with Sprites](https://docs.fly.io/sprites/working-with-sprites.md), plus live probes.

### 3.1 Supabase Database connector

| Question | Verified answer | How verified |
|---|---|---|
| Authentication | No `Authorization` header from the Sprite. The gateway identifies the calling Sprite from Fly.io request-signature identity headers, checks the access policy, and attaches the stored `sb_secret_` key server side. | Docs + probe: same URL from laptop returns `401 {"error":"authentication failed"}`; from the Sprite returns 200. |
| Gateway URL | `https://api.sprites.dev/v1/gateway/supabase/4mTfP1SN5GkJtGuDrHCE-A/<path>` (path forwarded to the project). Discoverable at `GET https://api.sprites.dev/v1/gateway/list` from inside the Sprite. | Probe |
| Credential | Modern `sb_secret_` key only, hosted `https://<ref>.supabase.co` only. Uses `service_role`, **bypasses RLS**. Key never lands on the Sprite. Project URL fixed after creation. | Catalog entry |
| Supported surface | **REST database only** (PostgREST): tables, views, RPC functions. Auth, Storage, Realtime, Edge Functions, project management are excluded. | Catalog + probe: `/auth/v1/settings` returns `403 endpoint is not supported by the Supabase Database connector` |
| REST | `GET /rest/v1/` returns 200 OpenAPI (PostgREST 14.18). | Probe |
| RPC | `POST /rest/v1/rpc/<fn>` is forwarded to PostgREST (unknown fn returned `PGRST202`, i.e. reached PostgREST). | Probe |
| Custom schema | `Accept-Profile: cornucopia` reaches PostgREST but returns `PGRST106: Only public, graphql_public exposed`. A dedicated schema works only after it is added to **Exposed schemas** in Supabase project API settings. | Probe |
| Direct Postgres | **Not provided.** No DDL path through the connector. Migrations must be applied outside the Sprite (see §5). | Docs |
| Access restrictions | Deny-by-default policy by name prefix and/or labels, or allow-all. Endpoint allow/block lists via API only. | Docs |
| Env vars injected into Sprite | **None documented.** The gateway URL is the integration point; I will configure it as app config (`SUPABASE_GATEWAY_URL`), not invent platform env vars. | Docs |

### 3.2 Sprite runtime

| Topic | Verified behavior | Design consequence |
|---|---|---|
| Lifecycle | active → (≈30 s idle) warm (suspended, memory kept, 100–500 ms wake) → cold (memory dropped, 1–2 s wake). Open TCP connections drop on any pause. | Never trust in-memory state. All work is reconstructed from Supabase. HTTP client must retry on reconnect. |
| Persistence | Disk persists (continuously synced to object storage); processes and RAM do not survive cold. | Code + venv installed once on disk; state lives in Supabase, not on disk. |
| Services | `sprite-env services create <name> --cmd ... --args ... --env ... --dir ... --needs ... --http-port <p>`. Runtime starts at boot, restarts on crash, restarts after cold wake. Only one service may own the HTTP port. Logs at `/.sprite/logs/services/<name>.log`. No systemd. | `cornucopia-api` service with `--http-port 8000`; `cornucopia-worker` service with `--needs cornucopia-api`. |
| Staying awake | Services don't prevent pausing. Tasks API on `/.sprite/api.sock` (`PUT /v1/tasks/<name> {"expire":"5m"}`, max 1 h, heartbeat pattern). | Worker holds a task only while an execution is in flight, releases after. |
| HTTP ingress | One URL, HTTPS, routes to the `--http-port` service (default 8080), wakes on request. Auth `sprite` (org members/org token) or `public`. | Browser-facing frontend cannot present Fly org tokens, so URL becomes `public` and **FastAPI enforces its own operator auth**. |
| Egress | Unrestricted by default; optional DNS allowlist policy. | Optional hardening in Phase 8: allow only `api.sprites.dev` + package hosts. |
| Deploy procedure | No image/Dockerfile deploy for Sprites. Code goes in by `git clone`/`sprite file push`/`sprite exec`, deps installed on the persistent disk, processes registered as services. Checkpoints (`sprite checkpoint create`) for rollback. | `scripts/deploy_sprite.sh` doing exactly those documented steps. |

## 4. Proposed architecture

```
Browser
  │ HTTPS (operator session cookie)
  ▼
Next.js (separate host)  ── server-side route handlers only (BFF) ──┐
                                                                     │ HTTPS + operator bearer token
                                                                     ▼
Fly.io Sprite "cornucopia"  (https://cornucopia-b6zug.sprites.app, URL auth public, app auth enforced)
  ├─ service cornucopia-api   (uvicorn FastAPI, :8000, --http-port)
  │     auth, validation, CRUD, event intake, approvals, read models
  └─ service cornucopia-worker (agent supervisor, --needs api)
        lease-based event claiming → LangGraph graph
          ├─ domain/compiler  (pure Python: units, requirements, allocation, feasibility)
          ├─ graph/deps       (NetworkX impact analysis)
          ├─ optimizer        (OR-Tools CP-SAT, lexicographic)
          ├─ approvals        (fingerprints, lifecycle)
          └─ SupabaseCheckpointSaver (custom LangGraph BaseCheckpointSaver over REST/RPC)
                     │  all DB I/O via repository interfaces → SupabaseRestClient
                     ▼
Sprites gateway  https://api.sprites.dev/v1/gateway/supabase/<conn>/rest/v1/...   (injects sb_secret_)
                     ▼
Supabase Postgres, schema `cornucopia` (tables + transactional RPC functions)
```

Key decisions (details in `ARCHITECTURE.md`):

1. **One codebase, two Sprite services.** API and worker are separate processes so the agent runs independently of HTTP traffic and the frontend. Both are Sprite services, so both come back after a cold boot.
2. **Transport adapter with three implementations** behind one `SupabaseTransport` interface: `GatewayTransport` (production; no key on the Sprite), `DirectRestTransport` (laptop dev only, reads `.env`; refuses to start when `SPRITE`-mode is set), and `InMemoryTransport` (tests). Production never silently falls back to a mock.
3. **Every multi-row state change is a Postgres RPC** (`plpgsql`, single transaction): event ingest with idempotency, work claiming with `FOR UPDATE SKIP LOCKED` leases, checkpoint put, plan proposal, approval decision, and `commit_approved_plan`. REST is used for reads and simple single-row writes.
4. **Migrations:** SQLAlchemy models are the source of truth; Alembic in *offline mode* (`alembic upgrade --sql`) generates versioned SQL into `db/migrations/*.sql`; hand-written RPC functions live alongside. Applied outside the Sprite (connector has no DDL). Alembic's `alembic_version` table tracks what is applied.
5. **Optimizer independent of LangGraph.** `optimizer.solve(snapshot, config) -> Result` is a pure function with fixed seed, `num_workers=1` for determinism, and a time limit; the graph only calls it as a tool.
6. **Approvals:** plan fingerprint = SHA-256 of canonical JSON of the plan's allocations + the operational state version it was computed against. Commit RPC re-checks fingerprint, state version, approval status, expiry, and operator role inside one transaction.
7. **Simulations** run the same compiler/optimizer on an in-memory copy of a state snapshot and persist only to `simulation_*` tables; they never call commit RPCs.
8. **No LLM** anywhere in the execution path. A disabled-by-default hook may come later.
9. **Auth:** operators stored in `cornucopia.operators` with argon2 password hashes and roles (`viewer`, `operator`, `approver`). FastAPI issues short-lived signed tokens; Next.js keeps them in HttpOnly cookies and calls the API server side. The browser never sees Supabase or gateway details.

## 5. Deployment assumptions (to confirm)

| # | Assumption | Needs from Raj |
|---|---|---|
| A1 | Tables live in a dedicated `cornucopia` schema. | Add `cornucopia` to Supabase **Project Settings → API → Exposed schemas** (I'll give exact steps in Phase 1). Fallback: `public` with `cn_` table prefix. |
| A2 | Migrations applied with the **Supabase CLI** (`supabase db push`) from the Mac, which needs `brew install supabase/tap/supabase`, `supabase login`, and the database password. Fallback: paste generated SQL into the Supabase SQL Editor. | Pick one. |
| A3 | Next.js frontend hosted on **Fly.io Machines** as a separate app (`fly launch`), keeping the whole story on Fly. Needs `flyctl` installed and logged in. Alternative: Vercel. | Pick one. |
| A4 | Sprite URL switched to `public` in Phase 8 only, after app-level auth is live. Until then, I test through `sprite proxy`. | OK? |
| A5 | Connector policy restricted from `allow_all` to name prefix `cornucopia`. | Raj changes it in the dashboard (Sprites → Connectors → the Supabase connection → access settings), or approves me doing it via API. |
| A6 | Python 3.13 on the Sprite (meets 3.12+); `uv` for env management on both sides. | none |

## 6. Dependency inventory (current versions, checked on PyPI/npm today)

Backend: fastapi 0.165, uvicorn 0.54, pydantic 2.14, httpx 0.29, sqlalchemy 2.1, alembic 1.20, langgraph 1.2 (+ langgraph-checkpoint 4.3 base classes only), ortools 9.15 (cp313 wheels available), networkx 3.7, argon2-cffi, pyjwt. Dev: pytest 9.2, ruff 0.17, mypy 2.4, respx (HTTP mocking).

Frontend: next 16.4, react 19.3, typescript (strict), tailwindcss 4.3, @xyflow/react (React Flow) 13, recharts 3.11, zod, @playwright/test 1.65. Component primitives: Radix UI for accessibility.

No paid inference SDKs.

## 7. Risk register

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Supabase secret key was pasted in chat. | High (already happened) | High once repo is public | Key is only in gitignored `.env` and the connector. **Rotate it** in Supabase before going public, then update the connector and `.env`. |
| R2 | Connector policy is `allow_all`; any Sprite in the org gets RLS-bypassing DB access. | Medium | High | Restrict to name prefix `cornucopia` (A5). |
| R3 | No direct SQL through the connector; DDL must be applied out of band. | Certain | Medium | Generated, versioned SQL + Supabase CLI or SQL Editor; Phase 1 verifies reproducibility from empty schema. |
| R4 | REST calls are not transactional across requests. | Certain | High | All consequential mutations are single RPC calls in plpgsql transactions. |
| R5 | Cold boot kills in-flight agent work; TCP drops on warm pause. | High | Medium | Durable leases with expiry, idempotency keys, checkpoint after every node, Tasks API hold during executions, retrying HTTP client. |
| R6 | Gateway latency/rate limits undocumented. | Medium | Medium | Batch reads (one snapshot RPC), measure in Phase 1, bounded retries with backoff. |
| R7 | LangGraph checkpointer API changes (v1.2 / checkpoint 4.x). | Medium | Medium | Pin versions; contract tests against `BaseCheckpointSaver` using the in-memory transport. |
| R8 | CP-SAT nondeterminism with multiple workers. | Medium | Medium | `num_search_workers=1`, fixed `random_seed`, integer-scaled quantities; determinism test. |
| R9 | Public Sprite URL exposes API. | Certain after A4 | High | App auth on every route, role checks, rate limiting, CORS locked to frontend origin, no secrets served. |
| R10 | Ambiguous unit conversions (mass vs volume). | Medium | Medium | Conversions only within dimension; cross-dimension only with ingredient-specific density; otherwise reject. |
| R11 | Newer toolchain majors (Next 16, TS 7, Tailwind 4). | Medium | Low | Pin versions; if a blocker appears, drop to prior major and note it. |
| R12 | Single shared Supabase project for dev and prod. | Medium | Medium | Schema-level separation; simulations isolated in tables; `demo_reset` RPC only on labeled demo org. |

## 8. Phase plan

See `IMPLEMENTATION_PLAN.md` for per-phase deliverables, tests, and acceptance checks. Summary:

| Phase | Deliverable | Key verification |
|---|---|---|
| 1 | Monorepo (`backend/`, `frontend/`, `db/`), FastAPI health, config, transports, repositories, first migration, Next.js shell calling `/health` | Insert + read a row **from the Sprite through the gateway**; migrations rebuild an empty schema; secret scan of frontend bundle |
| 2 | Domain model, unit engine, CRUD, event journal with idempotency | Unit tests, duplicate-event test, UI CRUD |
| 3 | Deterministic compiler + NetworkX dependency graph + baseline plan | Shortage/infeasibility/substitution tests |
| 4 | CP-SAT optimizer, lexicographic objectives, infeasibility diagnosis | Feasible/infeasible fixtures, determinism, timing on demo data |
| 5 | LangGraph agent with custom Supabase checkpointer, leases, retries | Kill worker mid-run → resumes without duplicate effects |
| 6 | Approval lifecycle + transactional `commit_approved_plan` RPC | Stale/duplicate/unauthorized/concurrent approval tests |
| 7 | Command-center UI (7 screens), React Flow recompilation view | Playwright end-to-end |
| 8 | Sprite services, heartbeat, startup recovery, frontend deploy | Restart drills on the real Sprite |
| 9 | Rice-cancellation demo + insufficient-resources escalation demo, docs | Scripted reproducible run |

## 9. Acceptance checklist for Phase 0

- [x] Repository inspected; greenfield confirmed.
- [x] Current Sprite platform capabilities documented from official docs.
- [x] Connector auth, REST and RPC support, restrictions verified by live probe from the Sprite.
- [x] No fabricated CLI commands, env vars, or endpoints (each one above is cited or probed).
- [x] Secrets isolated (`.env` gitignored, mode 600).
- [ ] Architecture approved by Raj.
- [ ] Assumptions A1–A5 confirmed.

**Recommendation:** proceed to Phase 1 once A1–A5 are answered.
