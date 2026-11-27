-- Revision 0007: operators, versioned plans, approvals, atomic plan commits,
-- transactional outbox.

do $$
declare t text;
begin
  foreach t in array array['operators','plan_versions','plan_changes','approval_requests',
                           'approval_decisions','plan_routing','lot_allocations','outbox_messages'] loop
    execute format('alter table cornucopia.%I enable row level security', t);
    execute format('revoke all on cornucopia.%I from public, anon, authenticated', t);
    execute format('grant select on cornucopia.%I to service_role', t);
  end loop;
end $$;
revoke all on all sequences in schema cornucopia from public, anon, authenticated;
grant usage, select on all sequences in schema cornucopia to service_role;

-- audit + state version for the committed-plan tables, touch for mutable ones
do $$
declare t text;
begin
  foreach t in array array['plan_routing','lot_allocations','operators'] loop
    execute format('create trigger audit_and_version after insert or update or delete on cornucopia.%I
                      for each row execute function cornucopia.tg_audit_and_version()', t);
  end loop;
end $$;
create trigger touch_updated_at before update on cornucopia.operators
  for each row execute function cornucopia.tg_touch_updated_at();
create trigger touch_updated_at before update on cornucopia.approval_requests
  for each row execute function cornucopia.tg_touch_updated_at();
create trigger append_only before update or delete on cornucopia.approval_decisions
  for each row execute function cornucopia.tg_agent_append_only();
create trigger append_only before update or delete on cornucopia.plan_changes
  for each row execute function cornucopia.tg_agent_append_only();

-- Plan-owned commitment columns may only change inside an approved commit.
create or replace function cornucopia.tg_commitment_plan_guard()
returns trigger language plpgsql set search_path = '' as $$
begin
  if (new.planned_meals, new.committed_plan_version_id) is distinct from
     (old.planned_meals, old.committed_plan_version_id)
     and coalesce(current_setting('cornucopia.plan_commit', true), '') <> 'on' then
    raise exception 'planned meals change only through an approved plan commit' using errcode = '42501';
  end if;
  return new;
end $$;
create trigger plan_guard before update on cornucopia.commitments
  for each row execute function cornucopia.tg_commitment_plan_guard();

-- ---------------------------------------------------------------- operators
create or replace function cornucopia.create_operator(
  p_organization_id uuid, p_username text, p_display_name text, p_role text, p_password_hash text
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare v cornucopia.operators;
begin
  perform set_config('cornucopia.actor', 'admin:cli', true);
  insert into cornucopia.operators (organization_id, username, display_name, role, password_hash)
  values (p_organization_id, p_username, p_display_name, p_role, p_password_hash)
  on conflict (organization_id, username) do update
     set display_name = excluded.display_name, role = excluded.role,
         password_hash = excluded.password_hash, active = true
  returning * into v;
  return jsonb_build_object('id', v.id, 'username', v.username, 'role', v.role);
end $$;

-- ----------------------------------------------------------------- proposals
create or replace function cornucopia.propose_plan(
  p_organization_id uuid, p_execution_id uuid, p_worker text, p_attempt int, p_run_id uuid,
  p_report jsonb, p_changes jsonb, p_escalated boolean, p_ttl_minutes int
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_req cornucopia.approval_requests;
  v_run cornucopia.optimization_runs;
  v_res cornucopia.optimization_results;
  v_pv cornucopia.plan_versions;
  v_num int;
begin
  if not cornucopia._holds_lease(p_execution_id, p_worker, p_attempt) then
    raise exception 'execution lease not held' using errcode = 'P0409';
  end if;
  select * into v_req from cornucopia.approval_requests where execution_id = p_execution_id;
  if found then  -- replayed node after a crash: same proposal
    return jsonb_build_object('request_id', v_req.id, 'plan_version_id', v_req.plan_version_id,
      'fingerprint', v_req.fingerprint, 'state_version', v_req.state_version,
      'expires_at', v_req.expires_at, 'duplicate', true);
  end if;
  select * into v_run from cornucopia.optimization_runs
   where id = p_run_id and organization_id = p_organization_id;
  select * into v_res from cornucopia.optimization_results where run_id = p_run_id and recommended;
  if v_run.id is null or v_res.id is null or v_res.plan is null then
    raise exception 'optimization run % has no recommended plan', p_run_id using errcode = 'P0404';
  end if;
  if v_res.verdict not in ('verified_feasible','verified_partial') then
    raise exception 'only independently verified plans can be proposed' using errcode = 'P0422';
  end if;

  perform pg_advisory_xact_lock(hashtextextended('plans/' || p_organization_id::text, 0));
  select coalesce(max(version_number), 0) + 1 into v_num
    from cornucopia.plan_versions where organization_id = p_organization_id;
  insert into cornucopia.plan_versions (organization_id, version_number, optimization_run_id, execution_id,
    fingerprint, state_version, verdict, plan, summary)
  values (p_organization_id, v_num, p_run_id, p_execution_id, v_res.fingerprint, v_run.state_version,
    v_res.verdict, v_res.plan, v_res.summary)
  returning * into v_pv;
  insert into cornucopia.plan_changes (plan_version_id, kind, ref_id, label, field, before, after)
  select v_pv.id, c ->> 'kind', c ->> 'ref_id', c ->> 'label', c ->> 'field', c ->> 'before', c ->> 'after'
    from jsonb_array_elements(coalesce(p_changes, '[]'::jsonb)) c;

  -- a newer proposal supersedes every older undecided one
  update cornucopia.plan_versions set status = 'stale'
   where id in (select plan_version_id from cornucopia.approval_requests
                 where organization_id = p_organization_id and status in ('pending','approved'));
  update cornucopia.approval_requests
     set status = 'stale', status_reason = 'superseded by plan v' || v_num
   where organization_id = p_organization_id and status in ('pending','approved');

  insert into cornucopia.approval_requests (organization_id, plan_version_id, execution_id, fingerprint,
    state_version, escalated, requested_by, report, expires_at)
  values (p_organization_id, v_pv.id, p_execution_id, v_pv.fingerprint, v_pv.state_version,
    coalesce(p_escalated, false), 'agent:' || p_worker, coalesce(p_report, '{}'::jsonb),
    now() + make_interval(mins => greatest(5, least(coalesce(p_ttl_minutes, 240), 1440))))
  returning * into v_req;
  return jsonb_build_object('request_id', v_req.id, 'plan_version_id', v_pv.id,
    'version_number', v_num, 'fingerprint', v_pv.fingerprint, 'state_version', v_pv.state_version,
    'expires_at', v_req.expires_at, 'duplicate', false);
end $$;

-- ------------------------------------------------------------------ decisions
-- Never raises for a refused decision: the refusal itself is recorded (and
-- any status change it implies, e.g. expired or stale) and returned as a code.
create or replace function cornucopia.decide_approval(
  p_organization_id uuid, p_request_id uuid, p_operator_id uuid, p_decision text,
  p_fingerprint text, p_state_version bigint, p_confirm boolean, p_reason text
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_req cornucopia.approval_requests;
  v_op cornucopia.operators;
  v_current bigint;
  v_code text;
begin
  if p_decision not in ('approve','reject') then
    raise exception 'decision must be approve or reject' using errcode = 'P0422';
  end if;
  select * into v_req from cornucopia.approval_requests
   where id = p_request_id and organization_id = p_organization_id for update;
  if not found then
    raise exception 'approval request not found' using errcode = 'P0404';
  end if;
  select * into v_op from cornucopia.operators
   where id = p_operator_id and organization_id = p_organization_id;
  select version into v_current from cornucopia.operational_state where organization_id = p_organization_id;

  if v_op.id is null or not v_op.active or v_op.role not in ('approver','admin') then
    v_code := 'unauthorized';
  elsif v_req.status in ('approved','committed') then
    v_code := 'duplicate';
  elsif v_req.status <> 'pending' then
    v_code := 'not_pending';
  elsif v_req.expires_at <= now() then
    v_code := 'expired';
    update cornucopia.approval_requests set status = 'expired', status_reason = 'approval window elapsed'
     where id = v_req.id;
    update cornucopia.plan_versions set status = 'expired' where id = v_req.plan_version_id;
  elsif p_fingerprint is distinct from v_req.fingerprint then
    v_code := 'fingerprint_mismatch';
  elsif p_state_version is distinct from v_req.state_version or v_current <> v_req.state_version then
    v_code := 'stale';
    update cornucopia.approval_requests
       set status = 'stale', status_reason = format('plan computed at v%s, operations now at v%s',
                                                    v_req.state_version, v_current)
     where id = v_req.id;
    update cornucopia.plan_versions set status = 'stale' where id = v_req.plan_version_id;
  elsif p_decision = 'approve' and not coalesce(p_confirm, false) then
    v_code := 'confirmation_required';
  end if;

  insert into cornucopia.approval_decisions (approval_request_id, operator_id, operator_username, decision,
    accepted, refusal_reason, fingerprint_presented, state_version_presented, confirmed, reason)
  values (v_req.id, v_op.id, coalesce(v_op.username, 'unknown'), p_decision, v_code is null, v_code,
    coalesce(p_fingerprint, ''), coalesce(p_state_version, -1), coalesce(p_confirm, false), left(p_reason, 500));

  if v_code is not null then
    return jsonb_build_object('accepted', false, 'code', v_code,
      'status', (select status from cornucopia.approval_requests where id = v_req.id));
  end if;
  update cornucopia.approval_requests
     set status = case p_decision when 'approve' then 'approved' else 'rejected' end,
         decided_at = now(), status_reason = left(p_reason, 500)
   where id = v_req.id;
  if p_decision = 'reject' then
    update cornucopia.plan_versions set status = 'rejected' where id = v_req.plan_version_id;
  end if;
  return jsonb_build_object('accepted', true,
    'status', case p_decision when 'approve' then 'approved' else 'rejected' end);
end $$;

-- ---------------------------------------------------------------------- commit
-- Atomically: verify approval, fingerprint, operational version and the
-- executing worker's lease; apply the plan; record the commit; audit (row
-- triggers, attributed to the approver); write the outbox message. Any check
-- failing changes nothing except marking the request stale/expired.
create or replace function cornucopia.commit_approved_plan(
  p_request_id uuid, p_worker text, p_attempt int
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_req cornucopia.approval_requests;
  v_pv cornucopia.plan_versions;
  v_dec cornucopia.approval_decisions;
  v_op cornucopia.operators;
  v_org uuid;
  v_current bigint;
  v_after bigint;
  v_team uuid;
begin
  select organization_id into v_org from cornucopia.approval_requests where id = p_request_id;
  if v_org is null then
    raise exception 'approval request not found' using errcode = 'P0404';
  end if;
  perform pg_advisory_xact_lock(hashtextextended('plans/' || v_org::text, 0));
  select * into v_req from cornucopia.approval_requests where id = p_request_id for update;
  if v_req.execution_id is null or not cornucopia._holds_lease(v_req.execution_id, p_worker, p_attempt) then
    raise exception 'execution lease not held' using errcode = 'P0409';
  end if;
  if v_req.status = 'committed' then
    return jsonb_build_object('committed', true, 'duplicate', true, 'plan_version_id', v_req.plan_version_id);
  end if;
  if v_req.status <> 'approved' then
    return jsonb_build_object('committed', false, 'code', 'not_approved', 'status', v_req.status);
  end if;
  if v_req.expires_at <= now() then
    update cornucopia.approval_requests set status = 'expired', status_reason = 'expired before commit'
     where id = v_req.id;
    update cornucopia.plan_versions set status = 'expired' where id = v_req.plan_version_id;
    return jsonb_build_object('committed', false, 'code', 'expired');
  end if;
  select * into v_dec from cornucopia.approval_decisions
   where approval_request_id = v_req.id and decision = 'approve' and accepted
   order by created_at desc limit 1;
  select * into v_op from cornucopia.operators where id = v_dec.operator_id;
  if v_dec.id is null or v_op.id is null or not v_op.active or v_op.role not in ('approver','admin') then
    return jsonb_build_object('committed', false, 'code', 'no_valid_approval');
  end if;
  select * into v_pv from cornucopia.plan_versions where id = v_req.plan_version_id;
  if v_pv.fingerprint <> v_req.fingerprint or v_dec.fingerprint_presented <> v_req.fingerprint then
    return jsonb_build_object('committed', false, 'code', 'fingerprint_mismatch');
  end if;
  select version into v_current from cornucopia.operational_state where organization_id = v_org for update;
  if v_current <> v_req.state_version then
    update cornucopia.approval_requests
       set status = 'stale', status_reason = format('operations changed (v%s -> v%s) before commit',
                                                    v_req.state_version, v_current)
     where id = v_req.id;
    update cornucopia.plan_versions set status = 'stale' where id = v_pv.id;
    return jsonb_build_object('committed', false, 'code', 'stale',
                              'plan_state_version', v_req.state_version, 'current_state_version', v_current);
  end if;

  perform set_config('cornucopia.actor', 'operator:' || v_op.username || ' (approved plan v' || v_pv.version_number || ')', true);
  perform set_config('cornucopia.plan_commit', 'on', true);

  -- cooking batches: replace the previous plan's planned batches
  update cornucopia.meal_batches set status = 'cancelled'
   where organization_id = v_org and status = 'planned';
  select (t ->> 'team_id')::uuid into v_team
    from jsonb_array_elements(v_pv.plan -> 'teams') t
   order by (t ->> 'portions')::int desc, t ->> 'team_id' limit 1;
  insert into cornucopia.meal_batches (organization_id, recipe_id, team_id, planned_portions, status, plan_version_id)
  select v_org, (r ->> 'recipe_id')::uuid, v_team, (r ->> 'portions')::numeric, 'planned', v_pv.id
    from jsonb_array_elements(v_pv.plan -> 'recipes') r;

  -- stock reservations
  update cornucopia.lot_allocations set released_at = now()
   where organization_id = v_org and released_at is null;
  insert into cornucopia.lot_allocations (organization_id, plan_version_id, lot_id, ingredient_id, quantity_base)
  select v_org, v_pv.id, (a ->> 'lot_id')::uuid, (a ->> 'ingredient_id')::uuid, (a ->> 'quantity_base')::numeric
    from jsonb_array_elements(v_pv.plan -> 'allocations') a;

  -- delivery routing
  insert into cornucopia.plan_routing (organization_id, plan_version_id, commitment_id, delivery_id, meals)
  select v_org, v_pv.id, (x ->> 'commitment_id')::uuid, (x ->> 'delivery_id')::uuid, (x ->> 'meals')::int
    from jsonb_array_elements(coalesce(v_pv.plan -> 'routing', '[]'::jsonb)) x;

  -- commitments: what will actually be delivered (the promise itself is unchanged)
  update cornucopia.commitments c
     set planned_meals = (p ->> 'planned')::int, committed_plan_version_id = v_pv.id,
         delivery_id = coalesce(
           (select (x ->> 'delivery_id')::uuid from jsonb_array_elements(coalesce(v_pv.plan -> 'routing', '[]'::jsonb)) x
             where x ->> 'commitment_id' = c.id::text
             group by x ->> 'delivery_id' having count(*) = 1
             limit 1), c.delivery_id)
    from jsonb_array_elements(v_pv.plan -> 'commitments') p
   where c.id = (p ->> 'commitment_id')::uuid and c.organization_id = v_org;

  update cornucopia.plan_versions set status = 'superseded'
   where organization_id = v_org and status = 'committed';
  select version into v_after from cornucopia.operational_state where organization_id = v_org;
  update cornucopia.operational_state set committed_plan_version_id = v_pv.id where organization_id = v_org;
  update cornucopia.plan_versions
     set status = 'committed', committed_at = now(), committed_state_version = v_after
   where id = v_pv.id;
  update cornucopia.approval_requests set status = 'committed', committed_at = now() where id = v_req.id;

  insert into cornucopia.outbox_messages (organization_id, topic, payload)
  values (v_org, 'plan.committed', jsonb_build_object(
    'plan_version_id', v_pv.id, 'version_number', v_pv.version_number, 'fingerprint', v_pv.fingerprint,
    'approval_request_id', v_req.id, 'approved_by', v_op.username,
    'meals_planned', (v_pv.plan -> 'metrics' ->> 'meals_planned')::int,
    'meals_requested', (v_pv.plan -> 'metrics' ->> 'meals_requested')::int,
    'state_version_before', v_req.state_version, 'state_version_after', v_after));

  return jsonb_build_object('committed', true, 'duplicate', false, 'plan_version_id', v_pv.id,
    'version_number', v_pv.version_number, 'state_version_after', v_after, 'approved_by', v_op.username);
end $$;

-- ------------------------------------------------------------- housekeeping
create or replace function cornucopia.expire_approvals(p_organization_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_current bigint;
  v_exp int;
  v_stale int;
begin
  select version into v_current from cornucopia.operational_state where organization_id = p_organization_id;
  with e as (
    update cornucopia.approval_requests set status = 'expired', status_reason = 'approval window elapsed'
     where organization_id = p_organization_id and status in ('pending','approved') and expires_at <= now()
     returning plan_version_id)
  update cornucopia.plan_versions set status = 'expired' where id in (select plan_version_id from e);
  get diagnostics v_exp = row_count;
  with s as (
    update cornucopia.approval_requests
       set status = 'stale', status_reason = format('operations changed after the plan was computed (now v%s)', v_current)
     where organization_id = p_organization_id and status in ('pending','approved') and state_version <> v_current
     returning plan_version_id)
  update cornucopia.plan_versions set status = 'stale' where id in (select plan_version_id from s);
  get diagnostics v_stale = row_count;
  return jsonb_build_object('expired', v_exp, 'stale', v_stale);
end $$;

-- --------------------------------------- resume executions after a decision
create or replace function cornucopia.claim_next_execution(
  p_organization_id uuid, p_worker text, p_lease_seconds int
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_exec cornucopia.agent_executions;
  v_event cornucopia.operational_events;
  v_req cornucopia.approval_requests;
  v_dec cornucopia.approval_decisions;
begin
  if p_lease_seconds not between 5 and 3600 then
    raise exception 'lease must be 5..3600 seconds' using errcode = 'P0422';
  end if;

  -- 1. crashed workers: expired leases
  select * into v_exec from cornucopia.agent_executions
   where organization_id = p_organization_id and status = 'running' and lease_expires_at < now()
   order by created_at for update skip locked limit 1;
  if found then
    update cornucopia.agent_executions
       set lease_owner = p_worker, attempt = attempt + 1,
           lease_expires_at = now() + make_interval(secs => p_lease_seconds), heartbeat_at = now()
     where id = v_exec.id returning * into v_exec;
    insert into cornucopia.agent_execution_steps (execution_id, attempt, node, status, detail)
    values (v_exec.id, v_exec.attempt, coalesce(v_exec.current_node, 'supervisor'), 'resumed',
            jsonb_build_object('worker', p_worker, 'previous_owner_lease_expired', true));
    select * into v_event from cornucopia.operational_events where id = v_exec.event_id;
    select * into v_req from cornucopia.approval_requests where execution_id = v_exec.id;
    return jsonb_build_object('resumed', true, 'execution', to_jsonb(v_exec), 'event', to_jsonb(v_event),
      'approval', case when v_req.id is not null and v_req.status <> 'pending' then
        jsonb_build_object('request_id', v_req.id, 'status', v_req.status) end);
  end if;

  -- 2. paused executions whose approval request was decided (or went stale/expired)
  select e.* into v_exec from cornucopia.agent_executions e
    join cornucopia.approval_requests r on r.execution_id = e.id
   where e.organization_id = p_organization_id and e.status = 'awaiting_approval'
     and r.status in ('approved','rejected','stale','expired')
   order by r.updated_at for update of e skip locked limit 1;
  if found then
    select * into v_req from cornucopia.approval_requests where execution_id = v_exec.id;
    select * into v_dec from cornucopia.approval_decisions
     where approval_request_id = v_req.id and accepted order by created_at desc limit 1;
    update cornucopia.agent_executions
       set status = 'running', lease_owner = p_worker, attempt = attempt + 1, finished_at = null,
           lease_expires_at = now() + make_interval(secs => p_lease_seconds), heartbeat_at = now()
     where id = v_exec.id returning * into v_exec;
    insert into cornucopia.agent_execution_steps (execution_id, attempt, node, status, detail)
    values (v_exec.id, v_exec.attempt, 'request_approval', 'resumed',
            jsonb_build_object('worker', p_worker, 'approval_status', v_req.status,
                               'decided_by', v_dec.operator_username));
    select * into v_event from cornucopia.operational_events where id = v_exec.event_id;
    return jsonb_build_object('resumed', true, 'execution', to_jsonb(v_exec), 'event', to_jsonb(v_event),
      'approval', jsonb_build_object('request_id', v_req.id, 'status', v_req.status,
                                     'decided_by', v_dec.operator_username, 'reason', v_req.status_reason));
  end if;

  -- 3. new events
  select * into v_event from cornucopia.operational_events
   where organization_id = p_organization_id and processing_status = 'pending'
   order by created_at, id for update skip locked limit 1;
  if not found then
    return null;
  end if;
  insert into cornucopia.agent_executions (organization_id, event_id, thread_id, correlation_id, status,
                                           attempt, lease_owner, lease_expires_at, heartbeat_at)
  values (p_organization_id, v_event.id, 'event:' || v_event.id, v_event.correlation_id, 'running',
          1, p_worker, now() + make_interval(secs => p_lease_seconds), now())
  on conflict (event_id) do nothing
  returning * into v_exec;
  if v_exec.id is null then
    update cornucopia.operational_events set processing_status = 'processed',
           processing_note = 'execution already exists' where id = v_event.id;
    return null;
  end if;
  update cornucopia.operational_events set processing_status = 'processing' where id = v_event.id;
  insert into cornucopia.agent_execution_steps (execution_id, attempt, node, status, detail)
  values (v_exec.id, 1, 'supervisor', 'claimed', jsonb_build_object('worker', p_worker));
  return jsonb_build_object('resumed', false, 'execution', to_jsonb(v_exec), 'event', to_jsonb(v_event));
end $$;

-- escalated proposals mark their event escalated too
create or replace function cornucopia.finish_execution(
  p_execution_id uuid, p_worker text, p_attempt int, p_status text, p_result jsonb, p_error text
) returns boolean language plpgsql security definer set search_path = '' as $$
declare
  v_event uuid;
  v_escalated boolean := coalesce((p_result ->> 'escalated')::boolean, false);
begin
  if p_status not in ('awaiting_approval','completed','escalated','failed') then
    raise exception 'invalid final status %', p_status using errcode = 'P0422';
  end if;
  if not cornucopia._holds_lease(p_execution_id, p_worker, p_attempt) then
    return false;
  end if;
  update cornucopia.agent_executions
     set status = p_status, result = p_result, error = p_error, finished_at = now(),
         lease_owner = null, lease_expires_at = null
   where id = p_execution_id
   returning event_id into v_event;
  update cornucopia.operational_events
     set processing_status = case when p_status = 'escalated' or v_escalated then 'escalated'
                                  when p_status = 'failed' then 'failed' else 'processed' end,
         processing_note = case p_status when 'awaiting_approval' then 'recovery proposal awaiting approval'
                                         when 'completed' then coalesce(p_result -> 'outcome' ->> 'status', 'completed')
                                         else left(coalesce(p_error, p_status), 500) end,
         processed_at = now()
   where id = v_event;
  return true;
end $$;

do $$
declare f text;
begin
  foreach f in array array[
    'create_operator(uuid, text, text, text, text)',
    'propose_plan(uuid, uuid, text, int, uuid, jsonb, jsonb, boolean, int)',
    'decide_approval(uuid, uuid, uuid, text, text, bigint, boolean, text)',
    'commit_approved_plan(uuid, text, int)', 'expire_approvals(uuid)',
    'claim_next_execution(uuid, text, int)', 'finish_execution(uuid, text, int, text, jsonb, text)'
  ] loop
    execute format('revoke all on function cornucopia.%s from public, anon, authenticated', f);
    execute format('grant execute on function cornucopia.%s to service_role', f);
  end loop;
end $$;

notify pgrst, 'reload schema';
