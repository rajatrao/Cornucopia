"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { fmtTime, ops, OpsError } from "@/lib/ops";

interface RequestRow {
  id: string;
  status: string;
  escalated: boolean;
  fingerprint: string;
  state_version: number;
  expires_at: string;
  created_at: string;
  execution_id: string | null;
  version_number: number | null;
  verdict: string | null;
  meals_planned: number | null;
  meals_requested: number | null;
  status_reason: string | null;
}

interface Detail {
  request: RequestRow & { report: { headline?: string; lines?: string[]; escalation?: string } };
  plan_version: { id: string; version_number: number; verdict: string; plan: { metrics: Record<string, number>; commitments: { commitment_id: string; recipient: string; planned: number; requested: number; status: string }[] } } | null;
  current_plan_version: { version_number: number } | null;
  changes: { id: number; kind: string; label: string; field: string; before: string; after: string }[];
  decisions: { id: string; operator_username: string; decision: string; accepted: boolean; refusal_reason: string | null; created_at: string; reason: string | null }[];
  operational_state_version: number;
  is_current: boolean;
}

const STATUS_STYLE: Record<string, string> = {
  pending: "bg-violet-100 text-violet-900 border-violet-800/30",
  approved: "bg-sky-100 text-sky-900 border-sky-800/30",
  committed: "bg-emerald-100 text-emerald-900 border-emerald-800/30",
  rejected: "bg-stone-200 text-stone-800 border-stone-500/30",
  stale: "bg-amber-100 text-amber-900 border-amber-800/30",
  expired: "bg-amber-100 text-amber-900 border-amber-800/30",
};
const REFUSAL: Record<string, string> = {
  unauthorized: "Your role cannot approve plans (approver role required). The attempt was recorded.",
  duplicate: "This plan was already decided.",
  not_pending: "This request is no longer pending.",
  expired: "The approval window has passed. The agent will need to propose again.",
  stale: "Operations changed after this plan was computed. It cannot be approved; a fresh proposal is needed.",
  fingerprint_mismatch: "The plan you reviewed is not the plan on record.",
  confirmation_required: "Tick the confirmation box to approve.",
};
const LB = 453.59237;

function fmtChange(kind: string, field: string, v: string): string {
  if ((kind === "allocation" || kind === "substitution") && /^-?\d+(\.\d+)?$/.test(v)) return `${(Number(v) / LB).toFixed(1)} lb`;
  if (field === "route" && v.length > 20) return `route ${v.slice(0, 8)}`;
  return v;
}

function Badge({ s }: { s: string }) {
  return <span className={`rounded-full border px-2 py-0.5 text-xs ${STATUS_STYLE[s] ?? ""}`}>{s}</span>;
}

export function ApprovalCenter() {
  const [rows, setRows] = useState<RequestRow[]>([]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const fetchRows = useCallback(() => ops<RequestRow[]>("approvals?limit=50"), []);

  useEffect(() => {
    let alive = true;
    const tick = () =>
      fetchRows()
        .then((r) => alive && setRows(r))
        .catch((e: unknown) => alive && setMessage({ tone: "bad", text: e instanceof Error ? e.message : "failed to load" }));
    void tick();
    const t = setInterval(tick, 5000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [fetchRows]);

  async function open(id: string) {
    setMessage(null);
    setConfirm(false);
    setReason("");
    setDetail(await ops<Detail>(`approvals/${id}`));
  }

  async function decide(decision: "approve" | "reject") {
    if (!detail) return;
    setBusy(true);
    setMessage(null);
    try {
      await ops(`approvals/${detail.request.id}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision, fingerprint: detail.request.fingerprint, state_version: detail.request.state_version, confirm: decision === "approve" ? confirm : false, reason: reason || null }),
      });
      setMessage({ tone: "ok", text: decision === "approve" ? "Approved. The agent on the Sprite will commit it atomically and verify again before applying." : "Rejected. Nothing will be committed." });
    } catch (e) {
      const code = e instanceof OpsError ? e.message : "";
      setMessage({ tone: "bad", text: REFUSAL[code] ?? (e instanceof Error ? e.message : "decision failed") });
    } finally {
      setBusy(false);
      setRows(await fetchRows());
      setDetail(await ops<Detail>(`approvals/${detail.request.id}`));
    }
  }

  const r = detail?.request;
  const pending = r?.status === "pending";

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
      <section aria-labelledby="req-h" className="lg:col-span-2">
        <h2 id="req-h" className="mb-2 text-base font-semibold text-stone-900">
          Recovery proposals
        </h2>
        <ul className="flex flex-col gap-2">
          {rows.map((x) => (
            <li key={x.id}>
              <button
                type="button"
                aria-label={`Proposal v${x.version_number ?? "?"} ${x.status}`}
                onClick={() => void open(x.id)}
                className={`w-full rounded-md border bg-white/60 p-3 text-left text-sm hover:bg-amber-100 ${r?.id === x.id ? "border-amber-800" : "border-amber-900/20"}`}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="font-medium">
                    Plan v{x.version_number} · {x.meals_planned ?? "?"} / {x.meals_requested ?? "?"} meals
                  </span>
                  <Badge s={x.status} />
                </span>
                <span className="mt-1 block text-xs text-stone-600">
                  {x.escalated ? "escalated · " : ""}
                  {x.verdict?.replace("_", " ")} · computed at v{x.state_version} · {fmtTime(x.created_at)}
                </span>
              </button>
            </li>
          ))}
          {rows.length === 0 && <li className="text-sm text-stone-500">No proposals yet. The agent creates them when operations change.</li>}
        </ul>
      </section>

      <section aria-label="Proposal detail" className="flex flex-col gap-4 lg:col-span-3">
        {!detail && <p className="text-sm text-stone-500">Select a proposal to review it.</p>}
        {detail && r && (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <Badge s={r.status} />
              {r.escalated && <span className="rounded-full border border-amber-800/30 bg-amber-100 px-2 py-0.5 text-xs text-amber-900">escalated</span>}
              <span className="font-mono text-xs text-stone-600">
                plan v{detail.plan_version?.version_number} · fingerprint {r.fingerprint.slice(0, 16)}… · computed at state v{r.state_version} (now v{detail.operational_state_version}) · expires {fmtTime(r.expires_at)}
              </span>
            </div>
            {!detail.is_current && pending && (
              <p role="note" className="rounded-md border border-amber-800/30 bg-amber-50 p-3 text-sm text-amber-950">
                Operations changed after this plan was computed; approving it will be refused as stale.
              </p>
            )}
            {r.status_reason && <p className="text-sm text-stone-700">Status: {r.status_reason}</p>}
            <div className="rounded-md border border-amber-900/20 bg-white/60 p-3 text-sm">
              <p className="font-medium">{r.report.headline}</p>
              <ul className="mt-1 list-disc pl-5">
                {(r.report.lines ?? []).map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
              {r.report.escalation && <p className="mt-2 text-amber-900">{r.report.escalation}</p>}
            </div>

            <table className="min-w-full rounded-lg border border-amber-900/20 bg-white/60 text-left text-sm">
              <caption className="p-2 text-left text-sm font-semibold text-stone-900">Commitments: current operations vs. this plan</caption>
              <tbody className="divide-y divide-amber-900/10">
                {detail.plan_version?.plan.commitments.map((c) => (
                  <tr key={c.commitment_id}>
                    <td className="px-3 py-2">{c.recipient}</td>
                    <td className="px-3 py-2 font-mono">
                      {c.planned} / {c.requested}
                    </td>
                    <td className="px-3 py-2 text-xs">{c.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <table className="min-w-full rounded-lg border border-amber-900/20 bg-white/60 text-left text-sm">
              <caption className="p-2 text-left text-sm font-semibold text-stone-900">Changes proposed</caption>
              <thead className="text-xs uppercase tracking-wide text-stone-600">
                <tr>
                  {["Kind", "What", "Before", "After"].map((h) => (
                    <th key={h} scope="col" className="px-3 py-1 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-amber-900/10">
                {detail.changes.map((c) => (
                  <tr key={c.id}>
                    <td className="px-3 py-2 text-xs">{c.kind}</td>
                    <td className="px-3 py-2">{c.label}</td>
                    <td className="px-3 py-2 font-mono">{fmtChange(c.kind, c.field, c.before)}</td>
                    <td className="px-3 py-2 font-mono">{fmtChange(c.kind, c.field, c.after)}</td>
                  </tr>
                ))}
                {detail.changes.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-3 py-2 text-stone-500">
                      No changes recorded.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>

            {message && (
              <p role={message.tone === "ok" ? "status" : "alert"} className={`rounded-md border p-3 text-sm ${message.tone === "ok" ? "border-emerald-800/30 bg-emerald-50 text-emerald-900" : "border-red-800/30 bg-red-50 text-red-900"}`}>
                {message.text}
              </p>
            )}

            {pending && (
              <div className="flex flex-col gap-3 rounded-lg border border-amber-900/20 bg-white/60 p-4">
                <label className="flex items-start gap-2 text-sm">
                  <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} className="mt-1" />
                  <span>
                    I have reviewed plan v{detail.plan_version?.version_number} (fingerprint {r.fingerprint.slice(0, 12)}) and confirm it should be committed to operations.
                  </span>
                </label>
                <label htmlFor="decision-reason" className="text-sm">
                  <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-stone-600">Reason (optional)</span>
                  <input id="decision-reason" className="w-full rounded-md border border-amber-900/30 bg-white px-3 py-2 text-sm" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
                </label>
                <div className="flex flex-wrap gap-2">
                  <button type="button" disabled={busy || !confirm} onClick={() => void decide("approve")} className="rounded-md bg-emerald-800 px-4 py-2 text-sm font-medium text-emerald-50 hover:bg-emerald-900 disabled:opacity-50">
                    Approve and commit
                  </button>
                  <button type="button" disabled={busy} onClick={() => void decide("reject")} className="rounded-md border border-red-800/40 px-4 py-2 text-sm text-red-900 hover:bg-red-50">
                    Reject
                  </button>
                  <Link href="/simulation" className="rounded-md border border-amber-900/30 px-4 py-2 text-sm text-stone-800 hover:bg-amber-100">
                    Simulate alternatives
                  </Link>
                </div>
              </div>
            )}

            <section aria-labelledby="dec-h">
              <h3 id="dec-h" className="mb-1 text-sm font-semibold text-stone-900">
                Decision history
              </h3>
              <ul className="text-sm">
                {detail.decisions.map((d) => (
                  <li key={d.id}>
                    {fmtTime(d.created_at)} · <span className="font-mono">{d.operator_username}</span> · {d.decision} · {d.accepted ? "accepted" : `refused (${d.refusal_reason})`}
                    {d.reason ? ` · “${d.reason}”` : ""}
                  </li>
                ))}
                {detail.decisions.length === 0 && <li className="text-stone-500">No decisions yet.</li>}
              </ul>
            </section>
          </>
        )}
      </section>
    </div>
  );
}
