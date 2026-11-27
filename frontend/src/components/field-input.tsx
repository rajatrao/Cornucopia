"use client";

import type { Field } from "@/lib/resource-config";
import type { Row } from "@/lib/ops";

export const inputCls =
  "w-full rounded-md border border-amber-900/30 bg-white px-3 py-2 text-sm text-stone-900 focus:outline-2 focus:outline-amber-700";

export type FormValue = string | string[] | boolean;

export function FieldInput({
  field,
  value,
  onChange,
  refs,
  id,
}: {
  field: Field;
  value: FormValue | undefined;
  onChange: (v: FormValue) => void;
  refs: Record<string, Row[]>;
  id: string;
}) {
  const label = (
    <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-stone-600">
      {field.label}
      {field.required ? <span className="text-red-800"> *</span> : null}
    </span>
  );
  const help = field.help ? <span className="mt-1 block text-xs text-stone-500">{field.help}</span> : null;

  if (field.type === "bool") {
    return (
      <label htmlFor={id} className="flex items-center gap-2 text-sm text-stone-800">
        <input id={id} type="checkbox" checked={value === true} onChange={(e) => onChange(e.target.checked)} />
        {field.label}
      </label>
    );
  }
  if (field.type === "multi") {
    const selected = Array.isArray(value) ? value : [];
    return (
      <fieldset>
        <legend className="mb-1 text-xs font-medium uppercase tracking-wide text-stone-600">{field.label}</legend>
        <div className="flex flex-wrap gap-2">
          {field.options?.map((o) => (
            <label key={o} className="flex items-center gap-1 rounded border border-amber-900/20 bg-white px-2 py-1 text-xs">
              <input
                type="checkbox"
                checked={selected.includes(o)}
                onChange={(e) => onChange(e.target.checked ? [...selected, o] : selected.filter((x) => x !== o))}
              />
              {o}
            </label>
          ))}
        </div>
        {help}
      </fieldset>
    );
  }
  let control: React.ReactNode;
  const str = typeof value === "string" ? value : "";
  if (field.type === "select" || field.type === "ref") {
    const opts =
      field.type === "select"
        ? (field.options ?? []).map((o) => ({ v: o, l: o }))
        : (refs[field.ref ?? ""] ?? []).map((r) => ({
            v: r.id,
            l: String(r.name ?? r.route_name ?? r.recipient ?? r.id),
          }));
    control = (
      <select id={id} className={inputCls} value={str} required={field.required} onChange={(e) => onChange(e.target.value)}>
        <option value="">{field.required ? "Select…" : "— none —"}</option>
        {opts.map((o) => (
          <option key={o.v} value={o.v}>
            {o.l}
          </option>
        ))}
      </select>
    );
  } else if (field.type === "textarea") {
    control = <textarea id={id} className={inputCls} rows={3} value={str} required={field.required} onChange={(e) => onChange(e.target.value)} />;
  } else {
    const type = field.type === "datetime" ? "datetime-local" : field.type === "text" ? "text" : "number";
    const step = field.type === "integer" ? "1" : field.type === "number" ? "any" : undefined;
    control = (
      <input
        id={id}
        type={type}
        step={step}
        min={field.type === "number" || field.type === "integer" ? "0" : undefined}
        className={inputCls}
        value={str}
        required={field.required}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }
  return (
    <label htmlFor={id} className="block">
      {label}
      {control}
      {help}
    </label>
  );
}

/** Convert form state into a JSON body; omits blanks so nothing is invented. */
export function toBody(fields: Field[], values: Record<string, FormValue>, mode: "create" | "update"): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    if (mode === "update" && !f.editable) continue;
    const v = values[f.name];
    if (v === undefined) continue;
    if (f.type === "bool") {
      out[f.name] = v === true;
    } else if (f.type === "multi") {
      out[f.name] = Array.isArray(v) ? v : [];
    } else if (typeof v === "string") {
      if (v.trim() === "") {
        if (mode === "update" && !f.required && (f.type === "ref" || f.type === "text")) out[f.name] = null;
        continue;
      }
      if (f.type === "integer") out[f.name] = Number.parseInt(v, 10);
      else if (f.type === "number") out[f.name] = v.trim();
      else if (f.type === "datetime") out[f.name] = new Date(v).toISOString();
      else out[f.name] = v.trim();
    }
  }
  return out;
}

export function fromRow(fields: Field[], row: Row): Record<string, FormValue> {
  const out: Record<string, FormValue> = {};
  for (const f of fields) {
    const v = row[f.name];
    if (f.type === "bool") out[f.name] = v === true;
    else if (f.type === "multi") out[f.name] = Array.isArray(v) ? (v as string[]) : [];
    else if (f.type === "datetime" && v) {
      const d = new Date(String(v));
      out[f.name] = new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    } else out[f.name] = v === null || v === undefined ? "" : String(v);
  }
  return out;
}
