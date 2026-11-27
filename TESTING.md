# Testing

## Backend

```bash
cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy cornucopia
```

Unit tests use `InMemorySupabaseClient` and `httpx.MockTransport` to check the exact wire format: gateway requests carry no credentials and do send `Accept-Profile`/`Content-Profile`. Production integrations are verified separately against the real services (below). Mocks are never substituted for them.

Schema drift check (models vs migrations), against the scratch local Postgres:

```bash
cd backend && uv run alembic -c ../db/alembic.ini upgrade head && uv run alembic -c ../db/alembic.ini check
```

Migration reproducibility (fresh databases, identical `pg_dump -s`):

```bash
PGHOST=localhost PGPORT=54329 PGUSER=postgres scripts/verify_migrations_local.sh
```

## Live integration (real Sprite, real connector, real Supabase)

```bash
sprite exec -s cornucopia -- bash -c 'T=$(grep ^CORNUCOPIA_API_TOKEN= ~/.config/cornucopia/cornucopia.env | cut -d= -f2); curl -s localhost:8000/health/db -H "Authorization: Bearer $T"'
```

## Frontend

```bash
cd frontend && npx tsc --noEmit && npm run lint && npm run build
```

End to end (frontend served by `next start -p 3100`, API reached via `sprite proxy 18000:8000`):

```bash
cd frontend && npx playwright test --trace off
```

Runs on a desktop and a mobile (Pixel 7) profile.

## Phase 1 results (2026-11-27)

| Check | Result |
|---|---|
| pytest | 15 passed |
| ruff check / format, mypy --strict | clean |
| alembic check | no drift |
| migration reproducibility | identical schema from two fresh DBs |
| live: health_check RPC via gateway from Sprite | 200 |
| live: insert + read probe via Sprite API → connector | ok (`source=gateway`) |
| Playwright (desktop + mobile) | 8 passed |
| bundle secret scan (`.next/static`) | 0 hits for token, `sb_secret`, `supabase.co`, `api.sprites.dev` |
