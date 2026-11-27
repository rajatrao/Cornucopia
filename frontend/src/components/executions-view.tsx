"use client";

import { useCallback, useEffect, useState } from "react";

import { fmtTime, ops } from "@/lib/ops";

interface Status {
  now: string;
  pending_events: number;
  executions_by_status: Record<string, number>;
  running: number;
  last_heartbeat_at: string | null;
  active_workers: string[];
}

interface Execution {
  id: string;
  event_id: string;
  event_type: string | null;
  thread_id: string;
  status: string;
  current_node: string | null;
  last_completed_node: string | null;
  attempt: number;
  retry_count: number;
  lease_owner: string | null;
  created_at: string;
  finished_at: string | null;
  result: Record<string, unknown> | null;
  error: string | null;
}

interface Step {
  id: number;
  attempt: number;
  node: string;
  status: string;
  detail: Record<string, unknown>;
  at: string;
}

interface Detail {
  execution: Execution;
  event: Record<string, unknown> | null;
  steps: Step[];
  checkpoints: { checkpoint_id: string; summary: Record<string, unknown>; created_at: string }[];
}

const STATUS_STYLE: Record<string, string> = {
  running: "bg-sky-100 text-sky-900 border-sky-800/30",
  awaiting_approval: "bg-violet-100 text-violet-900 border-violet-800/30",
  completed: "bg-emerald-100 text-emerald-900 border-emerald-800/30",
  escalated: "bg-amber-100 text-amber-900 border-amber-800/30",
  failed: "bg-red-100 text-red-900 border-red-800/30",
};
const STEP_STYLE: Record<string, string> = {
  completed: "text-emerald-800",
  failed: "text-red-800",
  retry: "text-amber-800",
  interrupted: "text-violet-800",
  resumed: "text-sky-800",
  claimed: "text-stone-600",
};

function Badge({ s }: { s: string }) {
  return <span className={`rounded-full border px-2 py-0.5 text-xs ${STATUS_STYLE[s] ?? "border-stone-300"}`}>{s.replace("_", " ")}</span>;
}

function stepNote(step: Step): string {
  const d = step.detail as Record<string, unknown>;
  if (d.error) return String(d.error);
  if (d.worker) return `worker ${String(d.worker)}`;
  if (d.decision) return `decision: ${String(d.decision)}`;
  const o = d.optimization as Record<string, unknown> | undefined;
  if (o) return `optimizer ${String(o.solver_status)} · ${String(o.verdict)} · ${String(o.meals_planned)} meals`;
  const a = d.assessment as Record<string, unknown> | undefined;
  if (a) return `${String(a.meals_at_risk)} of ${String(a.meals_requested)} meals at risk`;
  const i = d.impact as Record<string, unknown> | undefined;
  if (i) return `${String(i.affected_commitments)} commitment(s) affected`;
  if (d.waiting_for) return `waiting for ${String(d.waiting_for)}`;
  return "";
}

export function ExecutionsView() {
  const [status, setStatus] = useState<Status | null>(null);
  const [rows, setRows] = useState<Execution[]>([]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = useCallback(() => Promise.all([ops<Status>("agent/status"), ops<Execution[]>("agent/executions?limit=50")]), []);

  useEffect(() => {
    let alive = true;
    const tick = () =>
      fetchAll()
        .then(([s, r]) => {
          if (!alive) return;
          setStatus(s);
          setRows(r);
        })
        .catch((e: unknown) => alive && setError(e instanceof Error ? e.message : "failed to load"));
    void tick();
    const t = setInterval(tick, 4000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [fetchAll]);

  async function open(id: string) {
    try {
      setDetail(await ops<Detail>(`agent/executions/${id}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load execution");
    }
  }

  const result = detail?.execution.result as
    | { report?: { headline?: string; lines?: string[] }; outcome?: { status?: string; reasons?: string[] }; proposal?: { run_id?: string } }
    | null
    | undefined;

  return (
    <div className="flex flex-col gap-6">
      {error && (
        <p role="alert" className="rounded-md border border-red-800/30 bg-red-50 p-3 text-sm text-red-900">
          {error}
        </p>
      )}
      {status && (
        <dl aria-label="Agent runtime" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {[
            ["Pending events", String(status.pending_events)],
            ["Running executions", String(status.running)],
            ["Last heartbeat", status.last_heartbeat_at ? fmtTime(status.last_heartbeat_at) : "—"],
            ["By status", Object.entries(status.executions_by_status).map(([k, v]) => `${k} ${v}`).join(" · ") || "—"],
          ].map(([k, v]) => (
            <div key={k} className="rounded-lg border border-amber-900/20 bg-white/60 p-4">
              <dt className="text-xs uppercase tracking-wide text-stone-600">{k}</dt>
              <dd className="mt-1 font-mono text-sm text-stone-900">{v}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        <section aria-labelledby="exec-h" className="lg:col-span-2">
          <h2 id="exec-h" className="mb-2 text-base font-semibold text-stone-900">
            Agent executions
          </h2>
          <ul className="flex flex-col gap-2">
            {rows.map((x) => (
              <li key={x.id}>
                <button
                  type="button"
                  onClick={() => void open(x.id)}
                  aria-label={`Execution ${(x.event_type ?? "event").replaceAll("_", " ").toLowerCase()} ${x.status.replace("_", " ")}`}
                  className={`w-full rounded-md border bg-white/60 p-3 text-left text-sm hover:bg-amber-100 ${detail?.execution.id === x.id ? "border-amber-800" : "border-amber-900/20"}`}
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="font-medium">{(x.event_type ?? "event").replaceAll("_", " ").toLowerCase()}</span>
                    <Badge s={x.status} />
                  </span>
                  <span className="mt-1 block font-mono text-xs text-stone-600">
                    {x.current_node ?? "—"} · attempt {x.attempt} · retries {x.retry_count} · {fmtTime(x.created_at)}
                  </span>
                </button>
              </li>
            ))}
            {rows.length === 0 && <li className="text-sm text-stone-500">No executions yet.</li>}
          </ul>
        </section>

        <section aria-label="Execution detail" className="lg:col-span-3">
          {!detail && <p className="text-sm text-stone-500">Select an execution to see its workflow timeline.</p>}
          {detail && (
            <div className="flex flex-col gap-4">
              <div className="flex flex-wrap items-center gap-3">
                <Badge s={detail.execution.status} />
                <span className="font-mono text-xs text-stone-600">
                  {detail.execution.thread_id} · {detail.checkpoints.length} checkpoints · attempt {detail.execution.attempt}
                </span>
              </div>
              {result?.report?.lines && (
                <div className="rounded-md border border-amber-900/20 bg-white/60 p-3 text-sm">
                  <p className="font-medium">{result.report.headline}</p>
                  <ul className="mt-1 list-disc pl-5">
                    {result.report.lines.map((l) => (
                      <li key={l}>{l}</li>
                    ))}
                  </ul>
                </div>
              )}
              {result?.outcome?.reasons && (
                <div role="note" className="rounded-md border border-amber-800/30 bg-amber-50 p-3 text-sm text-amber-950">
                  <p className="font-medium">Escalated to operator</p>
                  <ul className="list-disc pl-5">
                    {result.outcome.reasons.map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                </div>
              )}
              {result?.proposal?.run_id && (
                <p className="rounded-md border border-violet-800/30 bg-violet-50 p-3 text-sm text-violet-950">
                  Recovery proposal (optimization run {result.proposal.run_id.slice(0, 8)}) is waiting for human approval.
                </p>
              )}
              {detail.execution.error && <p className="text-sm text-red-800">{detail.execution.error}</p>}
              <ol aria-label="Workflow timeline" className="flex flex-col gap-1 border-l-2 border-amber-900/20 pl-4">
                {detail.steps.map((s) => (
                  <li key={s.id} className="text-sm">
                    <span className={`font-medium ${STEP_STYLE[s.status] ?? ""}`}>{s.node}</span>{" "}
                    <span className="text-xs text-stone-500">
                      {s.status} · attempt {s.attempt} · {new Date(s.at).toLocaleTimeString()}
                    </span>
                    {stepNote(s) && <span className="block text-xs text-stone-700">{stepNote(s)}</span>}
                  </li>
                ))}
              </ol>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
