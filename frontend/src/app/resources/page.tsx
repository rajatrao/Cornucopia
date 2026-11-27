import { Suspense } from "react";

import { ResourceManager } from "@/components/resource-manager";

export const metadata = { title: "Resources · CORNUCOPIA" };

async function Manager({ searchParams }: { searchParams: Promise<{ kind?: string }> }) {
  const { kind } = await searchParams;
  return <ResourceManager initialKind={kind ?? "ingredients"} />;
}

export default function Page({ searchParams }: { searchParams: Promise<{ kind?: string }> }) {
  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-8">
      <h1 className="text-2xl font-bold tracking-tight text-stone-900">Resources</h1>
      <Suspense fallback={<p className="text-sm text-stone-600">Loading…</p>}>
        <Manager searchParams={searchParams} />
      </Suspense>
    </main>
  );
}
