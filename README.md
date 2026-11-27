# CORNUCOPIA

> When resources change, the feast goes on.

CORNUCOPIA is an autonomous resource compiler built for Fly.io Hacksgiving 2026. It turns unpredictable donations, inventory, preparation capacity, dietary restrictions and delivery commitments into executable plans. When reality changes, its agent works out what is affected, computes a replacement plan, and asks a human to approve it before anything is committed. We call this **reality recompilation**.

- The agent runs inside a **Fly.io Sprite**.
- Data lives in **Supabase** and is reached only through the official **Sprites Supabase Database connector**. The Supabase key never touches the Sprite.
- The web UI is a separate **Next.js** app hosted on **Vercel**.
- No paid LLM is involved. Decisions come from deterministic code, NetworkX, OR-Tools CP-SAT and LangGraph.

## Status

| Phase | Scope | State |
|---|---|---|
| 0 | Platform discovery, architecture | Done |
| 1 | Foundation, Supabase connector, migrations, frontend link | Done |
| 2 | Domain model, units, operational event journal, resource UI | Done, awaiting approval (branch `phase-2-domain-events`) |
| 3 to 9 | Compiler, optimizer, agent, approvals, command center, resilience, demo | Planned (`IMPLEMENTATION_PLAN.md`) |

## Repository map

| Path | What it is |
|---|---|
| `backend/` | FastAPI service and the agent runtime (Python 3.12+, managed with `uv`) |
| `frontend/` | Next.js command center (TypeScript strict, Tailwind) |
| `supabase/migrations/` | Generated SQL migrations, applied with the Supabase CLI |
| `db/` | Alembic config and hand-written SQL (grants, RLS, RPC functions) |
| `contracts/openapi.json` | Shared API contract. Frontend types are generated from it |
| `scripts/` | Deploy, migration generation and verification scripts |
| `docs/` | Phase reports and screenshots |

## Quick start (local)

```bash
cd backend && uv sync && uv run pytest
```

```bash
cd frontend && npm install && npm run build
```

Run the frontend against the Sprite-hosted API through a port forward:

```bash
sprite proxy -s cornucopia 18000:8000
```

```bash
cd frontend && npx next start -p 3100
```

`frontend/.env.local` (gitignored) needs `CORNUCOPIA_API_URL=http://localhost:18000` and `CORNUCOPIA_API_TOKEN`. See `DEPLOYMENT.md`.

## Documentation

`ARCHITECTURE.md`, `IMPLEMENTATION_PLAN.md`, `DEPLOYMENT.md`, `CONNECTOR_SETUP.md`, `DATABASE_SCHEMA.md`, `SECURITY.md`, `TESTING.md`, `CHANGELOG.md`, `JOURNAL.md`. The agent, optimizer and demo documents arrive with their phases.
