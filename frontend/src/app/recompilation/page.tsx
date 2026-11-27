import { Suspense } from "react";

import { RecompilationView } from "@/components/recompilation-view";

export const metadata = { title: "Reality Recompilation · CORNUCOPIA" };

export default function Page() {
  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-stone-900">Reality Recompilation</h1>
        <p className="text-sm text-stone-600">What changed, what it touches, and how the agent recompiled the plan.</p>
      </div>
      <Suspense>
        <RecompilationView />
      </Suspense>
    </main>
  );
}
