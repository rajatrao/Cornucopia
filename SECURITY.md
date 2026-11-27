# Security

## Secrets and where they live

| Secret | Location | Never in |
|---|---|---|
| Supabase `sb_secret_` key | Sprites connector (encrypted, server side); developer's gitignored `.env` for local direct mode | git, the Sprite, the frontend, logs |
| Supabase DB password | not stored (CLI uses `supabase login`) | anywhere in the repo |
| API bearer token | Sprite `/home/sprite/.config/cornucopia/cornucopia.env` (mode 600); Vercel env var; developer's gitignored `frontend/.env.local` | git, browser bundle |

Before every commit we scan staged content and history for key material:

```bash
git grep -n -I -E 'sb_secret_[A-Za-z0-9_]{8,}|CORNUCOPIA_API_TOKEN=[0-9a-f]{16,}' $(git rev-list --all) -- . || echo clean
```

## Trust boundaries

1. **Browser → Next.js server.** The browser only talks to Next.js. The API token sits in server-only modules (`import "server-only"`) and non-`NEXT_PUBLIC_` env vars. The build is scanned for credentials and backend hosts, and a Playwright test asserts that no response sent to the browser contains them.
2. **Next.js → Sprite API.** Every non-liveness route requires `Authorization: Bearer <token>`, compared in constant time. Production refuses to start without a token. Per-operator auth and roles come in Phase 6/8.
3. **Sprite → Supabase.** Only via the connector gateway. The app sends no credentials, the gateway authenticates the Sprite by Fly.io request identity, and calls from outside a Sprite get 401. `direct` transport is refused when `CORNUCOPIA_ENV=production`.
4. **Database.** All application writes go through `SECURITY DEFINER` RPCs (`write_resource`, `ingest_event`). `service_role` has no direct INSERT/UPDATE/DELETE on domain tables, and the event journal and audit log are append-only. Every write sets the acting operator for the transaction, and row triggers write an audit record in the same transaction. RLS on, no policies. Privileges revoked from `public`, `anon` and `authenticated` on the schema, tables and functions. Functions pin `search_path=''`.

## Input validation

Pydantic models with `extra="forbid"` and length limits on the API, plus independent validation in the Next.js route handlers. Database CHECK constraints are the last line.

## Open items

- Rotate the Supabase secret key (it was shared in chat during setup) and update the connector.
- Restrict the connector access policy from allow-all to name prefix `cornucopia`.
- Switch the Sprite URL to public only after operator auth (Phase 8).
- Phase 2 actor identity is asserted by the trusted frontend server (`X-Cornucopia-Actor`, validated). Per-operator sign-in replaces it in Phase 6/8.
