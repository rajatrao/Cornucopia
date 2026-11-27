"use client";

import { useEffect, useState } from "react";

import { fmtTime, ops, type Row } from "@/lib/ops";

export function InventoryView() {
  const [summary, setSummary] = useState<Row[]>([]);
  const [lots, setLots] = useState<Row[]>([]);
  const [donations, setDonations] = useState<Row[]>([]);
  const [ingredients, setIngredients] = useState<Row[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([ops<Row[]>("inventory/summary"), ops<Row[]>("inventory/lots"), ops<Row[]>("inventory/donations"), ops<Row[]>("resources/ingredients")])
      .then(([s, l, d, i]) => {
        setSummary(s);
        setLots(l);
        setDonations(d);
        setIngredients(i);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "failed to load"));
  }, []);

  const ing = (id: unknown) => String(ingredients.find((i) => i.id === id)?.name ?? "?");
  const don = (id: unknown) => String(donations.find((d) => d.id === id)?.description ?? "—");

  return (
    <div className="flex flex-col gap-8">
      {error && (
        <p role="alert" className="rounded-md border border-red-800/30 bg-red-50 p-3 text-sm text-red-900">
          {error}
        </p>
      )}
      <section aria-labelledby="stock-heading">
        <h2 id="stock-heading" className="mb-2 text-base font-semibold text-stone-900">
          Usable stock by ingredient
        </h2>
        <p className="mb-3 text-sm text-stone-600">Counts only received, unexpired lots. Pledged stock is shown separately and is not relied on.</p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {summary.map((s) => (
            <article key={String(s.ingredient_id)} className="rounded-lg border border-amber-900/20 bg-white/60 p-4" aria-label={`${s.ingredient_name} stock`}>
              <h3 className="font-medium text-stone-900">{String(s.ingredient_name)}</h3>
              <p className="mt-1 font-mono text-2xl text-stone-900">{String(s.available_display)}</p>
              <p className="mt-1 text-xs text-stone-600">
                {String(s.available_base)} {String(s.base_unit)} in {String(s.lots_available)} lot(s) · pledged {String(s.pledged_base)} · expiring within 48h{" "}
                {String(s.expiring_within_48h_base)}
              </p>
            </article>
          ))}
          {summary.length === 0 && <p className="text-sm text-stone-500">No ingredients yet.</p>}
        </div>
      </section>

      <section aria-labelledby="lots-heading">
        <h2 id="lots-heading" className="mb-2 text-base font-semibold text-stone-900">
          Inventory lots
        </h2>
        <div className="overflow-x-auto rounded-lg border border-amber-900/20 bg-white/60">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-amber-900/20 text-xs uppercase tracking-wide text-stone-600">
              <tr>
                {["Ingredient", "Reported", "Remaining (base)", "Status", "Expires", "Donation"].map((h) => (
                  <th key={h} scope="col" className="px-3 py-2 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-amber-900/10">
              {lots.map((l) => (
                <tr key={l.id}>
                  <td className="px-3 py-2">{ing(l.ingredient_id)}</td>
                  <td className="px-3 py-2 font-mono">
                    {String(l.reported_quantity)} {String(l.reported_unit)}
                  </td>
                  <td className="px-3 py-2 font-mono">
                    {String(l.quantity_base)} / {String(l.initial_quantity_base)} {String(l.base_unit)}
                  </td>
                  <td className="px-3 py-2">{String(l.status)}</td>
                  <td className="px-3 py-2">{fmtTime(l.expires_at)}</td>
                  <td className="px-3 py-2">{don(l.donation_id)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby="donations-heading">
        <h2 id="donations-heading" className="mb-2 text-base font-semibold text-stone-900">
          Donations
        </h2>
        <ul className="divide-y divide-amber-900/10 rounded-lg border border-amber-900/20 bg-white/60">
          {donations.map((d) => (
            <li key={d.id} className="flex flex-col gap-1 p-3 text-sm sm:flex-row sm:justify-between">
              <span>{String(d.description)}</span>
              <span className="font-mono text-xs text-stone-600">
                {String(d.status)} · {fmtTime(d.created_at)}
                {d.cancel_reason ? ` · ${String(d.cancel_reason)}` : ""}
              </span>
            </li>
          ))}
          {donations.length === 0 && <li className="p-3 text-sm text-stone-500">No donations yet. Report one from the Event Center.</li>}
        </ul>
      </section>
    </div>
  );
}
