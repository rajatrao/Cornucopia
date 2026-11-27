"use client";

import { useEffect, useState } from "react";

import { fmtTime, ops } from "@/lib/ops";

interface Candidate {
  name: string;
  description: string;
  verdict: string;
  fingerprint: string | null;
  meals_planned: number;
  commitments_feasible: number;
  substitutions_used: number;
  meals_rerouted: number;
  violations: string[];
  diff_vs_recommended: { changes: { kind: string }[]; meals_planned_delta: number } | null;
}

interface Report {
  state_version: number;
  solver_status: string;
  verdict: string;
  fingerprint: string | null;
  validation_checks: number;
  violations: string[];
  wall_ms: number;
  model_stats: Record<string, number>;
  objectives: Record<string, number>;
  stages: { name: string; status: string; objective: number | null; wall_ms: number; deterministic_time: number }[];
  plan: {
    metrics: Record<string, number>;
    commitments: { commitment_id: string; recipient: string; requested: number; planned: number; status: string; limited_by: string[]; risks: string[] }[];
    substitutions: { recipe_id: string; ingredient_id: string; substitute_id: string; replaced_base: string; substitute_base: string }[];
    routing: { commitment_id: string; delivery_id: string; meals: number }[];
  } | null;
  diagnosis: { fully_serviceable: boolean; explanation: string; shortfalls: { label: string; display: string; resource: string }[]; blocked: Record<string, string[]> };
  candidates: Candidate[];
}

interface RunOut {
  run_id: string;
  labels: Record<string, string>;
  report: Report;
}

interface RunSummary {
  id: string;
  state_version: number;
  requested_by: string;
  solver_status: string;
  verdict: string;
  objectives: Record<string, number>;
  wall_ms: string;
  created_at: string;
}

const LB = 453.59237;
const STAGE_LABEL: Record<string, string> = {
  commitments_met: "1. Commitments fully met (max)",
  meals_served: "2. Meals served (max)",
  plan_change: "3. Change vs. reference plan (min)",
  waste_mg: "4. Expiring stock left unused, mg (min)",
  delivery_disruption: "5. Delivery disruption (min)",
  due_priority: "6. Earlier-due priority (tie-break)",
};
const VERDICT_STYLE: Record<string, string> = {
  verified_feasible: "bg-emerald-100 text-emerald-900 border-emerald-800/30",
  verified_partial: "bg-orange-100 text-orange-800 border-orange-300",
  unverified: "bg-red-100 text-red-900 border-red-800/30",
  failed: "bg-red-100 text-red-900 border-red-800/30",
};

function Badge({ verdict }: { verdict: string }) {
  return <span className={`rounded-full border px-2 py-0.5 text-xs ${VERDICT_STYLE[verdict] ?? ""}`}>{verdict.replace("_", " ")}</span>;
}

export function OptimizerView() {
  const [opts, setOpts] = useState({ use_substitutions: true, allow_rerouting: true, include_pledged: false });
  const [result, setResult] = useState<RunOut | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    ops<RunSummary[]>("optimizer/runs?limit=10")
      .then(setRuns)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "failed to load runs"));
  }, []);

  async function runOptimizer() {
    setBusy(true);
    setError(null);
    try {
      const out = await ops<RunOut>("optimizer/runs", { method: "POST", body: JSON.stringify(opts) });
      setResult(out);
      setRuns(await ops<RunSummary[]>("optimizer/runs?limit=10"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "optimization failed");
    } finally {
      setBusy(false);
    }
  }

  const r = result?.report;
  const L = result?.labels ?? {};

  return (
    <div className="flex flex-col gap-8">
      <form
        aria-label="Optimizer settings"
        className="flex flex-col gap-3 rounded-lg border border-amber-900/20 bg-white/60 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          void runOptimizer();
        }}
      >
        <div className="flex flex-wrap gap-4 text-sm">
          {(
            [
              ["use_substitutions", "Allow ingredient substitutions"],
              ["allow_rerouting", "Allow moving meals between delivery routes"],
              ["include_pledged", "Count pledged (not yet received) donations"],
            ] as const
          ).map(([k, label]) => (
            <label key={k} className="flex items-center gap-2">
              <input type="checkbox" checked={opts[k]} onChange={(e) => setOpts((o) => ({ ...o, [k]: e.target.checked }))} />
              {label}
            </label>
          ))}
        </div>
        <div>
          <button type="submit" disabled={busy} className="rounded-md bg-amber-800 px-4 py-2 text-sm font-medium text-amber-50 hover:bg-amber-900 disabled:opacity-50">
            {busy ? "Solving…" : "Run CP-SAT optimizer"}
          </button>
        </div>
        <p className="text-xs text-stone-600">
          Hard constraints (diets, stock, kitchen capacity, routes) are never traded off. The result is a proposal; approval comes later.
        </p>
      </form>

      {error && (
        <p role="alert" className="rounded-md border border-red-800/30 bg-red-50 p-3 text-sm text-red-900">
          {error}
        </p>
      )}

      {r && (
        <section aria-label="Optimization result" className="flex flex-col gap-6">
          <div className="flex flex-wrap items-center gap-3">
            <Badge verdict={r.verdict} />
            <span className="font-mono text-2xl text-stone-900">
              {r.plan?.metrics.meals_planned ?? 0} / {r.plan?.metrics.meals_requested ?? 0} meals
            </span>
            <span className="font-mono text-xs text-stone-600">
              solver {r.solver_status} · {r.wall_ms} ms · {r.model_stats.variables} vars · {r.validation_checks} validator checks · state v{r.state_version} · fingerprint {r.fingerprint?.slice(0, 12)}
            </span>
          </div>

          <div role="note" aria-label="Diagnosis" className={`rounded-md border p-3 text-sm ${r.diagnosis.fully_serviceable ? "border-emerald-800/30 bg-emerald-50 text-emerald-900" : "border-orange-300 bg-orange-50 text-orange-900"}`}>
            <p className="font-medium">Diagnosis</p>
            <p>{r.diagnosis.explanation}</p>
            {Object.entries(r.diagnosis.blocked).map(([id, reasons]) => (
              <p key={id} className="text-xs">
                {L[id] ?? id}: {reasons.join("; ")}
              </p>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <section aria-labelledby="opt-c">
              <h2 id="opt-c" className="mb-2 text-base font-semibold text-stone-900">
                Proposed commitments
              </h2>
              <table className="min-w-full rounded-lg border border-amber-900/20 bg-white/60 text-left text-sm">
                <caption className="sr-only">Proposed commitments</caption>
                <tbody className="divide-y divide-amber-900/10">
                  {r.plan?.commitments.map((c) => (
                    <tr key={c.commitment_id}>
                      <td className="px-3 py-2">{c.recipient}</td>
                      <td className="px-3 py-2 font-mono">
                        {c.planned} / {c.requested}
                      </td>
                      <td className="px-3 py-2 text-xs">{c.status}</td>
                      <td className="px-3 py-2 text-xs">{[...c.limited_by, ...c.risks].join("; ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <h3 className="mb-1 mt-4 text-sm font-semibold text-stone-900">Substitutions</h3>
              <ul className="text-sm">
                {r.plan?.substitutions.map((s) => (
                  <li key={`${s.recipe_id}-${s.substitute_id}`}>
                    {L[s.recipe_id]}: {(Number(s.replaced_base) / LB).toFixed(2)} lb {L[s.ingredient_id]} → {(Number(s.substitute_base) / LB).toFixed(2)} lb {L[s.substitute_id]}
                  </li>
                ))}
                {r.plan?.substitutions.length === 0 && <li className="text-stone-500">None.</li>}
              </ul>
            </section>
            <section aria-labelledby="opt-o">
              <h2 id="opt-o" className="mb-2 text-base font-semibold text-stone-900">
                Lexicographic objectives
              </h2>
              <table className="min-w-full rounded-lg border border-amber-900/20 bg-white/60 text-left text-sm">
                <caption className="sr-only">Objective stages</caption>
                <tbody className="divide-y divide-amber-900/10">
                  {r.stages.map((s) => (
                    <tr key={s.name}>
                      <td className="px-3 py-2">{STAGE_LABEL[s.name] ?? s.name}</td>
                      <td className="px-3 py-2 font-mono">{s.objective ?? "—"}</td>
                      <td className="px-3 py-2 font-mono text-xs">{s.status}</td>
                      <td className="px-3 py-2 font-mono text-xs">{s.wall_ms} ms</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          </div>

          <section aria-labelledby="opt-cand">
            <h2 id="opt-cand" className="mb-2 text-base font-semibold text-stone-900">
              Alternative plans
            </h2>
            <div className="overflow-x-auto rounded-lg border border-amber-900/20 bg-white/60">
              <table className="min-w-full text-left text-sm">
                <caption className="sr-only">Alternative plans</caption>
                <thead className="border-b border-amber-900/20 text-xs uppercase tracking-wide text-stone-600">
                  <tr>
                    {["Candidate", "Verdict", "Meals", "Commitments met", "Substitutions", "Meals rerouted", "Differences vs. recommended"].map((h) => (
                      <th key={h} scope="col" className="px-3 py-2 font-medium">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-amber-900/10">
                  {r.candidates.map((c) => (
                    <tr key={c.name} title={c.description}>
                      <td className="px-3 py-2">{c.name.replace("_", " ")}</td>
                      <td className="px-3 py-2">
                        <Badge verdict={c.verdict} />
                      </td>
                      <td className="px-3 py-2 font-mono">{c.meals_planned}</td>
                      <td className="px-3 py-2 font-mono">{c.commitments_feasible}</td>
                      <td className="px-3 py-2 font-mono">{c.substitutions_used}</td>
                      <td className="px-3 py-2 font-mono">{c.meals_rerouted}</td>
                      <td className="px-3 py-2 text-xs">{c.diff_vs_recommended ? `${c.diff_vs_recommended.changes.length} changes, ${c.diff_vs_recommended.meals_planned_delta >= 0 ? "+" : ""}${c.diff_vs_recommended.meals_planned_delta} meals` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </section>
      )}

      <section aria-labelledby="runs-h">
        <h2 id="runs-h" className="mb-2 text-base font-semibold text-stone-900">
          Recent optimization runs
        </h2>
        <ul className="divide-y divide-amber-900/10 rounded-lg border border-amber-900/20 bg-white/60 text-sm">
          {runs.map((x) => (
            <li key={x.id} className="flex flex-wrap items-center gap-3 p-3">
              <Badge verdict={x.verdict} />
              <span className="font-mono">{x.objectives.meals_served ?? 0} meals</span>
              <span className="font-mono text-xs text-stone-600">
                {x.solver_status} · {x.wall_ms} ms · v{x.state_version} · {x.requested_by} · {fmtTime(x.created_at)}
              </span>
            </li>
          ))}
          {runs.length === 0 && <li className="p-3 text-stone-500">No runs yet.</li>}
        </ul>
      </section>
    </div>
  );
}
