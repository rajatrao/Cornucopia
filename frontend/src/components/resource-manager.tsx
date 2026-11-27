"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { FieldInput, type FormValue, fromRow, toBody } from "@/components/field-input";
import { fmtTime, ops, type Row } from "@/lib/ops";
import { RESOURCE_KINDS, type ResourceKind } from "@/lib/resource-config";

function cell(kind: ResourceKind, col: string, row: Row, refs: Record<string, Row[]>): string {
  const v = row[col];
  const field = kind.fields.find((f) => f.name === col);
  if (field?.type === "ref" && v) {
    const target = refs[field.ref ?? ""]?.find((r) => r.id === v);
    return target ? String(target.name ?? target.route_name ?? target.recipient) : String(v).slice(0, 8);
  }
  if (col.endsWith("_at")) return fmtTime(v);
  if (Array.isArray(v)) return v.length ? v.join(", ") : "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  return v === null || v === undefined || v === "" ? "—" : String(v);
}

export function ResourceManager({ initialKind }: { initialKind: string }) {
  const [kindName, setKindName] = useState(initialKind);
  const kind = RESOURCE_KINDS.find((k) => k.kind === kindName) ?? RESOURCE_KINDS[0];
  const [rows, setRows] = useState<Row[]>([]);
  const [refs, setRefs] = useState<Record<string, Row[]>>({});
  const [form, setForm] = useState<Record<string, FormValue>>({});
  const [editing, setEditing] = useState<Row | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refKinds = useMemo(() => [...new Set(kind.fields.filter((f) => f.ref).map((f) => f.ref!))], [kind]);

  const fetchAll = useCallback(async () => {
    const [list, ...refLists] = await Promise.all([
      ops<Row[]>(`resources/${kind.kind}`),
      ...refKinds.map((k) => ops<Row[]>(`resources/${k}`)),
    ]);
    return { list, refs: Object.fromEntries(refKinds.map((k, i) => [k, refLists[i]])) };
  }, [kind, refKinds]);

  const apply = useCallback((data: { list: Row[]; refs: Record<string, Row[]> }) => {
    setRows(data.list);
    setRefs(data.refs);
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
    const url = new URL(window.location.href);
    url.searchParams.set("kind", kind.kind);
    window.history.replaceState(null, "", url);
  }, [kind, fetchAll, apply]);

  function selectKind(next: string) {
    setKindName(next);
    setForm({});
    setEditing(null);
    setNotice(null);
    setError(null);
    setRows([]);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (editing) {
        await ops(`resources/${kind.kind}/${editing.id}`, { method: "PATCH", body: JSON.stringify(toBody(kind.fields, form, "update")) });
        setNotice("Saved.");
      } else {
        await ops(`resources/${kind.kind}`, { method: "POST", body: JSON.stringify(toBody(kind.fields, form, "create")) });
        setNotice("Created.");
      }
      setForm({});
      setEditing(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "request failed");
    } finally {
      setBusy(false);
    }
  }

  async function remove(row: Row) {
    if (!window.confirm(`Delete this ${kind.label.toLowerCase().replace(/s$/, "")}? This is recorded in the audit log.`)) return;
    setError(null);
    try {
      await ops(`resources/${kind.kind}/${row.id}`, { method: "DELETE" });
      setNotice("Deleted.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "delete failed");
    }
  }

  const visibleFields = editing ? kind.fields.filter((f) => f.editable) : kind.fields;

  return (
    <div className="flex flex-col gap-6">
      <nav aria-label="Resource types" className="flex flex-wrap gap-2">
        {RESOURCE_KINDS.map((k) => (
          <button
            key={k.kind}
            type="button"
            onClick={() => selectKind(k.kind)}
            aria-pressed={k.kind === kind.kind}
            className={`rounded-full border px-3 py-1 text-sm ${
              k.kind === kind.kind ? "border-amber-800 bg-amber-800 text-amber-50" : "border-amber-900/30 bg-white/70 text-stone-800 hover:bg-amber-100"
            }`}
          >
            {k.label}
          </button>
        ))}
      </nav>

      {kind.note && <p className="text-sm text-stone-600">{kind.note}</p>}
      {error && (
        <p role="alert" className="rounded-md border border-red-800/30 bg-red-50 p-3 text-sm text-red-900">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="rounded-md border border-emerald-800/30 bg-emerald-50 p-3 text-sm text-emerald-900">
          {notice}
        </p>
      )}

      <form onSubmit={submit} aria-label={`${editing ? "Edit" : "Add"} ${kind.label}`} className="grid grid-cols-1 gap-4 rounded-lg border border-amber-900/20 bg-white/60 p-4 sm:grid-cols-2">
        <h2 className="text-base font-semibold text-stone-900 sm:col-span-2">
          {editing ? `Edit ${kind.display(editing)}` : `Add to ${kind.label}`}
        </h2>
        {visibleFields.map((f) => (
          <div key={f.name} className={f.type === "multi" || f.type === "textarea" ? "sm:col-span-2" : ""}>
            <FieldInput id={`f-${f.name}`} field={f} value={form[f.name]} refs={refs} onChange={(v) => setForm((s) => ({ ...s, [f.name]: v }))} />
          </div>
        ))}
        <div className="flex gap-2 sm:col-span-2">
          <button type="submit" disabled={busy} className="rounded-md bg-amber-800 px-4 py-2 text-sm font-medium text-amber-50 hover:bg-amber-900 disabled:opacity-50">
            {editing ? "Save changes" : "Create"}
          </button>
          {editing && (
            <button type="button" onClick={() => { setEditing(null); setForm({}); }} className="rounded-md border border-amber-900/30 px-4 py-2 text-sm">
              Cancel
            </button>
          )}
        </div>
      </form>

      <div className="overflow-x-auto rounded-lg border border-amber-900/20 bg-white/60">
        <table className="min-w-full text-left text-sm">
          <caption className="sr-only">{kind.label}</caption>
          <thead className="border-b border-amber-900/20 text-xs uppercase tracking-wide text-stone-600">
            <tr>
              <th scope="col" className="px-3 py-2">
                <span className="sr-only">Actions</span>
              </th>
              {kind.columns.map((c) => (
                <th key={c} scope="col" className="px-3 py-2 font-medium">
                  {kind.fields.find((f) => f.name === c)?.label ?? c.replaceAll("_", " ")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-amber-900/10">
            {rows.length === 0 && (
              <tr>
                <td colSpan={kind.columns.length + 1} className="px-3 py-4 text-stone-500">
                  Nothing here yet.
                </td>
              </tr>
            )}
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="whitespace-nowrap px-3 py-2 text-left">
                  <button type="button" aria-label={`Edit ${kind.display(r)}`} className="mr-3 text-amber-900 underline" onClick={() => { setEditing(r); setForm(fromRow(kind.fields, r)); }}>
                    Edit
                  </button>
                  <button type="button" aria-label={`Delete ${kind.display(r)}`} className="text-red-800 underline" onClick={() => void remove(r)}>
                    Delete
                  </button>
                </td>
                {kind.columns.map((c) => (
                  <td key={c} className="px-3 py-2 align-top text-stone-900">
                    {cell(kind, c, r, refs)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
