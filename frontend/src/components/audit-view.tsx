"use client";

import { useEffect, useState } from "react";

import { fmtTime, ops, type Row } from "@/lib/ops";

export function AuditView() {
  const [rows, setRows] = useState<Row[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    ops<Row[]>("audit?limit=200").then(setRows).catch((e: unknown) => setError(e instanceof Error ? e.message : "failed"));
  }, []);
  return (
    <div className="overflow-x-auto rounded-lg border border-amber-900/20 bg-white/60">
      {error && <p role="alert" className="p-3 text-sm text-red-900">{error}</p>}
      <table className="min-w-full text-left text-sm">
        <caption className="sr-only">Audit log</caption>
        <thead className="border-b border-amber-900/20 text-xs uppercase tracking-wide text-stone-600">
          <tr>
            {["When", "Actor", "Action", "Record", "From event"].map((h) => (
              <th key={h} scope="col" className="px-3 py-2 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-amber-900/10">
          {rows.map((r) => (
            <tr key={String(r.id)}>
              <td className="whitespace-nowrap px-3 py-2">{fmtTime(r.at)}</td>
              <td className="px-3 py-2 font-mono text-xs">{String(r.actor)}</td>
              <td className="px-3 py-2">{String(r.action)}</td>
              <td className="px-3 py-2 font-mono text-xs">
                {String(r.table_name)}/{String(r.record_id).slice(0, 8)}
              </td>
              <td className="px-3 py-2 font-mono text-xs">{r.event_id ? String(r.event_id).slice(0, 8) : "—"}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={5} className="px-3 py-4 text-stone-500">
                No changes recorded yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
