-- Revision 0005: append-only optimization runs and their candidate results.

alter table cornucopia.optimization_runs enable row level security;
alter table cornucopia.optimization_results enable row level security;
revoke all on cornucopia.optimization_runs, cornucopia.optimization_results from public, anon, authenticated;
grant select on cornucopia.optimization_runs, cornucopia.optimization_results to service_role;

create or replace function cornucopia.record_optimization_run(
  p_organization_id uuid,
  p_actor text,
  p_run jsonb,
  p_results jsonb
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_id uuid := gen_random_uuid();
begin
  if jsonb_typeof(p_results) <> 'array' or jsonb_array_length(p_results) = 0 then
    raise exception 'an optimization run needs at least one result' using errcode = 'P0422';
  end if;
  if (select count(*) from jsonb_array_elements(p_results) r where (r ->> 'recommended')::boolean) <> 1 then
    raise exception 'exactly one result must be recommended' using errcode = 'P0422';
  end if;
  insert into cornucopia.optimization_runs (id, organization_id, state_version, requested_by, correlation_id,
    config, solver_status, verdict, objectives, stages, model_stats, diagnosis, wall_ms)
  values (v_id, p_organization_id, (p_run ->> 'state_version')::bigint, p_actor,
    (p_run ->> 'correlation_id')::uuid, p_run -> 'config', p_run ->> 'solver_status', p_run ->> 'verdict',
    p_run -> 'objectives', p_run -> 'stages', p_run -> 'model_stats', p_run -> 'diagnosis',
    (p_run ->> 'wall_ms')::numeric);
  insert into cornucopia.optimization_results (run_id, candidate, recommended, verdict, fingerprint,
    meals_planned, plan, summary)
  select v_id, r ->> 'candidate', (r ->> 'recommended')::boolean, r ->> 'verdict', r ->> 'fingerprint',
         (r ->> 'meals_planned')::int, r -> 'plan', r -> 'summary'
    from jsonb_array_elements(p_results) r;
  return jsonb_build_object('run_id', v_id);
end $$;

create or replace function cornucopia.tg_optimization_append_only()
returns trigger language plpgsql set search_path = '' as $$
begin
  raise exception '% is append-only', tg_table_name using errcode = '42501';
end $$;
create trigger append_only before update or delete on cornucopia.optimization_runs
  for each row execute function cornucopia.tg_optimization_append_only();
create trigger append_only before update or delete on cornucopia.optimization_results
  for each row execute function cornucopia.tg_optimization_append_only();

revoke all on function cornucopia.record_optimization_run(uuid, text, jsonb, jsonb) from public, anon, authenticated;
grant execute on function cornucopia.record_optimization_run(uuid, text, jsonb, jsonb) to service_role;

notify pgrst, 'reload schema';
