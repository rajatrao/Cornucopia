"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { fmtTime, ops } from "@/lib/ops";

interface CC {
  organization: { name: string; slug: string };
  state_version: number;
  meals_committed: number;
  meals_feasible_now: number;
  committed_plan: { version_number: number; meals_planned: number; committed_at: string | null; fingerprint: string } | null;
  commitments: { commitment_id: string; recipient: string; requested: number; planned: number; status: string; limited_by: string[] }[];
  inventory: { ingredient_id: string; name: string; base_unit: string; required_base: string; available_base: string; coverage: number | null }[];
  shortages: { name: string; missing_base: string; base_unit: string }[];
  agent: { live_workers: number; last_seen_at: string | null; running: { id: string }[]; recent: { id: string; status: string; current_node: string | null; created_at: string }[] };
  pending_approvals: { id: string; escalated: boolean; created_at: string }[];
  recent_events: { id: string; event_type: string; actor: string; created_at: string; processing_status: string }[];
  notifications: { id: string; title: string; created_at: string }[];
}

const LB = 453.59237;
const qty = (v: string, unit: string) => (unit === "g" ? `${(Number(v) / LB).toFixed(1)} lb` : unit === "ml" ? `${(Number(v) / 1000).toFixed(1)} l` : `${Number(v)} ${unit}`);

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "good" | "bad" | "warn" }) {
  const color = tone === "good" ? "text-emerald-800" : tone === "bad" ? "text-red-800" : tone === "warn" ? "text-orange-600" : "text-stone-900";
  return (
    <div className="rounded-xl border border-amber-900/20 bg-white/70 p-4 shadow-sm">
      <dt className="text-xs uppercase tracking-wide text-stone-600">{label}</dt>
      <dd className={`mt-1 font-mono text-3xl ${color}`}>{value}</dd>
      {sub && <dd className="mt-1 text-xs text-stone-600">{sub}</dd>}
    </div>
  );
}

export function CommandCenter() {
  const [cc, setCc] = useState<CC | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = () =>
      ops<CC>("command-center")
        .then((d) => alive && (setCc(d), setError(null)))
        .catch((e: unknown) => alive && setError(e instanceof Error ? e.message : "failed to load"));
    void tick();
    const t = setInterval(tick, 6000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  if (error && !cc)
    return (
      <p role="alert" className="rounded-md border border-red-800/30 bg-red-50 p-3 text-sm text-red-900">
        {error}
      </p>
    );
  if (!cc) return <p className="text-sm text-stone-600">Loading operational state…</p>;

  const feasibleTone = cc.meals_feasible_now >= cc.meals_committed ? "good" : cc.meals_feasible_now === 0 ? "bad" : "warn";
  const chart = cc.inventory.filter((i) => i.coverage !== null).map((i) => ({ name: i.name, coverage: Math.round((i.coverage ?? 0) * 100) }));

  return (
    <div className="flex flex-col gap-8">
      <section aria-label="Active operation" className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.3em] text-amber-800">Active operation</p>
          <h2 className="text-2xl font-bold text-stone-900">{cc.organization.name}</h2>
        </div>
        <span className="font-mono text-xs text-stone-600">operational state v{cc.state_version}</span>
      </section>

      <dl aria-label="Operation summary" className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Tile label="Meals committed" value={String(cc.meals_committed)} />
        <Tile label="Feasible right now" value={String(cc.meals_feasible_now)} tone={feasibleTone} sub="without any recovery action" />
        <Tile label="Committed plan" value={cc.committed_plan ? `${cc.committed_plan.meals_planned}` : "—"} sub={cc.committed_plan ? `plan v${cc.committed_plan.version_number}` : "no plan committed yet"} />
        <Tile label="Pending approvals" value={String(cc.pending_approvals.length)} tone={cc.pending_approvals.length ? "warn" : undefined} />
        <Tile label="Agent" value={cc.agent.live_workers ? "online" : "idle"} tone={cc.agent.live_workers ? "good" : "warn"} sub={`${cc.agent.running.length} running · last heartbeat ${cc.agent.last_seen_at ? fmtTime(cc.agent.last_seen_at) : "—"}`} />
      </dl>

      {cc.shortages.length > 0 && (
        <section role="alert" aria-label="Resource shortages" className="rounded-xl border border-red-800/30 bg-red-50 p-4">
          <h3 className="font-semibold text-red-900">Resource shortages</h3>
          <ul className="mt-1 text-sm text-red-900">
            {cc.shortages.map((s) => (
              <li key={s.name}>
                {s.name}: {qty(s.missing_base, s.base_unit)} short of what every commitment needs
              </li>
            ))}
          </ul>
          {cc.pending_approvals.length > 0 && (
            <Link href="/approvals" className="mt-2 inline-block text-sm font-medium text-red-900 underline">
              Review the agent&apos;s recovery proposal →
            </Link>
          )}
        </section>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section aria-labelledby="inv-h" className="rounded-xl border border-amber-900/20 bg-white/70 p-4">
          <h3 id="inv-h" className="mb-2 font-semibold text-stone-900">
            Inventory health (stock vs. need, %)
          </h3>
          <div className="h-64" role="img" aria-label="Inventory coverage chart">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chart} margin={{ left: 0, right: 8, top: 8, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} />
                <YAxis tick={{ fontSize: 11 }} domain={[0, (max: number) => Math.max(150, max)]} />
                <Tooltip formatter={(v) => [`${v}%`, "coverage"]} />
                <ReferenceLine y={100} stroke="#7c3aed" strokeDasharray="4 4" />
                <Bar dataKey="coverage" radius={[4, 4, 0, 0]}>
                  {chart.map((d) => (
                    <Cell key={d.name} fill={d.coverage >= 100 ? "#10b981" : d.coverage > 0 ? "#f97316" : "#ef4444"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
        <section aria-labelledby="com-h" className="rounded-xl border border-amber-900/20 bg-white/70 p-4">
          <h3 id="com-h" className="mb-2 font-semibold text-stone-900">
            Commitments
          </h3>
          <ul className="flex flex-col gap-2 text-sm">
            {cc.commitments.map((c) => (
              <li key={c.commitment_id}>
                <div className="flex justify-between">
                  <span>{c.recipient}</span>
                  <span className="font-mono">
                    {c.planned} / {c.requested}
                  </span>
                </div>
                <div className="mt-1 h-2 overflow-hidden rounded bg-amber-100">
                  <div className={`h-2 ${c.status === "feasible" ? "bg-emerald-700" : c.planned ? "bg-orange-500" : "bg-red-600"}`} style={{ width: `${Math.min(100, (100 * c.planned) / Math.max(1, c.requested))}%` }} />
                </div>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <section aria-labelledby="ev-h" className="rounded-xl border border-amber-900/20 bg-white/70 p-4">
          <h3 id="ev-h" className="mb-2 font-semibold text-stone-900">
            Recent operational events
          </h3>
          <ul className="flex flex-col gap-1 text-sm">
            {cc.recent_events.map((e) => (
              <li key={e.id}>
                {e.event_type.replaceAll("_", " ").toLowerCase()} <span className="text-xs text-stone-500">· {e.processing_status} · {fmtTime(e.created_at)}</span>
              </li>
            ))}
          </ul>
        </section>
        <section aria-labelledby="ag-h" className="rounded-xl border border-amber-900/20 bg-white/70 p-4">
          <h3 id="ag-h" className="mb-2 font-semibold text-stone-900">
            Agent recovery executions
          </h3>
          <ul className="flex flex-col gap-1 text-sm">
            {cc.agent.recent.map((x) => (
              <li key={x.id}>
                <Link href={`/recompilation?execution=${x.id}`} className="underline decoration-amber-800/40 hover:text-amber-900">
                  {x.status.replace("_", " ")}
                </Link>{" "}
                <span className="text-xs text-stone-500">
                  · {x.current_node} · {fmtTime(x.created_at)}
                </span>
              </li>
            ))}
          </ul>
        </section>
        <section aria-labelledby="no-h" className="rounded-xl border border-amber-900/20 bg-white/70 p-4">
          <h3 id="no-h" className="mb-2 font-semibold text-stone-900">
            Notifications
          </h3>
          <ul className="flex flex-col gap-1 text-sm">
            {cc.notifications.map((n) => (
              <li key={n.id}>
                {n.title} <span className="text-xs text-stone-500">· {fmtTime(n.created_at)}</span>
              </li>
            ))}
            {cc.notifications.length === 0 && <li className="text-stone-500">Nothing yet.</li>}
          </ul>
        </section>
      </div>
    </div>
  );
}
