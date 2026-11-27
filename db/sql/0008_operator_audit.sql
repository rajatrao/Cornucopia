-- Revision 0008: operator account changes are audited but do not bump the
-- operational state version (they are not planning inputs; bumping would
-- make every pending approval stale when someone is added).

create or replace function cornucopia.tg_audit_and_version()
returns trigger language plpgsql security definer set search_path = '' as $$
declare
  v_old jsonb := case when tg_op in ('UPDATE','DELETE') then to_jsonb(old) end;
  v_new jsonb := case when tg_op in ('INSERT','UPDATE') then to_jsonb(new) end;
  v_row jsonb := coalesce(v_new, v_old);
  v_org uuid;
  v_event uuid := nullif(current_setting('cornucopia.event_id', true), '')::uuid;
begin
  if tg_op = 'UPDATE' and v_old = v_new then
    return new;
  end if;
  v_org := (v_row ->> 'organization_id')::uuid;
  if v_org is null and tg_table_name = 'recipe_ingredients' then
    select r.organization_id into v_org from cornucopia.recipes r where r.id = (v_row ->> 'recipe_id')::uuid;
  elsif v_org is null and tg_table_name = 'meal_components' then
    select m.organization_id into v_org from cornucopia.meals m where m.id = (v_row ->> 'meal_id')::uuid;
  end if;

  insert into cornucopia.audit_records (organization_id, table_name, record_id, action, actor, event_id, old_row, new_row)
  values (v_org, tg_table_name, v_row ->> 'id', tg_op, cornucopia.current_actor(), v_event, v_old, v_new);

  -- operator accounts are audited but are not operational inputs to plans
  if v_org is not null and tg_table_name <> 'operators' then
    insert into cornucopia.operational_state as s (organization_id, version, updated_at)
    values (v_org, 1, now())
    on conflict (organization_id) do update set version = s.version + 1, updated_at = now();
  end if;
  return coalesce(new, old);
end $$;

notify pgrst, 'reload schema';
