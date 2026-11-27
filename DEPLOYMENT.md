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

The script packages `backend/` into a tarball, which excludes `.env` and virtualenvs. It uploads with `sprite file push`, runs `uv sync --frozen --no-dev` in a new release directory, and points `current` at that release. It then (re)creates the `cornucopia-api` Sprite service with `sprite-env services create ... --http-port 8000`, and smoke-tests `/health` inside the Sprite.

On first deploy the script generates the API bearer token on the Sprite in `/home/sprite/.config/cornucopia/cornucopia.env` (mode 600). The Supabase key is never sent to the Sprite.

Check the service:

```bash
sprite exec -s cornucopia -- sprite-env services get cornucopia-api
```

```bash
sprite exec -s cornucopia -- tail -n 50 /.sprite/logs/services/cornucopia-api.log
```

## 3. Frontend on Vercel (*planned for Phase 8*)

The frontend needs two server-side environment variables (never `NEXT_PUBLIC_`):

| Variable | Value |
|---|---|
| `CORNUCOPIA_API_URL` | the Sprite URL from `sprite info` |
| `CORNUCOPIA_API_TOKEN` | the token in the Sprite's `cornucopia.env` |

The Sprite URL is org-private by default. It will be switched to public with `sprite config update --url-auth public` only after per-operator auth lands (Phase 8). Until then the frontend runs locally against `sprite proxy`.
