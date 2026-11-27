-- Revision 0002 (hand-written part): privileges, RLS, audit + state-version
-- triggers, append-only journal, and the transactional event ingest RPC.

-- ---------------------------------------------------------------- privileges
do $$
declare t text;
begin
  foreach t in array array[
    'donors','ingredients','donations','inventory_lots','recipes','recipe_ingredients',
    'ingredient_substitutions','meals','meal_components','preparation_teams','volunteers',
    'deliveries','commitments','meal_batches','operational_state','operational_events',
    'audit_records'
  ] loop
    execute format('alter table cornucopia.%I enable row level security', t);
    execute format('revoke all on cornucopia.%I from public, anon, authenticated', t);
    execute format('grant select, insert, update, delete on cornucopia.%I to service_role', t);
  end loop;
end $$;
revoke all on all sequences in schema cornucopia from public, anon, authenticated;
grant usage, select on all sequences in schema cornucopia to service_role;

-- The journal and the audit log are append-only even for service_role.
revoke update, delete on cornucopia.audit_records from service_role;
revoke delete on cornucopia.operational_events from service_role;

-- ------------------------------------------------------------------- actor
-- Who is acting: set by RPCs (set_config), else the X-Cornucopia-Actor
-- request header forwarded by PostgREST, else 'system'.
create or replace function cornucopia.current_actor()
returns text language sql stable set search_path = '' as $$
  select coalesce(
    nullif(current_setting('cornucopia.actor', true), ''),
    nullif((nullif(current_setting('request.headers', true), '')::json ->> 'x-cornucopia-actor'), ''),
    'system'
  );
$$;

-- --------------------------------------------------- audit + state version
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

  if v_org is not null then
    insert into cornucopia.operational_state as s (organization_id, version, updated_at)
    values (v_org, 1, now())
    on conflict (organization_id) do update set version = s.version + 1, updated_at = now();
  end if;
  return coalesce(new, old);
end $$;

create or replace function cornucopia.tg_touch_updated_at()
returns trigger language plpgsql set search_path = '' as $$
begin
  new.updated_at := now();
  return new;
end $$;

do $$
declare t text;
begin
  foreach t in array array[
    'donors','ingredients','donations','inventory_lots','recipes','recipe_ingredients',
    'ingredient_substitutions','meals','meal_components','preparation_teams','volunteers',
    'deliveries','commitments','meal_batches'
  ] loop
    execute format(
      'create trigger audit_and_version after insert or update or delete on cornucopia.%I
         for each row execute function cornucopia.tg_audit_and_version()', t);
    if t not in ('recipe_ingredients','meal_components') then
      execute format(
        'create trigger touch_updated_at before update on cornucopia.%I
           for each row execute function cornucopia.tg_touch_updated_at()', t);
    end if;
  end loop;
end $$;

-- ---------------------------------------------------- append-only journal
create or replace function cornucopia.tg_events_append_only()
returns trigger language plpgsql set search_path = '' as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'operational_events is append-only' using errcode = '42501';
  end if;
  if (new.id, new.organization_id, new.idempotency_key, new.event_type, new.payload,
      new.payload_hash, new.actor, new.correlation_id, new.effect, new.state_version,
      new.created_at)
     is distinct from
     (old.id, old.organization_id, old.idempotency_key, old.event_type, old.payload,
      old.payload_hash, old.actor, old.correlation_id, old.effect, old.state_version,
      old.created_at) then
    raise exception 'operational_events: only processing columns may change' using errcode = '42501';
  end if;
  return new;
end $$;

create trigger append_only before update or delete on cornucopia.operational_events
  for each row execute function cornucopia.tg_events_append_only();

create or replace function cornucopia.tg_audit_append_only()
returns trigger language plpgsql set search_path = '' as $$
begin
  raise exception 'audit_records is append-only' using errcode = '42501';
end $$;

create trigger append_only before update or delete on cornucopia.audit_records
  for each row execute function cornucopia.tg_audit_append_only();

-- ------------------------------------------------------- organizations
create or replace function cornucopia.ensure_organization(p_slug text, p_name text)
returns cornucopia.organizations language plpgsql set search_path = '' as $$
declare v cornucopia.organizations;
begin
  insert into cornucopia.organizations (slug, name) values (p_slug, p_name)
  on conflict (slug) do nothing;
  select * into v from cornucopia.organizations where slug = p_slug;
  insert into cornucopia.operational_state (organization_id) values (v.id)
  on conflict (organization_id) do nothing;
  return v;
end $$;

-- ------------------------------------------------------------ event ingest
-- One transaction: idempotency check, apply the reported fact to operational
-- state, journal the event, audit every row change, bump the state version.
-- Payloads arrive already validated and unit-normalised by the API.
create or replace function cornucopia.ingest_event(
  p_organization_id uuid,
  p_idempotency_key text,
  p_event_type text,
  p_payload jsonb,
  p_actor text,
  p_correlation_id uuid
) returns jsonb language plpgsql set search_path = '' as $$
declare
  v_hash text := encode(sha256(convert_to(p_payload::text, 'UTF8')), 'hex');
  v_existing cornucopia.operational_events;
  v_id uuid := gen_random_uuid();
  v_effect jsonb;
  v_version bigint;
  v_n int;
  v_lot record;
  v_target uuid;
  v_status text;
begin
  -- serialise concurrent submissions of the same key
  perform pg_advisory_xact_lock(hashtextextended(p_organization_id::text || '/' || p_idempotency_key, 0));

  select * into v_existing from cornucopia.operational_events
   where organization_id = p_organization_id and idempotency_key = p_idempotency_key;
  if found then
    if v_existing.payload_hash <> v_hash or v_existing.event_type <> p_event_type then
      raise exception 'idempotency key % was already used for a different event', p_idempotency_key
        using errcode = 'P0409';
    end if;
    return jsonb_build_object('duplicate', true, 'event', to_jsonb(v_existing));
  end if;

  perform set_config('cornucopia.actor', p_actor, true);
  perform set_config('cornucopia.event_id', v_id::text, true);

  case p_event_type
  when 'DONATION_CREATED' then
    v_target := gen_random_uuid();
    v_status := case when coalesce((p_payload ->> 'received')::boolean, true) then 'received' else 'pledged' end;
    insert into cornucopia.donations (id, organization_id, donor_id, description, status, expected_at, received_at, source_event_id)
    values (v_target, p_organization_id, (p_payload ->> 'donor_id')::uuid, p_payload ->> 'description', v_status,
            (p_payload ->> 'expected_at')::timestamptz,
            case when v_status = 'received' then now() end, v_id);
    insert into cornucopia.inventory_lots (organization_id, ingredient_id, donation_id, reported_quantity, reported_unit,
                                           initial_quantity_base, quantity_base, base_unit, status, expires_at)
    select p_organization_id, (l ->> 'ingredient_id')::uuid, v_target, (l ->> 'quantity')::numeric, l ->> 'unit',
           (l ->> 'quantity_base')::numeric, (l ->> 'quantity_base')::numeric, i.base_unit,
           case when v_status = 'received' then 'available' else 'pledged' end, (l ->> 'expires_at')::timestamptz
      from jsonb_array_elements(p_payload -> 'lots') l
      join cornucopia.ingredients i on i.id = (l ->> 'ingredient_id')::uuid and i.organization_id = p_organization_id
     where i.base_unit = l ->> 'base_unit';
    get diagnostics v_n = row_count;
    if v_n <> jsonb_array_length(p_payload -> 'lots') then
      raise exception 'donation lots reference unknown ingredients or mismatched base units' using errcode = 'P0422';
    end if;
    v_effect := jsonb_build_object('donation_id', v_target, 'status', v_status, 'lots_created', v_n);

  when 'DONATION_CANCELLED' then
    v_target := (p_payload ->> 'donation_id')::uuid;
    update cornucopia.donations set status = 'cancelled', cancelled_at = now(), cancel_reason = p_payload ->> 'reason'
     where id = v_target and organization_id = p_organization_id and status <> 'cancelled';
    if not found then
      raise exception 'donation % not found or already cancelled', v_target using errcode = 'P0409';
    end if;
    select coalesce(jsonb_agg(jsonb_build_object('lot_id', id, 'ingredient_id', ingredient_id,
             'removed_base', quantity_base, 'base_unit', base_unit, 'previous_status', status)), '[]'::jsonb)
      into v_effect
      from cornucopia.inventory_lots
     where donation_id = v_target and status in ('pledged','available');
    update cornucopia.inventory_lots set status = 'cancelled', quantity_base = 0
     where donation_id = v_target and status in ('pledged','available');
    v_effect := jsonb_build_object('donation_id', v_target, 'lots_removed', v_effect);

  when 'INVENTORY_ADJUSTED' then
    v_target := (p_payload ->> 'lot_id')::uuid;
    select * into v_lot from cornucopia.inventory_lots
     where id = v_target and organization_id = p_organization_id for update;
    if not found then
      raise exception 'inventory lot % not found', v_target using errcode = 'P0404';
    end if;
    if v_lot.status not in ('available','depleted') then
      raise exception 'inventory lot % is %, cannot adjust', v_target, v_lot.status using errcode = 'P0409';
    end if;
    if v_lot.base_unit <> p_payload ->> 'base_unit' then
      raise exception 'adjustment unit does not match lot base unit' using errcode = 'P0422';
    end if;
    if v_lot.quantity_base + (p_payload ->> 'delta_base')::numeric < 0 then
      raise exception 'adjustment would make lot % negative (% % available)', v_target, v_lot.quantity_base, v_lot.base_unit
        using errcode = 'P0422';
    end if;
    update cornucopia.inventory_lots
       set quantity_base = quantity_base + (p_payload ->> 'delta_base')::numeric,
           status = case when quantity_base + (p_payload ->> 'delta_base')::numeric = 0 then 'depleted' else 'available' end
     where id = v_target;
    v_effect := jsonb_build_object('lot_id', v_target, 'before_base', v_lot.quantity_base,
      'after_base', v_lot.quantity_base + (p_payload ->> 'delta_base')::numeric, 'base_unit', v_lot.base_unit);

  when 'INGREDIENT_EXPIRED' then
    v_target := (p_payload ->> 'lot_id')::uuid;
    select * into v_lot from cornucopia.inventory_lots
     where id = v_target and organization_id = p_organization_id for update;
    if not found or v_lot.status not in ('available','pledged') then
      raise exception 'inventory lot % not found or not available', v_target using errcode = 'P0409';
    end if;
    if p_payload ? 'quantity_base' and (p_payload ->> 'quantity_base')::numeric < v_lot.quantity_base then
      update cornucopia.inventory_lots set quantity_base = quantity_base - (p_payload ->> 'quantity_base')::numeric
       where id = v_target;
      v_effect := jsonb_build_object('lot_id', v_target, 'expired_base', (p_payload ->> 'quantity_base')::numeric,
                                     'remaining_base', v_lot.quantity_base - (p_payload ->> 'quantity_base')::numeric);
    else
      update cornucopia.inventory_lots set status = 'expired', quantity_base = 0 where id = v_target;
      v_effect := jsonb_build_object('lot_id', v_target, 'expired_base', v_lot.quantity_base, 'remaining_base', 0);
    end if;

  when 'VOLUNTEER_UNAVAILABLE' then
    v_target := (p_payload ->> 'volunteer_id')::uuid;
    update cornucopia.volunteers set available = false, unavailable_reason = p_payload ->> 'reason'
     where id = v_target and organization_id = p_organization_id and available;
    if not found then
      raise exception 'volunteer % not found or already unavailable', v_target using errcode = 'P0409';
    end if;
    v_effect := jsonb_build_object('volunteer_id', v_target, 'available', false);

  when 'DELIVERY_DELAYED' then
    v_target := (p_payload ->> 'delivery_id')::uuid;
    update cornucopia.deliveries
       set status = 'delayed', delay_minutes = delay_minutes + (p_payload ->> 'delay_minutes')::int,
           departs_at = departs_at + make_interval(mins => (p_payload ->> 'delay_minutes')::int),
           status_reason = p_payload ->> 'reason'
     where id = v_target and organization_id = p_organization_id and status in ('scheduled','delayed')
     returning jsonb_build_object('delivery_id', id, 'departs_at', departs_at, 'delay_minutes', delay_minutes)
      into v_effect;
    if v_effect is null then
      raise exception 'delivery % not found or not schedulable', v_target using errcode = 'P0409';
    end if;

  when 'DELIVERY_CANCELLED' then
    v_target := (p_payload ->> 'delivery_id')::uuid;
    update cornucopia.deliveries set status = 'cancelled', status_reason = p_payload ->> 'reason'
     where id = v_target and organization_id = p_organization_id and status in ('scheduled','delayed');
    if not found then
      raise exception 'delivery % not found or already final', v_target using errcode = 'P0409';
    end if;
    select jsonb_build_object('delivery_id', v_target,
             'affected_commitments', coalesce(jsonb_agg(id), '[]'::jsonb))
      into v_effect
      from cornucopia.commitments where delivery_id = v_target and status = 'active';

  when 'COMMITMENT_CHANGED' then
    v_target := (p_payload ->> 'commitment_id')::uuid;
    update cornucopia.commitments c
       set meals_count = coalesce((p_payload ->> 'meals_count')::int, c.meals_count),
           diet_requirements = coalesce(
             (select array_agg(x) from jsonb_array_elements_text(p_payload -> 'diet_requirements') x),
             case when p_payload ? 'diet_requirements' then '{}'::text[] end,
             c.diet_requirements),
           due_at = coalesce((p_payload ->> 'due_at')::timestamptz, c.due_at),
           status = coalesce(p_payload ->> 'status', c.status),
           version = c.version + 1
     where id = v_target and organization_id = p_organization_id and status = 'active'
     returning jsonb_build_object('commitment_id', id, 'meals_count', meals_count,
                'diet_requirements', diet_requirements, 'due_at', due_at, 'status', status, 'version', version)
      into v_effect;
    if v_effect is null then
      raise exception 'commitment % not found or not active', v_target using errcode = 'P0409';
    end if;

  when 'PREPARATION_CAPACITY_CHANGED' then
    v_target := (p_payload ->> 'team_id')::uuid;
    update cornucopia.preparation_teams t
       set capacity_portions_per_hour = coalesce((p_payload ->> 'capacity_portions_per_hour')::numeric, t.capacity_portions_per_hour),
           available_hours = coalesce((p_payload ->> 'available_hours')::numeric, t.available_hours),
           active = coalesce((p_payload ->> 'active')::boolean, t.active)
     where id = v_target and organization_id = p_organization_id
     returning jsonb_build_object('team_id', id, 'capacity_portions_per_hour', capacity_portions_per_hour,
                'available_hours', available_hours, 'active', active)
      into v_effect;
    if v_effect is null then
      raise exception 'preparation team % not found', v_target using errcode = 'P0404';
    end if;

  else
    raise exception 'unknown event type %', p_event_type using errcode = 'P0422';
  end case;

  insert into cornucopia.operational_state as s (organization_id, version) values (p_organization_id, 1)
  on conflict (organization_id) do update set version = s.version + 1, updated_at = now()
  returning version into v_version;

  insert into cornucopia.operational_events (id, organization_id, idempotency_key, event_type, payload, payload_hash,
                                             actor, correlation_id, effect, state_version)
  values (v_id, p_organization_id, p_idempotency_key, p_event_type, p_payload, v_hash,
          p_actor, p_correlation_id, v_effect, v_version);

  return jsonb_build_object('duplicate', false,
    'event', (select to_jsonb(e) from cornucopia.operational_events e where e.id = v_id));
end $$;

-- ------------------------------------------------------------- functions
revoke all on function cornucopia.current_actor() from public, anon, authenticated;
revoke all on function cornucopia.ensure_organization(text, text) from public, anon, authenticated;
revoke all on function cornucopia.ingest_event(uuid, text, text, jsonb, text, uuid) from public, anon, authenticated;
revoke all on function cornucopia.tg_audit_and_version() from public, anon, authenticated;
grant execute on function cornucopia.current_actor() to service_role;
grant execute on function cornucopia.ensure_organization(text, text) to service_role;
grant execute on function cornucopia.ingest_event(uuid, text, text, jsonb, text, uuid) to service_role;

notify pgrst, 'reload schema';
