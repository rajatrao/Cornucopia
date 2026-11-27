-- Hand-written part of revision 0001: privileges, RLS, RPC functions.
-- Applied right after the Alembic-generated tables in the same migration.

-- Only service_role (what the Sprites connector's sb_secret_ key maps to)
-- may touch this schema. anon/authenticated get nothing: the browser never
-- talks to Supabase.
revoke all on schema cornucopia from public, anon, authenticated;
grant usage on schema cornucopia to service_role;

alter table cornucopia.organizations enable row level security;
alter table cornucopia.system_probes enable row level security;

revoke all on all tables in schema cornucopia from public, anon, authenticated;
grant select, insert, update, delete on all tables in schema cornucopia to service_role;

alter default privileges in schema cornucopia revoke all on tables from public, anon, authenticated;
alter default privileges in schema cornucopia grant select, insert, update, delete on tables to service_role;
alter default privileges in schema cornucopia revoke execute on functions from public, anon, authenticated;
alter default privileges in schema cornucopia grant execute on functions to service_role;

create or replace function cornucopia.health_check()
returns jsonb
language sql
stable
set search_path = ''
as $$
  select jsonb_build_object(
    'ok', true,
    'schema', 'cornucopia',
    'server_time', to_char(now() at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    'backend', 'postgres ' || current_setting('server_version')
  );
$$;

create or replace function cornucopia.record_probe(p_note text, p_source text)
returns cornucopia.system_probes
language sql
volatile
set search_path = ''
as $$
  insert into cornucopia.system_probes (note, source)
  values (p_note, p_source)
  returning *;
$$;

revoke all on function cornucopia.health_check() from public, anon, authenticated;
revoke all on function cornucopia.record_probe(text, text) from public, anon, authenticated;
grant execute on function cornucopia.health_check() to service_role;
grant execute on function cornucopia.record_probe(text, text) to service_role;

-- Make PostgREST pick up the new objects immediately.
notify pgrst, 'reload schema';
