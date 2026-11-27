# Security

## Secrets and where they live

| Secret | Location | Never in |
|---|---|---|
| Supabase `sb_secret_` key | Sprites connector (encrypted, server side); developer's gitignored `.env` for local direct mode | git, the Sprite, the frontend, logs |
| Supabase DB password | not stored (CLI uses `supabase login`) | anywhere in the repo |
| Session signing secret (`CORNUCOPIA_SESSION_SECRET`) | Sprite `cornucopia.env` (mode 600), generated on first deploy | git, frontend, logs |
| Operator passwords | argon2id hashes in `operators`; generated passwords are shown once (stored locally only in gitignored `.env.operators` / `frontend/.env.e2e`) | git, logs |
| API bearer token | Sprite `/home/sprite/.config/cornucopia/cornucopia.env` (mode 600); Vercel env var; developer's gitignored `frontend/.env.local` | git, browser bundle |

Before every commit we scan staged content and history for key material:

```bash
git grep -n -I -E 'sb_secret_[A-Za-z0-9_]{8,}|CORNUCOPIA_API_TOKEN=[0-9a-f]{16,}' $(git rev-list --all) -- . || echo clean
```

## Trust boundaries

1. **Browser → Next.js server.** The browser only talks to Next.js. The API token sits in server-only modules (`import "server-only"`) and non-`NEXT_PUBLIC_` env vars. The build is scanned for credentials and backend hosts, and a Playwright test asserts that no response sent to the browser contains them.
2. **Next.js → Sprite API.** Two layers. Every request carries the service bearer token (constant-time compare), and every operational route also requires a signed operator session: an HS256 JWT issued by the API at sign-in, stored by Next.js in an HttpOnly, SameSite=Lax (Secure in production) cookie, and forwarded server-side as `X-Cornucopia-Session`. The API verifies signature, expiry and organization, and that the operator is still active (cached for 30 s). The acting operator for audits is derived from the session, never from client input. Roles: viewer < operator (report events, edit resources, run the optimizer) < approver (decide approvals) < admin.
3. **Sprite → Supabase.** Only via the connector gateway. The app sends no credentials, the gateway authenticates the Sprite by Fly.io request identity, and calls from outside a Sprite get 401. `direct` transport is refused when `CORNUCOPIA_ENV=production`.
4. **Database.** All application writes go through `SECURITY DEFINER` RPCs (`write_resource`, `ingest_event`). `service_role` has no direct INSERT/UPDATE/DELETE on domain tables, and the event journal and audit log are append-only. Every write sets the acting operator for the transaction, and row triggers write an audit record in the same transaction. RLS on, no policies. Privileges revoked from `public`, `anon` and `authenticated` on the schema, tables and functions. Functions pin `search_path=''`.

## Approvals

- A plan is never authorised by being feasible. Commits happen only through `commit_approved_plan`, which re-checks in one transaction: the approval status and expiry; an accepted decision by an active approver; the plan fingerprint (request, plan version and decision must all match); that the operational state version is unchanged since the plan was computed; and the lease of the executing agent.
- Every decision attempt is recorded, including refusals (unauthorized, duplicate, stale, expired, fingerprint mismatch, unconfirmed).
- A database trigger stops `planned_meals` and the committed plan from being changed by anything except an approved commit.

## Input validation

Pydantic models with `extra="forbid"` and length limits on the API, plus independent validation in the Next.js route handlers. Database CHECK constraints are the last line.

## Open items

- Rotate the Supabase secret key (it was shared in chat during setup) and update the connector.
- Restrict the connector access policy from allow-all to name prefix `cornucopia`.
- The Sprite URL is public (Phase 8). Only `/health` is unauthenticated; everything else needs the service token, and operational routes also need an operator session.
- No rate limiting or lockout on sign-in yet. Recommended before real use: put Vercel's firewall in front, or add a per-IP limiter.
