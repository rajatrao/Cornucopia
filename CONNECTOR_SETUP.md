# Supabase Database connector setup

Verified against [Sprites Connectors docs](https://docs.fly.io/sprites/concepts/connectors.md) and the Supabase Database entry in the [Sprites ecosystem catalog](https://fly.io/sprites/ecosystem/) on 2026-11-27.

## What the connector is

A Sprites gateway route that forwards PostgREST requests from an authorized Sprite to a hosted Supabase project and attaches the project's `sb_secret_` key on the way. The key never lands on the Sprite. It uses `service_role` and bypasses RLS, so only trusted Sprites should be authorized.

Supported: REST database API (tables, views, RPC functions). Not supported: Auth, Storage, Realtime, Edge Functions, project management, and direct Postgres connections.

## One-time setup (already done for this project)

1. Fly.io dashboard → your organization → Sprites → Connectors → Add connector → Supabase Database.
2. Project URL: `https://<project-ref>.supabase.co` (from Supabase "Connect"). Secret key: an `sb_secret_...` key from Supabase Settings → API Keys. The project URL cannot be changed later.
3. Access settings: turn off "Allow all sprites", then restrict by name prefix (`cornucopia`) and/or labels. A connector with no policy denies all Sprites.

## Using it from the Sprite

Discover connections (inside the Sprite only):

```bash
curl -s https://api.sprites.dev/v1/gateway/list
```

The `connections[].gateway_base_url` field gives the base URL. Example read (no Authorization header):

```bash
curl "$SUPABASE_GATEWAY_URL/rest/v1/" -H "Accept: application/openapi+json"
```

`SUPABASE_GATEWAY_URL` is CORNUCOPIA's own config name, not a platform-injected variable.

Requests from outside a Sprite (laptop, CI) get `401`. Unsupported paths such as `/auth/v1/*` get `403`.

## Custom schema

CORNUCOPIA uses schema `cornucopia`. PostgREST only serves schemas listed under Supabase Project Settings → API → Exposed schemas. This repo declares that in `supabase/config.toml` and applies it with `supabase config push` (see DEPLOYMENT.md). Requests send `Accept-Profile: cornucopia` (reads) and `Content-Profile: cornucopia` (writes and RPC).

## Rotating the key

1. Supabase Settings → API Keys: create a new secret key, then revoke the old one.
2. Update the connector's credential in the Fly.io dashboard.
3. Update the local gitignored `.env` if you use local direct mode.

## Verified behaviours (2026-11-27)

- Custom request headers (for example `X-Cornucopia-Actor`) are **not** forwarded to PostgREST by the gateway. Anything the database must know about the caller is therefore passed as an RPC argument.
- PostgREST error bodies (`code`, `message`, `details`) pass through unchanged, including custom SQLSTATEs raised by our functions.
