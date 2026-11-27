"use client";

import { useCallback, useEffect, useState } from "react";

import { fmtTime, ops, type Row } from "@/lib/ops";

interface CommitmentPlan {
  commitment_id: string;
  recipient: string;
  requested: number;
  planned: number;
  status: "feasible" | "partial" | "infeasible";
  delivery_id: string | null;
  limited_by: string[];
  risks: string[];
  omitted_optional: string[];
}

interface Report {
  fingerprint: string;
  labels: Record<string, string>;
  validation: { valid: boolean; checks: number; violations: string[] };
  plan: {
    state_version: number;
    as_of: string;
    commitments: CommitmentPlan[];
    recipes: { recipe_id: string; portions: string; batches: string }[];
    teams: { team_id: string; portions: number; capacity: number }[];
    deliveries: { delivery_id: string; meals: number; capacity: number }[];
    shortages: { ingredient_id: string; required_base: string; available_base: string; missing_base: string }[];
    metrics: Record<string, number | string>;
  };
  ingredients: { ingredient_id: string; name: string; base_unit: string; required_base: string; available_base: string; planned_base: string }[];
  teams: { team_id: string; name: string; capacity_portions: number; notes: string[] }[];
  substitution_suggestions: { substitution_id: string; recipe_id: string; ingredient_id: string; substitute_id: string; ratio: string; max_replaceable_base: string }[];
}

interface ImpactReport {
  event_type: string;
  state_version: number;
  impact: {
    origins: string[];
    nodes: { id: string; kind: string; label: string; role: string }[];
    edges: { source: string; target: string; rel: string }[];
    affected_commitments: string[];
    counts: Record<string, number>;
  };
}

const LB = 453.59237;
function qty(base: string | number, unit: string): string {
  const n = Number(base);
  if (unit === "g") return `${(n / LB).toFixed(1)} lb`;
  if (unit === "ml") return n >= 1000 ? `${(n / 1000).toFixed(1)} l` : `${n.toFixed(0)} ml`;
  return `${n} ${unit}`;
}

const STATUS_STYLE: Record<string, string> = {
  feasible: "bg-emerald-100 text-emerald-900 border-emerald-800/30",
  partial: "bg-orange-100 text-orange-800 border-orange-300",
  infeasible: "bg-red-100 text-red-900 border-red-800/30",
};

const KIND_ORDER = ["donation", "lot", "volunteer", "team", "ingredient", "recipe", "batch", "meal", "delivery", "commitment"];

function Stat({ label, value, tone }: { label: string; value: string; tone?: "bad" | "good" }) {
  return (
    <div className="rounded-lg border border-amber-900/20 bg-white/60 p-4">
      <dt className="text-xs uppercase tracking-wide text-stone-600">{label}</dt>
      <dd className={`mt-1 font-mono text-2xl ${tone === "bad" ? "text-red-800" : tone === "good" ? "text-emerald-800" : "text-stone-900"}`}>{value}</dd>
    </div>
  );
}

export function CompilerView() {
  const [report, setReport] = useState<Report | null>(null);
  const [events, setEvents] = useState<Row[]>([]);
  const [impact, setImpact] = useState<ImpactReport | null>(null);
  const [eventId, setEventId] = useState("");
  const [pledged, setPledged] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const fetchReport = useCallback(
    (withPledged: boolean) => Promise.all([ops<Report>(`compiler/plan?include_pledged=${withPledged}`), ops<Row[]>("events?limit=30")]),
    [],
  );

  useEffect(() => {
    fetchReport(false)
      .then(([r, e]) => {
        setReport(r);
        setEvents(e);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "failed to compile"));
  }, [fetchReport]);

  async function recompile(withPledged: boolean) {
    setBusy(true);
    setError(null);
    try {
      const [r, e] = await fetchReport(withPledged);
      setReport(r);
      setEvents(e);
    } catch (err) {
      setError(err instanceof Error ? err.message : "failed to compile");
    } finally {
      setBusy(false);
    }
  }

  async function analyse(id: string) {
    setEventId(id);
    setImpact(null);
    if (!id) return;
    try {
      setImpact(await ops<ImpactReport>(`compiler/impact/${id}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "impact analysis failed");
    }
  }

  const L = report?.labels ?? {};
  const m = report?.plan.metrics;

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-wrap items-center gap-4">
        <button type="button" disabled={busy} onClick={() => void recompile(pledged)} className="rounded-md bg-amber-800 px-4 py-2 text-sm font-medium text-amber-50 hover:bg-amber-900 disabled:opacity-50">
          {busy ? "Compiling…" : "Recompile baseline plan"}
        </button>
        <label className="flex items-center gap-2 text-sm text-stone-800">
          <input
            type="checkbox"
            checked={pledged}
            onChange={(e) => {
              setPledged(e.target.checked);
              void recompile(e.target.checked);
            }}
          />
          Count pledged (not yet received) donations
        </label>
        {report && (
          <span className="font-mono text-xs text-stone-600">
            state v{report.plan.state_version} · {fmtTime(report.plan.as_of)} · fingerprint {report.fingerprint.slice(0, 12)}
          </span>
        )}
      </div>

      {error && (
        <p role="alert" className="rounded-md border border-red-800/30 bg-red-50 p-3 text-sm text-red-900">
          {error}
        </p>
      )}

      {report && m && (
        <>
          <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="Plan summary">
            <Stat label="Meals feasible" value={`${m.meals_planned} / ${m.meals_requested}`} tone={m.meals_planned === m.meals_requested ? "good" : "bad"} />
            <Stat label="Commitments fully met" value={`${m.commitments_feasible} / ${m.commitments_total}`} />
            <Stat label="Portions to cook" value={`${m.portions_planned} / ${m.prep_capacity_portions}`} />
            <Stat label="Validator" value={report.validation.valid ? `valid · ${report.validation.checks} checks` : "INVALID"} tone={report.validation.valid ? "good" : "bad"} />
          </dl>
          <p className="text-xs text-stone-600">
            This is a proposal computed by the deterministic baseline planner. Being feasible does not approve or commit anything.
          </p>
          {!report.validation.valid && (
            <ul role="alert" className="list-disc rounded-md border border-red-800/30 bg-red-50 p-3 pl-6 text-sm text-red-900">
              {report.validation.violations.map((v) => (
                <li key={v}>{v}</li>
              ))}
            </ul>
          )}

          <section aria-labelledby="commit-h">
            <h2 id="commit-h" className="mb-2 text-base font-semibold text-stone-900">
              Commitments
            </h2>
            <div className="overflow-x-auto rounded-lg border border-amber-900/20 bg-white/60">
              <table className="min-w-full text-left text-sm">
                <caption className="sr-only">Commitment feasibility</caption>
                <thead className="border-b border-amber-900/20 text-xs uppercase tracking-wide text-stone-600">
                  <tr>
                    {["Recipient", "Status", "Planned / requested", "Limited by", "Risks"].map((h) => (
                      <th key={h} scope="col" className="px-3 py-2 font-medium">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-amber-900/10">
                  {report.plan.commitments.map((c) => (
                    <tr key={c.commitment_id}>
                      <td className="px-3 py-2">{c.recipient}</td>
                      <td className="px-3 py-2">
                        <span className={`rounded-full border px-2 py-0.5 text-xs ${STATUS_STYLE[c.status]}`}>{c.status}</span>
                      </td>
                      <td className="px-3 py-2 font-mono">
                        {c.planned} / {c.requested}
                      </td>
                      <td className="px-3 py-2 text-xs">{c.limited_by.join("; ") || "—"}</td>
                      <td className="px-3 py-2 text-xs">{[...c.risks, ...c.omitted_optional.map((o) => `omits ${o}`)].join("; ") || "—"}</td>
                    </tr>
                  ))}
                  {report.plan.commitments.length === 0 && (
                    <tr>
                      <td colSpan={5} className="px-3 py-4 text-stone-500">
                        No active commitments.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section aria-labelledby="ing-h">
            <h2 id="ing-h" className="mb-2 text-base font-semibold text-stone-900">
              Ingredient balance
            </h2>
            <div className="overflow-x-auto rounded-lg border border-amber-900/20 bg-white/60">
              <table className="min-w-full text-left text-sm">
                <caption className="sr-only">Ingredient balance</caption>
                <thead className="border-b border-amber-900/20 text-xs uppercase tracking-wide text-stone-600">
                  <tr>
                    {["Ingredient", "Needed for all commitments", "Usable stock", "Allocated by plan", "Gap"].map((h) => (
                      <th key={h} scope="col" className="px-3 py-2 font-medium">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-amber-900/10">
                  {report.ingredients.map((i) => {
                    const gap = Number(i.required_base) - Number(i.available_base);
                    return (
                      <tr key={i.ingredient_id}>
                        <td className="px-3 py-2">{i.name}</td>
                        <td className="px-3 py-2 font-mono">{qty(i.required_base, i.base_unit)}</td>
                        <td className="px-3 py-2 font-mono">{qty(i.available_base, i.base_unit)}</td>
                        <td className="px-3 py-2 font-mono">{qty(i.planned_base, i.base_unit)}</td>
                        <td className={`px-3 py-2 font-mono ${gap > 0 ? "text-red-800" : "text-emerald-800"}`}>{gap > 0 ? `short ${qty(gap, i.base_unit)}` : "ok"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <section aria-labelledby="cap-h">
              <h2 id="cap-h" className="mb-2 text-base font-semibold text-stone-900">
                Preparation and delivery capacity
              </h2>
              <ul className="flex flex-col gap-2 text-sm">
                {report.teams.map((t) => {
                  const load = report.plan.teams.find((x) => x.team_id === t.team_id);
                  return (
                    <li key={t.team_id} className="rounded-md border border-amber-900/20 bg-white/60 p-3">
                      <span className="font-medium">{t.name}</span>: {load?.portions ?? 0} of {t.capacity_portions} portions
                      {t.notes.length > 0 && <span className="block text-xs text-amber-900">{t.notes.join("; ")}</span>}
                    </li>
                  );
                })}
                {report.plan.deliveries.map((d) => (
                  <li key={d.delivery_id} className="rounded-md border border-amber-900/20 bg-white/60 p-3">
                    <span className="font-medium">{L[d.delivery_id] ?? d.delivery_id}</span>: {d.meals} of {d.capacity} meals
                  </li>
                ))}
              </ul>
            </section>
            <section aria-labelledby="sub-h">
              <h2 id="sub-h" className="mb-2 text-base font-semibold text-stone-900">
                Valid substitutions for shortages
              </h2>
              <ul className="flex flex-col gap-2 text-sm">
                {report.substitution_suggestions.map((s) => (
                  <li key={`${s.substitution_id}-${s.recipe_id}`} className="rounded-md border border-amber-900/20 bg-white/60 p-3">
                    In <span className="font-medium">{L[s.recipe_id]}</span>, replace {L[s.ingredient_id]} with {L[s.substitute_id]} (×{s.ratio}), up to {qty(s.max_replaceable_base, "g")}
                  </li>
                ))}
                {report.substitution_suggestions.length === 0 && <li className="text-stone-500">None needed or none valid.</li>}
              </ul>
              <p className="mt-2 text-xs text-stone-600">Checked against recipe scope, every affected diet and spare stock. The optimizer decides whether to use them (Phase 4).</p>
            </section>
          </div>
        </>
      )}

      <section aria-labelledby="impact-h" className="flex flex-col gap-3">
        <h2 id="impact-h" className="text-base font-semibold text-stone-900">
          Impact of an operational event
        </h2>
        <label htmlFor="impact-event" className="text-sm text-stone-700">
          Event
          <select id="impact-event" className="mt-1 block w-full rounded-md border border-amber-900/30 bg-white px-3 py-2 text-sm" value={eventId} onChange={(e) => void analyse(e.target.value)}>
            <option value="">Select an event…</option>
            {events.map((e) => (
              <option key={e.id} value={e.id}>
                {String(e.event_type)} · {fmtTime(e.created_at)} · v{String(e.state_version)}
              </option>
            ))}
          </select>
        </label>
        {impact && (
          <div className="rounded-lg border border-amber-900/20 bg-white/60 p-4" aria-label="Impact analysis">
            <p className="text-sm text-stone-800">
              {impact.impact.nodes.length} dependent nodes, {impact.impact.affected_commitments.length} commitment(s) affected.
            </p>
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {KIND_ORDER.filter((k) => impact.impact.counts[k]).map((k) => (
                <div key={k}>
                  <h3 className="text-xs font-medium uppercase tracking-wide text-stone-600">
                    {k} ({impact.impact.counts[k]})
                  </h3>
                  <ul className="mt-1 text-sm">
                    {impact.impact.nodes
                      .filter((n) => n.kind === k)
                      .map((n) => (
                        <li key={n.id}>
                          {n.label} <span className="text-xs text-stone-500">{n.role}</span>
                        </li>
                      ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
