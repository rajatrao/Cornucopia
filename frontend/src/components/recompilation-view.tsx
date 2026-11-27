"use client";

import "@xyflow/react/dist/style.css";

import { Background, Controls, type Edge, MarkerType, type Node, ReactFlow } from "@xyflow/react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { fmtTime, ops } from "@/lib/ops";

interface ImpactNode {
  id: string;
  kind: string;
  label: string;
  role: string;
}
interface Recomp {
  execution: { id: string; status: string; attempt: number; result: Record<string, unknown> | null };
  event: { event_type: string; payload: Record<string, unknown>; effect: Record<string, unknown>; actor: string; created_at: string; state_version: number } | null;
  steps: { id: number; node: string; status: string; attempt: number; at: string }[];
  impact: { nodes: ImpactNode[]; edges: { source: string; target: string; rel: string }[]; counts: Record<string, number>; affected_commitments: string[] } | null;
  run: { solver_status: string; verdict: string; objectives: Record<string, number>; stages: { name: string; objective: number | null; status: string; wall_ms: number }[]; diagnosis: { explanation: string; shortfalls: { label: string; display: string }[] }; wall_ms: number; state_version: number } | null;
  candidates: { candidate: string; verdict: string; meals_planned: number }[];
  proposed_plan: { metrics: Record<string, number>; commitments: { commitment_id: string; recipient: string; planned: number; requested: number; status: string; risks: string[] }[]; substitutions: { recipe_id: string; ingredient_id: string; substitute_id: string; substitute_base: string }[] } | null;
  approval_request: { id: string; status: string; fingerprint: string } | null;
  changes: { id: number; kind: string; label: string; before: string; after: string }[];
  labels: Record<string, string>;
}
interface ExecRow {
  id: string;
  status: string;
  event_type: string | null;
  created_at: string;
}

const COLUMNS = ["donation", "lot", "volunteer", "team", "ingredient", "recipe", "batch", "meal", "delivery", "commitment"];
const COLOR: Record<string, string> = { origin: "#b91c1c", downstream: "#7c3aed", upstream: "#1d4ed8" };
const LB = 453.59237;

function graph(impact: Recomp["impact"]): { nodes: Node[]; edges: Edge[] } {
  if (!impact) return { nodes: [], edges: [] };
  const byCol: Record<string, ImpactNode[]> = {};
  for (const n of impact.nodes) (byCol[n.kind] ??= []).push(n);
  const cols = COLUMNS.filter((k) => byCol[k]);
  const nodes: Node[] = [];
  cols.forEach((k, ci) =>
    byCol[k].forEach((n, ri) =>
      nodes.push({
        id: n.id,
        position: { x: ci * 190, y: ri * 78 },
        data: { label: `${n.kind}\n${n.label}` },
        style: { whiteSpace: "pre-line", fontSize: 11, width: 160, border: `2px solid ${COLOR[n.role] ?? "#78716c"}`, background: n.role === "origin" ? "#fee2e2" : "#f5f3ff", color: "#1c1917", borderRadius: 8 },
      }),
    ),
  );
  const edges: Edge[] = impact.edges.map((e) => ({
    id: `${e.source}->${e.target}`,
    source: e.source,
    target: e.target,
    label: e.rel.replaceAll("_", " "),
    animated: e.rel !== "substitute_for",
    style: { stroke: e.rel === "substitute_for" ? "#1d4ed8" : "#7c3aed", strokeDasharray: e.rel === "substitute_for" ? "4 4" : undefined },
    labelStyle: { fontSize: 9 },
    markerEnd: { type: MarkerType.ArrowClosed },
  }));
  return { nodes, edges };
}

export function RecompilationView() {
  const params = useSearchParams();
  const [execs, setExecs] = useState<ExecRow[]>([]);
  const [selected, setSelected] = useState<string>(params.get("execution") ?? "");
  const [data, setData] = useState<Recomp | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    ops<ExecRow[]>("agent/executions?limit=40")
      .then((rows) => {
        setExecs(rows);
        setSelected((cur) => cur || rows.find((r) => r.status !== "completed")?.id || rows[0]?.id || "");
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "failed to load"));
  }, []);

  useEffect(() => {
    if (!selected) return;
    let alive = true;
    ops<Recomp>(`recompilation/${selected}`)
      .then((d) => alive && setData(d))
      .catch((e: unknown) => alive && setError(e instanceof Error ? e.message : "failed to load"));
    return () => {
      alive = false;
    };
  }, [selected]);

  const flow = useMemo(() => graph(data?.impact ?? null), [data]);
  const L = data?.labels ?? {};
  const before = data?.candidates.find((c) => c.candidate === "baseline");

  return (
    <div className="flex flex-col gap-6">
      {error && (
        <p role="alert" className="rounded-md border border-red-800/30 bg-red-50 p-3 text-sm text-red-900">
          {error}
        </p>
      )}
      <label htmlFor="exec-pick" className="text-sm text-stone-700">
        Recovery execution
        <select id="exec-pick" className="mt-1 block w-full rounded-md border border-amber-900/30 bg-white px-3 py-2 text-sm" value={selected} onChange={(e) => setSelected(e.target.value)}>
          {execs.map((x) => (
            <option key={x.id} value={x.id}>
              {(x.event_type ?? "event").replaceAll("_", " ").toLowerCase()} · {x.status.replace("_", " ")} · {fmtTime(x.created_at)}
            </option>
          ))}
        </select>
      </label>

      {data && (
        <>
          <section aria-label="Incoming event" className="rounded-xl border border-red-800/30 bg-red-50 p-4">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-red-800">Incoming operational event</p>
            <p className="mt-1 text-lg font-semibold text-stone-900">{data.event?.event_type.replaceAll("_", " ").toLowerCase()}</p>
            <p className="text-sm text-stone-700">
              reported by {data.event?.actor} · {fmtTime(data.event?.created_at)} · applied at state v{data.event?.state_version}
              {typeof data.event?.payload?.reason === "string" ? ` · “${data.event.payload.reason}”` : ""}
            </p>
          </section>

          <section aria-labelledby="graph-h" className="rounded-xl border border-amber-900/20 bg-white/70 p-4">
            <h2 id="graph-h" className="font-semibold text-stone-900">
              Affected dependency graph
            </h2>
            <p className="mb-2 text-xs text-stone-600">
              <span className="text-red-700">■ changed</span> · <span className="text-amber-700">■ downstream impact</span> · <span className="text-blue-700">■ upstream / substitute</span> ·{" "}
              {Object.entries(data.impact?.counts ?? {})
                .map(([k, v]) => `${v} ${k}`)
                .join(", ")}
            </p>
            <div className="h-[420px] rounded-lg border border-amber-900/10" aria-label="Dependency graph">
              <ReactFlow nodes={flow.nodes} edges={flow.edges} fitView nodesDraggable={false} nodesConnectable={false} proOptions={{ hideAttribution: true }}>
                <Background />
                <Controls showInteractive={false} />
              </ReactFlow>
            </div>
          </section>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <section aria-labelledby="plans-h" className="rounded-xl border border-amber-900/20 bg-white/70 p-4">
              <h2 id="plans-h" className="mb-2 font-semibold text-stone-900">
                Original vs. replacement plan
              </h2>
              {data.proposed_plan ? (
                <p className="mb-2 text-sm text-stone-700">
                  Without recovery: <span className="font-mono">{before?.meals_planned ?? "?"}</span> meals · Proposed: <span className="font-mono">{data.proposed_plan.metrics.meals_planned}</span> of {data.proposed_plan.metrics.meals_requested}
                </p>
              ) : (
                <p className="text-sm text-stone-600">No commitment affected by this event was at risk, so the plan was left unchanged.</p>
              )}
              <table className="min-w-full text-left text-sm">
                <caption className="sr-only">Commitments in the proposed plan</caption>
                <tbody className="divide-y divide-amber-900/10">
                  {data.proposed_plan?.commitments.map((c) => (
                    <tr key={c.commitment_id}>
                      <td className="py-1">{c.recipient}</td>
                      <td className="py-1 font-mono">
                        {c.planned} / {c.requested}
                      </td>
                      <td className="py-1 text-xs">{c.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.proposed_plan && data.proposed_plan.substitutions.length > 0 && (
                <ul className="mt-2 text-sm">
                  {data.proposed_plan.substitutions.map((s) => (
                    <li key={s.recipe_id + s.substitute_id}>
                      Substitution in {L[s.recipe_id]}: {L[s.ingredient_id]} → {(Number(s.substitute_base) / LB).toFixed(1)} lb {L[s.substitute_id]}
                    </li>
                  ))}
                </ul>
              )}
              {data.approval_request && (
                <Link href="/approvals" className="mt-3 inline-block text-sm font-medium text-amber-900 underline">
                  Approval: {data.approval_request.status} →
                </Link>
              )}
            </section>
            <section aria-labelledby="obj-h" className="rounded-xl border border-amber-900/20 bg-white/70 p-4">
              <h2 id="obj-h" className="mb-2 font-semibold text-stone-900">
                Optimization and constraint satisfaction
              </h2>
              {data.run ? (
                <>
                  <p className="text-sm">
                    CP-SAT {data.run.solver_status} · verdict <span className="font-medium">{data.run.verdict.replace("_", " ")}</span> (independent validator) · {data.run.wall_ms} ms
                  </p>
                  <ul className="mt-2 text-sm">
                    {data.run.stages.map((s) => (
                      <li key={s.name}>
                        {s.name.replaceAll("_", " ")}: <span className="font-mono">{s.objective ?? "—"}</span> <span className="text-xs text-stone-500">{s.status}</span>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-3 text-sm font-medium text-stone-900">Unresolved risks</p>
                  <p className="text-sm text-stone-700">{data.run.diagnosis.explanation}</p>
                </>
              ) : (
                <p className="text-sm text-stone-600">No optimization was needed for this event.</p>
              )}
            </section>
          </div>

          <section aria-labelledby="tl-h" className="rounded-xl border border-amber-900/20 bg-white/70 p-4">
            <h2 id="tl-h" className="mb-2 font-semibold text-stone-900">
              Agent execution timeline
            </h2>
            <ol aria-label="Agent timeline" className="flex flex-wrap gap-2">
              {data.steps.map((s) => (
                <li key={s.id} className={`rounded-full border px-2 py-0.5 text-xs ${s.status === "completed" ? "border-emerald-800/30 bg-emerald-50" : s.status === "interrupted" ? "border-violet-800/30 bg-violet-50" : s.status === "resumed" ? "border-sky-800/30 bg-sky-50" : "border-stone-300 bg-white"}`} title={`${s.status} · attempt ${s.attempt} · ${fmtTime(s.at)}`}>
                  {s.node}
                </li>
              ))}
            </ol>
          </section>
        </>
      )}
    </div>
  );
}
