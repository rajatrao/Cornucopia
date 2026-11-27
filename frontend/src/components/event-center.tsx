"use client";

import { useCallback, useEffect, useState } from "react";

import { inputCls } from "@/components/field-input";
import { DIETS, fmtTime, newKey, ops, type Row, UNITS } from "@/lib/ops";

type EventType =
  | "DONATION_CREATED"
  | "DONATION_CANCELLED"
  | "INVENTORY_ADJUSTED"
  | "INGREDIENT_EXPIRED"
  | "VOLUNTEER_UNAVAILABLE"
  | "DELIVERY_DELAYED"
  | "DELIVERY_CANCELLED"
  | "COMMITMENT_CHANGED"
  | "PREPARATION_CAPACITY_CHANGED";

const LABELS: Record<EventType, string> = {
  DONATION_CREATED: "New donation",
  DONATION_CANCELLED: "Donation cancelled",
  INVENTORY_ADJUSTED: "Inventory adjusted",
  INGREDIENT_EXPIRED: "Ingredient expired",
  VOLUNTEER_UNAVAILABLE: "Volunteer unavailable",
  DELIVERY_DELAYED: "Delivery delayed",
  DELIVERY_CANCELLED: "Delivery cancelled",
  COMMITMENT_CHANGED: "Commitment changed",
  PREPARATION_CAPACITY_CHANGED: "Preparation capacity changed",
};

interface Refs {
  ingredients: Row[];
  donors: Row[];
  donations: Row[];
  lots: Row[];
  volunteers: Row[];
  deliveries: Row[];
  commitments: Row[];
  teams: Row[];
}

interface EventRow extends Row {
  event_type: string;
  actor: string;
  created_at: string;
  processing_status: string;
  payload: Record<string, unknown>;
  effect: Record<string, unknown>;
  state_version: number;
  idempotency_key: string;
}

type V = Record<string, string>;

function Text({ id, label, value, onChange, type = "text", required = true }: { id: string; label: string; value: string | undefined; onChange: (v: string) => void; type?: string; required?: boolean }) {
  return (
    <label htmlFor={id} className="block">
      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-stone-600">
        {label}
        {required && <span className="text-red-800"> *</span>}
      </span>
      <input id={id} type={type} step={type === "number" ? "any" : undefined} min={type === "number" ? "0" : undefined} required={required} className={inputCls} value={value ?? ""} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

function Pick({ id, label, value, onChange, options, required = true, empty = "— none —" }: { id: string; label: string; value: string | undefined; onChange: (v: string) => void; options: { v: string; l: string }[]; required?: boolean; empty?: string }) {
  return (
    <label htmlFor={id} className="block">
      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-stone-600">
        {label}
        {required && <span className="text-red-800"> *</span>}
      </span>
      <select id={id} required={required} className={inputCls} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        <option value="">{required ? "Select…" : empty}</option>
        {options.map((o) => (
          <option key={o.v} value={o.v}>
            {o.l}
          </option>
        ))}
      </select>
    </label>
  );
}

const iso = (local: string | undefined) => (local ? new Date(local).toISOString() : undefined);
const clean = (o: Record<string, unknown>) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined && v !== ""));

export function EventCenter() {
  const [type, setType] = useState<EventType>("DONATION_CREATED");
  const [v, setV] = useState<V>({});
  const [lots, setLots] = useState<{ ingredient_id: string; quantity: string; unit: string; expires_at: string }[]>([
    { ingredient_id: "", quantity: "", unit: "lb", expires_at: "" },
  ]);
  const [diets, setDiets] = useState<string[] | null>(null);
  // Generated on first submit and reused on retries, so a double submit is a duplicate.
  const [key, setKey] = useState("");
  const [refs, setRefs] = useState<Refs | null>(null);
  const [events, setEvents] = useState<EventRow[]>([]);
  const [result, setResult] = useState<{ duplicate: boolean; event: EventRow } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const fetchAll = useCallback(async () => {
    const [ingredients, donors, donations, lotRows, volunteers, deliveries, commitments, teams, evs] = await Promise.all([
      ops<Row[]>("resources/ingredients"),
      ops<Row[]>("resources/donors"),
      ops<Row[]>("inventory/donations"),
      ops<Row[]>("inventory/lots"),
      ops<Row[]>("resources/volunteers"),
      ops<Row[]>("resources/deliveries"),
      ops<Row[]>("resources/commitments"),
      ops<Row[]>("resources/teams"),
      ops<EventRow[]>("events?limit=50"),
    ]);
    return { refs: { ingredients, donors, donations, lots: lotRows, volunteers, deliveries, commitments, teams }, evs };
  }, []);

  const apply = useCallback((d: { refs: Refs; evs: EventRow[] }) => {
    setRefs(d.refs);
    setEvents(d.evs);
  }, []);

  const load = useCallback(async () => {
    try {
      apply(await fetchAll());
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load");
    }
  }, [apply, fetchAll]);

  useEffect(() => {
    fetchAll()
      .then(apply)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "failed to load"));
  }, [fetchAll, apply]);

  const set = (k: string) => (val: string) => setV((s) => ({ ...s, [k]: val }));
  const ingName = (id: unknown) => String(refs?.ingredients.find((i) => i.id === id)?.name ?? "?");

  function reset(next: EventType) {
    setType(next);
    setV({});
    setDiets(null);
    setLots([{ ingredient_id: "", quantity: "", unit: "lb", expires_at: "" }]);
    setKey("");
    setResult(null);
    setError(null);
  }

  function payload(): Record<string, unknown> {
    switch (type) {
      case "DONATION_CREATED":
        return clean({
          type,
          description: v.description,
          donor_id: v.donor_id,
          received: v.received !== "pledged",
          expected_at: iso(v.expected_at),
          lots: lots.map((l) => clean({ ingredient_id: l.ingredient_id, quantity: l.quantity, unit: l.unit, expires_at: iso(l.expires_at) })),
        });
      case "DONATION_CANCELLED":
        return { type, donation_id: v.donation_id, reason: v.reason };
      case "INVENTORY_ADJUSTED":
        return { type, lot_id: v.lot_id, direction: v.direction ?? "remove", quantity: v.quantity, unit: v.unit, reason: v.reason };
      case "INGREDIENT_EXPIRED":
        return clean({ type, lot_id: v.lot_id, quantity: v.quantity, unit: v.quantity ? v.unit : undefined, reason: v.reason });
      case "VOLUNTEER_UNAVAILABLE":
        return { type, volunteer_id: v.volunteer_id, reason: v.reason };
      case "DELIVERY_DELAYED":
        return { type, delivery_id: v.delivery_id, delay_minutes: Number.parseInt(v.delay_minutes ?? "", 10), reason: v.reason };
      case "DELIVERY_CANCELLED":
        return { type, delivery_id: v.delivery_id, reason: v.reason };
      case "COMMITMENT_CHANGED":
        return clean({
          type,
          commitment_id: v.commitment_id,
          meals_count: v.meals_count ? Number.parseInt(v.meals_count, 10) : undefined,
          diet_requirements: diets ?? undefined,
          due_at: iso(v.due_at),
          status: v.status,
          reason: v.reason,
        });
      case "PREPARATION_CAPACITY_CHANGED":
        return clean({
          type,
          team_id: v.team_id,
          capacity_portions_per_hour: v.capacity,
          available_hours: v.hours,
          active: v.active === "" || v.active === undefined ? undefined : v.active === "true",
          reason: v.reason,
        });
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const k = key || newKey("evt");
    setKey(k);
    try {
      const res = await ops<{ duplicate: boolean; event: EventRow }>("events", {
        method: "POST",
        body: JSON.stringify({ idempotency_key: k, event: payload() }),
      });
      setResult(res);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "submit failed");
    } finally {
      setBusy(false);
    }
  }

  const opt = (rows: Row[] | undefined, label: (r: Row) => string, keep: (r: Row) => boolean = () => true) =>
    (rows ?? []).filter(keep).map((r) => ({ v: r.id, l: label(r) }));
  const lotOptions = opt(refs?.lots, (l) => `${ingName(l.ingredient_id)} · ${l.quantity_base} ${l.base_unit} · ${l.status}`, (l) => ["available", "pledged", "depleted"].includes(String(l.status)));
  const reason = <Text id="ev-reason" label="Reason" value={v.reason} onChange={set("reason")} />;

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
      <form onSubmit={submit} aria-label="Report operational event" className="flex flex-col gap-4 rounded-lg border border-amber-900/20 bg-white/60 p-4 lg:col-span-3">
        <Pick
          id="ev-type"
          label="What happened?"
          value={type}
          onChange={(x) => reset(x as EventType)}
          options={(Object.keys(LABELS) as EventType[]).map((k) => ({ v: k, l: LABELS[k] }))}
        />

        {type === "DONATION_CREATED" && (
          <>
            <Text id="ev-description" label="Description" value={v.description} onChange={set("description")} />
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Pick id="ev-donor" label="Donor" required={false} value={v.donor_id} onChange={set("donor_id")} options={opt(refs?.donors, (d) => String(d.name))} />
              <Pick id="ev-received" label="Status" value={v.received ?? "received"} onChange={set("received")} options={[{ v: "received", l: "Received now" }, { v: "pledged", l: "Pledged (not yet received)" }]} />
              <Text id="ev-expected" label="Expected at" type="datetime-local" required={false} value={v.expected_at} onChange={set("expected_at")} />
            </div>
            <fieldset className="flex flex-col gap-3">
              <legend className="text-xs font-medium uppercase tracking-wide text-stone-600">Items</legend>
              {lots.map((l, i) => (
                <div key={i} className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                  <div className="col-span-2">
                    <Pick id={`ev-lot-ing-${i}`} label="Ingredient" value={l.ingredient_id} onChange={(x) => setLots((s) => s.map((y, j) => (j === i ? { ...y, ingredient_id: x } : y)))} options={opt(refs?.ingredients, (r) => `${r.name} (${r.base_unit})`)} />
                  </div>
                  <Text id={`ev-lot-qty-${i}`} label="Quantity" type="number" value={l.quantity} onChange={(x) => setLots((s) => s.map((y, j) => (j === i ? { ...y, quantity: x } : y)))} />
                  <Pick id={`ev-lot-unit-${i}`} label="Unit" value={l.unit} onChange={(x) => setLots((s) => s.map((y, j) => (j === i ? { ...y, unit: x } : y)))} options={UNITS.map((u) => ({ v: u, l: u }))} />
                  <Text id={`ev-lot-exp-${i}`} label="Expires" type="datetime-local" required={false} value={l.expires_at} onChange={(x) => setLots((s) => s.map((y, j) => (j === i ? { ...y, expires_at: x } : y)))} />
                </div>
              ))}
              <button type="button" className="self-start text-sm text-amber-900 underline" onClick={() => setLots((s) => [...s, { ingredient_id: "", quantity: "", unit: "lb", expires_at: "" }])}>
                Add another item
              </button>
            </fieldset>
          </>
        )}

        {type === "DONATION_CANCELLED" && (
          <>
            <Pick id="ev-donation" label="Donation" value={v.donation_id} onChange={set("donation_id")} options={opt(refs?.donations, (d) => `${d.description} · ${d.status}`, (d) => d.status !== "cancelled")} />
            {reason}
          </>
        )}

        {(type === "INVENTORY_ADJUSTED" || type === "INGREDIENT_EXPIRED") && (
          <>
            <Pick id="ev-lot" label="Inventory lot" value={v.lot_id} onChange={set("lot_id")} options={lotOptions} />
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {type === "INVENTORY_ADJUSTED" && (
                <Pick id="ev-direction" label="Direction" value={v.direction ?? "remove"} onChange={set("direction")} options={[{ v: "remove", l: "Remove" }, { v: "add", l: "Add" }]} />
              )}
              <Text id="ev-qty" label={type === "INGREDIENT_EXPIRED" ? "Quantity (blank = whole lot)" : "Quantity"} type="number" required={type === "INVENTORY_ADJUSTED"} value={v.quantity} onChange={set("quantity")} />
              <Pick id="ev-unit" label="Unit" required={type === "INVENTORY_ADJUSTED" || Boolean(v.quantity)} value={v.unit} onChange={set("unit")} options={UNITS.map((u) => ({ v: u, l: u }))} />
            </div>
            {reason}
          </>
        )}

        {type === "VOLUNTEER_UNAVAILABLE" && (
          <>
            <Pick id="ev-volunteer" label="Volunteer" value={v.volunteer_id} onChange={set("volunteer_id")} options={opt(refs?.volunteers, (x) => `${x.name} (${x.role})`, (x) => x.available === true)} />
            {reason}
          </>
        )}

        {(type === "DELIVERY_DELAYED" || type === "DELIVERY_CANCELLED") && (
          <>
            <Pick id="ev-delivery" label="Delivery route" value={v.delivery_id} onChange={set("delivery_id")} options={opt(refs?.deliveries, (d) => `${d.route_name} · ${fmtTime(d.departs_at)} · ${d.status}`, (d) => ["scheduled", "delayed"].includes(String(d.status)))} />
            {type === "DELIVERY_DELAYED" && <Text id="ev-delay" label="Delay (minutes)" type="number" value={v.delay_minutes} onChange={set("delay_minutes")} />}
            {reason}
          </>
        )}

        {type === "COMMITMENT_CHANGED" && (
          <>
            <Pick id="ev-commitment" label="Commitment" value={v.commitment_id} onChange={set("commitment_id")} options={opt(refs?.commitments, (c) => `${c.recipient} · ${c.meals_count} meals`, (c) => c.status === "active")} />
            <p className="text-xs text-stone-600">Only fill in what changed. Blank fields stay as they are.</p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Text id="ev-meals" label="New meal count" type="number" required={false} value={v.meals_count} onChange={set("meals_count")} />
              <Text id="ev-due" label="New due time" type="datetime-local" required={false} value={v.due_at} onChange={set("due_at")} />
              <Pick id="ev-status" label="New status" required={false} empty="— unchanged —" value={v.status} onChange={set("status")} options={[{ v: "cancelled", l: "Cancelled" }, { v: "fulfilled", l: "Fulfilled" }]} />
            </div>
            <fieldset>
              <legend className="mb-1 text-xs font-medium uppercase tracking-wide text-stone-600">
                Dietary requirements{" "}
                <button type="button" className="ml-2 normal-case text-amber-900 underline" onClick={() => setDiets(diets === null ? [] : null)}>
                  {diets === null ? "change" : "leave unchanged"}
                </button>
              </legend>
              {diets !== null && (
                <div className="flex flex-wrap gap-2">
                  {DIETS.map((d) => (
                    <label key={d} className="flex items-center gap-1 rounded border border-amber-900/20 bg-white px-2 py-1 text-xs">
                      <input type="checkbox" checked={diets.includes(d)} onChange={(e) => setDiets(e.target.checked ? [...diets, d] : diets.filter((x) => x !== d))} />
                      {d}
                    </label>
                  ))}
                </div>
              )}
            </fieldset>
            {reason}
          </>
        )}

        {type === "PREPARATION_CAPACITY_CHANGED" && (
          <>
            <Pick id="ev-team" label="Team" value={v.team_id} onChange={set("team_id")} options={opt(refs?.teams, (t) => `${t.name} · ${t.capacity_portions_per_hour}/h × ${t.available_hours}h`)} />
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Text id="ev-capacity" label="Portions per hour" type="number" required={false} value={v.capacity} onChange={set("capacity")} />
              <Text id="ev-hours" label="Available hours" type="number" required={false} value={v.hours} onChange={set("hours")} />
              <Pick id="ev-active" label="Active" required={false} empty="— unchanged —" value={v.active} onChange={set("active")} options={[{ v: "true", l: "Active" }, { v: "false", l: "Inactive" }]} />
            </div>
            {reason}
          </>
        )}

        {error && (
          <p role="alert" className="rounded-md border border-red-800/30 bg-red-50 p-3 text-sm text-red-900">
            {error}
          </p>
        )}
        {result && (
          <div role="status" className="rounded-md border border-emerald-800/30 bg-emerald-50 p-3 text-sm text-emerald-900">
            <p className="font-medium">
              {result.duplicate ? "Already recorded (duplicate submission ignored)." : "Event journaled and applied."} State version {result.event.state_version}.
            </p>
            <pre className="mt-2 overflow-x-auto text-xs">{JSON.stringify(result.event.effect, null, 2)}</pre>
          </div>
        )}
        <div className="flex items-center gap-3">
          <button type="submit" disabled={busy} className="rounded-md bg-amber-800 px-4 py-2 text-sm font-medium text-amber-50 hover:bg-amber-900 disabled:opacity-50">
            {busy ? "Submitting…" : "Submit event"}
          </button>
          {result && (
            <button type="button" className="text-sm text-amber-900 underline" onClick={() => reset(type)}>
              Report another
            </button>
          )}
          {key && (
            <span className="font-mono text-xs text-stone-500" title="Resubmitting with the same key never applies the event twice">
              key {key.slice(0, 16)}…
            </span>
          )}
        </div>
      </form>

      <section aria-labelledby="journal-heading" className="lg:col-span-2">
        <h2 id="journal-heading" className="mb-2 text-base font-semibold text-stone-900">
          Event journal
        </h2>
        <ol className="flex flex-col gap-2">
          {events.length === 0 && <li className="text-sm text-stone-500">No events yet.</li>}
          {events.map((e) => (
            <li key={e.id} className="rounded-md border border-amber-900/20 bg-white/60 p-3 text-sm">
              <details>
                <summary className="cursor-pointer">
                  <span className="font-medium text-stone-900">{LABELS[e.event_type as EventType] ?? e.event_type}</span>
                  <span className="ml-2 font-mono text-xs text-stone-500">
                    v{e.state_version} · {e.processing_status} · {e.actor} · {fmtTime(e.created_at)}
                  </span>
                </summary>
                <pre className="mt-2 overflow-x-auto text-xs text-stone-700">{JSON.stringify({ payload: e.payload, effect: e.effect }, null, 2)}</pre>
              </details>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
