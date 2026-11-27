-- Revision 0009: transactional outbox delivery into the in-app notification
-- feed, and agent worker liveness.

do $$
declare t text;
begin
  foreach t in array array['operator_notifications','agent_workers'] loop
    execute format('alter table cornucopia.%I enable row level security', t);
    execute format('revoke all on cornucopia.%I from public, anon, authenticated', t);
    execute format('grant select on cornucopia.%I to service_role', t);
  end loop;
end $$;

-- Deliver due outbox messages exactly once: claim with SKIP LOCKED, write the
-- notification (unique per message) and mark delivered in one transaction.
-- A failure only bumps attempts with exponential backoff.
create or replace function cornucopia.deliver_outbox(p_organization_id uuid, p_limit int)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  m cornucopia.outbox_messages;
  n int := 0;
  v_title text;
begin
  for m in
    select * from cornucopia.outbox_messages
     where organization_id = p_organization_id and delivered_at is null and next_attempt_at <= now()
     order by created_at
     for update skip locked
     limit greatest(1, least(p_limit, 100))
  loop
    begin
      v_title := case m.topic
        when 'plan.committed' then format('Plan v%s committed by %s: %s of %s meals',
          m.payload ->> 'version_number', m.payload ->> 'approved_by',
          m.payload ->> 'meals_planned', m.payload ->> 'meals_requested')
        else m.topic end;
      insert into cornucopia.operator_notifications (organization_id, outbox_message_id, topic, title, payload)
      values (m.organization_id, m.id, m.topic, v_title, m.payload)
      on conflict (outbox_message_id) do nothing;
      update cornucopia.outbox_messages set delivered_at = now(), attempts = attempts + 1 where id = m.id;
      n := n + 1;
    exception when others then
      update cornucopia.outbox_messages
         set attempts = attempts + 1, last_error = left(sqlerrm, 500),
             next_attempt_at = now() + make_interval(secs => least(3600, 5 * power(2, attempts)::int))
       where id = m.id;
    end;
  end loop;
  return jsonb_build_object('delivered', n);
end $$;

create or replace function cornucopia.worker_heartbeat(
  p_organization_id uuid, p_worker text, p_status text, p_version text
) returns boolean language plpgsql security definer set search_path = '' as $$
begin
  insert into cornucopia.agent_workers (worker_id, organization_id, started_at, last_seen_at, status, version)
  values (p_worker, p_organization_id, now(), now(), p_status, p_version)
  on conflict (worker_id) do update set last_seen_at = now(), status = excluded.status;
  return true;
end $$;

do $$
declare f text;
begin
  foreach f in array array['deliver_outbox(uuid, int)', 'worker_heartbeat(uuid, text, text, text)'] loop
    execute format('revoke all on function cornucopia.%s from public, anon, authenticated', f);
    execute format('grant execute on function cornucopia.%s to service_role', f);
  end loop;
end $$;

notify pgrst, 'reload schema';
