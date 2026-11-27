"use client";

import { useEffect, useState } from "react";

import { ops } from "@/lib/ops";

interface Scenario {
  key: string;
  title: string;
  description: string;
}
interface Side {
  verdict: string;
  meals_planned: number;
  meals_requested: number;
  commitments_feasible: number;
  substitutions: number;
  commitments: { commitment_id: string; recipient: string; planned: number; requested: number; status: string }[];
  diagnosis: { explanation: string };
  wall_ms: number;
}
interface Result {
  scenario: Scenario;
  isolated: boolean;
  applied: string[];
  state_version: number;
  before: Side;
  after: Side;
  impact: { counts: Record<string, number> };
}

export function SimulationLab() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    ops<Scenario[]>("simulations/scenarios")
      .then(setScenarios)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "failed"));
  }, []);

  async function run(key: string) {
    setBusy(key);
    setError(null);
    try {
      setResult(await ops<Result>("simulations", { method: "POST", body: JSON.stringify({ scenario: key }) }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "simulation failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <p role="note" className="rounded-md border border-sky-800/30 bg-sky-50 p-3 text-sm text-sky-950">
        Simulations run the real optimizer on a copy of the current operational state. Nothing is written: production records, plans and approvals are untouched.
      </p>
      {error && (
        <p role="alert" className="rounded-md border border-red-800/30 bg-red-50 p-3 text-sm text-red-900">
          {error}
        </p>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {scenarios.map((s) => (
          <button key={s.key} type="button" disabled={busy !== null} onClick={() => void run(s.key)} className="rounded-xl border border-amber-900/20 bg-white/70 p-4 text-left hover:bg-amber-100 disabled:opacity-60">
            <span className="block font-semibold text-stone-900">{s.title}</span>
            <span className="mt-1 block text-xs text-stone-600">{s.description}</span>
            {busy === s.key && <span className="mt-2 block text-xs text-amber-900">Simulating…</span>}
          </button>
        ))}
      </div>
      {result && (
        <section aria-label="Simulation result" className="flex flex-col gap-4 rounded-xl border border-amber-900/20 bg-white/70 p-4">
          <div>
            <h2 className="text-lg font-semibold text-stone-900">{result.scenario.title}</h2>
            <p className="text-sm text-stone-700">{result.applied.join(" · ")}</p>
            <p className="text-xs text-stone-500">
              isolated simulation of state v{result.state_version} · affected: {Object.entries(result.impact.counts).map(([k, v]) => `${v} ${k}`).join(", ") || "nothing"}
            </p>
          </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {(["before", "after"] as const).map((side) => {
              const s = result[side];
              return (
                <div key={side} className="rounded-lg border border-amber-900/10 p-3">
                  <p className="text-xs uppercase tracking-wide text-stone-600">{side === "before" ? "Today" : "After the disruption (best recovery)"}</p>
                  <p className="font-mono text-3xl text-stone-900">
                    {s.meals_planned} / {s.meals_requested}
                  </p>
                  <p className="text-xs text-stone-600">
                    {s.verdict.replace("_", " ")} · {s.commitments_feasible} commitments fully met · {s.substitutions} substitution(s)
                  </p>
                  <ul className="mt-2 text-sm">
                    {s.commitments.map((c) => (
                      <li key={c.commitment_id}>
                        {c.recipient}: <span className="font-mono">{c.planned}</span>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-2 text-xs text-stone-700">{s.diagnosis.explanation}</p>
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
