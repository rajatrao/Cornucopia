import { Suspense } from "react";

import { LoginForm } from "@/components/login-form";

export const metadata = { title: "Sign in · CORNUCOPIA" };

export default function Page() {
  return (
    <main className="mx-auto flex min-h-[70vh] max-w-sm flex-col justify-center gap-6 px-6 py-12">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.3em] text-amber-800">Autonomous resource compiler</p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-stone-900">CORNUCOPIA</h1>
        <p className="mt-1 text-stone-700">When resources change, the feast goes on.</p>
      </div>
      <Suspense>
        <LoginForm />
      </Suspense>
    </main>
  );
}
