-- Revision 0003: single write path for resource management (CRUD).
--
-- Verified 2026-11-27: the Sprites gateway does not forward custom request
-- headers, so an actor header cannot reach the audit trigger on plain REST
-- writes. Every resource write therefore goes through this RPC, which sets
-- the actor for the transaction, enforces organization ownership, and lets
-- the audit/version triggers record the change atomically.
--
-- Inventory lots, donations and operational events are deliberately absent:
-- they change only through ingest_event.

create or replace function cornucopia.write_resource(
  p_organization_id uuid,
  p_actor text,
  p_table text,
  p_action text,
  p_id uuid,
  p_values jsonb
) returns jsonb language plpgsql set search_path = '' as $$
declare
  v_cols text;
  v_row jsonb;
  v_parent_table text;
  v_parent_col text;
  v_owned boolean;
  v_org_scoped boolean;
begin
  if p_table not in ('donors','ingredients','recipes','recipe_ingredients','ingredient_substitutions',
                     'meals','meal_components','preparation_teams','volunteers','deliveries',
                     'commitments') then
    raise exception 'table % is not writable through write_resource', p_table using errcode = 'P0403';
  end if;
  if p_action not in ('insert','update','delete') then
    raise exception 'unknown action %', p_action using errcode = 'P0422';
  end if;
  if p_actor is null or length(p_actor) < 3 then
    raise exception 'actor is required' using errcode = 'P0422';
  end if;
  perform set_config('cornucopia.actor', p_actor, true);

  v_org_scoped := p_table not in ('recipe_ingredients','meal_components');
  v_parent_table := case p_table when 'recipe_ingredients' then 'recipes' when 'meal_components' then 'meals' end;
  v_parent_col := case p_table when 'recipe_ingredients' then 'recipe_id' when 'meal_components' then 'meal_id' end;

  if p_values ? 'id' or p_values ? 'created_at' or p_values ? 'updated_at' then
    raise exception 'id and timestamps are server-managed' using errcode = 'P0422';
  end if;
  if v_org_scoped then
    if p_action = 'insert' then
      p_values := p_values || jsonb_build_object('organization_id', p_organization_id);
    elsif p_values ? 'organization_id' then
      raise exception 'organization_id cannot change' using errcode = 'P0422';
    end if;
  end if;

  if p_action = 'insert' then
    select string_agg(quote_ident(k), ',') into v_cols from jsonb_object_keys(p_values) k;
    execute format(
      'insert into cornucopia.%1$I (%2$s) select %2$s from jsonb_populate_record(null::cornucopia.%1$I, $1)
       returning to_jsonb(%1$I.*)', p_table, v_cols)
      using p_values into v_row;
  elsif p_action = 'update' then
    if p_values = '{}'::jsonb then
      raise exception 'nothing to update' using errcode = 'P0422';
    end if;
    select string_agg(quote_ident(k), ',') into v_cols from jsonb_object_keys(p_values) k;
    execute format(
      'update cornucopia.%1$I t set (%2$s) = (select %2$s from jsonb_populate_record(null::cornucopia.%1$I, $1))
        where t.id = $2 %3$s returning to_jsonb(t.*)',
      p_table, v_cols, case when v_org_scoped then 'and t.organization_id = $3' else '' end)
      using p_values, p_id, p_organization_id into v_row;
  else
    execute format(
      'delete from cornucopia.%1$I t where t.id = $1 %2$s returning to_jsonb(t.*)',
      p_table, case when v_org_scoped then 'and t.organization_id = $2' else '' end)
      using p_id, p_organization_id into v_row;
  end if;

  if v_row is null then
    raise exception '% % not found', p_table, p_id using errcode = 'P0404';
  end if;

  if not v_org_scoped then
    execute format('select exists (select 1 from cornucopia.%I where id = $1 and organization_id = $2)', v_parent_table)
      using (v_row ->> v_parent_col)::uuid, p_organization_id into v_owned;
    if not v_owned then
      raise exception '% belongs to another organization', p_table using errcode = 'P0403';
    end if;
  end if;
  return v_row;
end $$;

revoke all on function cornucopia.write_resource(uuid, text, text, text, uuid, jsonb) from public, anon, authenticated;
grant execute on function cornucopia.write_resource(uuid, text, text, text, uuid, jsonb) to service_role;

-- Direct table writes are no longer needed by the application: reads stay on
-- REST, writes go through RPCs (write_resource, ingest_event).
do $$
declare t text;
begin
  foreach t in array array[
    'donors','ingredients','donations','inventory_lots','recipes','recipe_ingredients',
    'ingredient_substitutions','meals','meal_components','preparation_teams','volunteers',
    'deliveries','commitments','meal_batches','operational_state'
  ] loop
    execute format('revoke insert, update, delete on cornucopia.%I from service_role', t);
  end loop;
end $$;
revoke insert, update on cornucopia.operational_events from service_role;
revoke insert on cornucopia.audit_records from service_role;

-- RPCs that write must therefore run with the owner's rights.
alter function cornucopia.write_resource(uuid, text, text, text, uuid, jsonb) security definer;
alter function cornucopia.ingest_event(uuid, text, text, jsonb, text, uuid) security definer;
alter function cornucopia.ensure_organization(text, text) security definer;
alter function cornucopia.record_probe(text, text) security definer;

notify pgrst, 'reload schema';
