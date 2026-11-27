import { connection } from "next/server";
import { Suspense } from "react";

import { ProbeForm } from "@/components/probe-form";
import { api, type DbHealth, type Liveness, type Probe } from "@/lib/api/server";

async function load(): Promise<{
  live: Liveness | null;
  db: DbHealth | null;
  probes: Probe[];
  error: string | null;
}> {
  try {
    const [live, db, probes] = await Promise.all([api.liveness(), api.dbHealth(), api.listProbes()]);
    return { live, db, probes, error: null };
  } catch (err) {
    return { live: null, db: null, probes: [], error: err instanceof Error ? err.message : "unreachable" };
  }
}

function Stat({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return (
    <div className="rounded-lg border border-amber-900/20 bg-white/60 p-4">
      <dt className="text-xs uppercase tracking-wide text-stone-600">{label}</dt>
      <dd className={`mt-1 font-mono text-sm ${ok === false ? "text-red-800" : "text-stone-900"}`}>{value}</dd>
    </div>
  );
}

async function LiveSections() {
  await connection(); // always render with live backend state
  const { live, db, probes, error } = await load();

  return (
    <>

      <section aria-labelledby="runtime-heading" className="flex flex-col gap-3">
        <h2 id="runtime-heading" className="text-lg font-semibold text-stone-900">
          Runtime link
        </h2>
        {error ? (
          <p role="alert" className="rounded-md border border-red-800/30 bg-red-50 p-3 text-sm text-red-900">
            Backend unreachable: {error}
          </p>
        ) : (
          <dl className="grid grid-cols-1 gap-3 sm:grid-cols-4">
            <Stat label="Runtime" value={live?.runtime ?? "?"} />
            <Stat label="Transport" value={live?.transport ?? "?"} />
            <Stat label="Database" value={db?.status ?? "?"} ok={db?.status === "ok"} />
            <Stat label="DB latency" value={db ? `${db.latency_ms} ms` : "?"} />
          </dl>
        )}
      </section>

      <section aria-labelledby="probe-heading" className="flex flex-col gap-3">
        <h2 id="probe-heading" className="text-lg font-semibold text-stone-900">
          Connectivity probes
        </h2>
        <p className="text-sm text-stone-700">
          Browser → Next.js server → Sprite API → Sprites Supabase connector → Supabase.
        </p>
        <ProbeForm />
        <ul className="divide-y divide-amber-900/10 rounded-lg border border-amber-900/20 bg-white/60">
          {probes.length === 0 && <li className="p-3 text-sm text-stone-600">No probes yet.</li>}
          {probes.map((p) => (
            <li key={p.id} className="flex flex-col gap-1 p-3 text-sm sm:flex-row sm:justify-between">
              <span className="text-stone-900">{p.note}</span>
              <span className="font-mono text-xs text-stone-600">
                {p.source} · {new Date(p.created_at).toISOString()}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col gap-8 px-6 py-12">
      <header>
        <p className="text-xs font-semibold uppercase tracking-[0.3em] text-amber-800">Autonomous resource compiler</p>
        <h1 className="mt-2 text-4xl font-bold tracking-tight text-stone-900">CORNUCOPIA</h1>
        <p className="mt-1 text-stone-700">When resources change, the feast goes on.</p>
      </header>
      <Suspense fallback={<p className="text-sm text-stone-600">Contacting the Sprite…</p>}>
        <LiveSections />
      </Suspense>
    </main>
  );
}
