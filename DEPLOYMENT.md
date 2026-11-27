# Deployment

Every command here was run against the real platform on 2026-11-27 unless marked *planned*.

## Prerequisites

| Tool | Install | Used for |
|---|---|---|
| `sprite` CLI | see [CLI installation](https://docs.fly.io/sprites/cli/installation.md); `sprite login` | Sprite deploys |
| Supabase CLI ≥ 3.4 | `brew install supabase/tap/supabase`; `supabase login` | schema migrations and API config |
| `uv` | `brew install uv` | Python environments |
| Node 20+ / npm | | frontend |

## 1. Database (Supabase CLI)

The Sprites connector exposes PostgREST only, so schema changes are applied with the Supabase CLI from a developer machine.

```bash
supabase link --project-ref <project-ref> --yes
```

```bash
supabase db push --remote --dry-run
```

```bash
supabase db push --remote --yes
```

Expose the `cornucopia` schema to PostgREST. `supabase/config.toml` declares only `[api]`, and `config push` leaves undeclared remote settings unchanged.

```bash
supabase config diff
```

```bash
supabase config push --yes
```

With CLI 3.4 and a `supabase login` session, `db push --remote` did not need the database password.

### Changing the schema

1. Edit `backend/cornucopia/persistence/models.py` and/or `db/sql/*.sql`.
2. Add an Alembic revision (autogenerate against the scratch local Postgres named in `db/alembic.ini`):

```bash
cd backend && uv run alembic -c ../db/alembic.ini revision --autogenerate --rev-id 0002 -m "<slug>"
```

3. Render it to a Supabase migration:

```bash
scripts/gen_migration.sh 0001 0002 <UTC timestamp YYYYMMDDHHMMSS> <slug>
```

4. Prove it reproduces from empty (local Postgres with `anon`, `authenticated`, `service_role` roles):

```bash
PGHOST=localhost PGPORT=54329 PGUSER=postgres scripts/verify_migrations_local.sh
```

5. `supabase db push --remote`.

## 2. Backend on the Sprite

```bash
SPRITE=cornucopia SUPABASE_GATEWAY_URL=https://api.sprites.dev/v1/gateway/supabase/<connection-id> scripts/deploy_sprite.sh
```

The script also (re)creates the `cornucopia-worker` service: the autonomous agent, `python -m cornucopia.worker`. It runs independently of the API and has no HTTP port. The Sprite runtime restarts it on crash and after a cold boot, and unfinished executions are resumed from Supabase through expired leases.

The script packages `backend/` into a tarball, which excludes `.env` and virtualenvs. It uploads with `sprite file push`, runs `uv sync --frozen --no-dev` in a new release directory, and points `current` at that release. It then (re)creates the `cornucopia-api` Sprite service with `sprite-env services create ... --http-port 8000`, and smoke-tests `/health` inside the Sprite.

On first deploy the script generates the API bearer token on the Sprite in `/home/sprite/.config/cornucopia/cornucopia.env` (mode 600). The Supabase key is never sent to the Sprite.

Check the service:

```bash
sprite exec -s cornucopia -- sprite-env services get cornucopia-api
```

```bash
sprite exec -s cornucopia -- tail -n 50 /.sprite/logs/services/cornucopia-api.log
```

```bash
sprite exec -s cornucopia -- tail -n 50 /.sprite/logs/services/cornucopia-worker.log
```

## Sample data (development / demonstration organizations only)

Seed the labelled Thanksgiving sample operation through the API. All of it is created through the same validated, audited endpoints as the UI, and the script is idempotent:

```bash
CORNUCOPIA_API_URL=http://localhost:18000 CORNUCOPIA_API_TOKEN=<token> uv run --project backend python scripts/seed_sample.py --label "[sample] "
```

## Operators

Operator accounts live in Supabase as argon2id hashes. Create them on the Sprite. With `--generate-password`, a strong password is printed exactly once.

```bash
sprite exec -s cornucopia -- bash -c 'cd /home/sprite/cornucopia/current/backend && .venv/bin/python -m cornucopia.admin create-operator --username raj --name Raj --role admin --generate-password'
```

Roles: `viewer` (read), `operator` (report events, edit resources, run the optimizer), `approver` (also decide approvals), `admin`.

## 3. Public API URL

The API requires the service token on every route except `/health`, and an operator session on operational routes. With that in place the Sprite URL can be public so a hosted frontend can reach it:

```bash
sprite config update -s cornucopia --url-auth public
```

Health checks:

| URL | Meaning |
|---|---|
| `GET /health` | API process liveness (no auth) |
| `GET /health/db` | Supabase reachable through the connector (service token) |
| `GET /health/agent` | an agent worker heartbeat within the last 90 s (service token) |

## 4. Frontend on Vercel

Live at **https://cornucopia-delta.vercel.app** (project `cornucopia`, deployed with `vercel deploy --prod` from `frontend/`). It talks to the public Sprite URL server-side.

The frontend is a standard Next.js 16 app in `frontend/`. It needs two server-side environment variables, never `NEXT_PUBLIC_`:

| Variable | Value |
|---|---|
| `CORNUCOPIA_API_URL` | `https://cornucopia-b6zug.sprites.app` (from `sprite info`) |
| `CORNUCOPIA_API_TOKEN` | the `CORNUCOPIA_API_TOKEN` value in the Sprite's `/home/sprite/.config/cornucopia/cornucopia.env` |

These steps need your Vercel account:

```bash
npm i -g vercel
```

```bash
cd frontend && vercel link
```

```bash
vercel env add CORNUCOPIA_API_URL production
```

```bash
vercel env add CORNUCOPIA_API_TOKEN production
```

```bash
vercel --prod
```

Alternatively, import the GitHub repo in the Vercel dashboard with Root Directory `frontend` and set the same two variables.

## 5. Restart drills (verified on the Sprite)

| Drill | Command | Expected |
|---|---|---|
| Kill the agent mid-execution | `sprite exec -s cornucopia -- sprite-env services signal cornucopia-worker KILL` | The runtime restarts the worker. After the lease expires (≤ 60 s) the same execution resumes with `attempt + 1` from its last checkpoint. |
| Restart the API | `sprite exec -s cornucopia -- sprite-env services restart cornucopia-api` | Requests resume. Sessions remain valid because they are signed tokens. |
| Graceful worker stop | `sprite-env services stop cornucopia-worker` | SIGTERM: the worker finishes its current execution, records `stopped`, exits. |
