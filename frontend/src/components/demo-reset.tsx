"use client";

import { useEffect, useRef, useState } from "react";

const RANK: Record<string, number> = { viewer: 0, operator: 1, approver: 2, admin: 3 };

interface ResetStatus {
  enabled: boolean;
  required_role: string | null;
  state: "idle" | "running" | "done" | "failed";
  step?: string;
  error?: string;
  organization?: string;
}

async function status(): Promise<ResetStatus | null> {
  const r = await fetch("/api/ops/admin/demo-reset", { cache: "no-store" });
  return r.ok ? ((await r.json()) as ResetStatus) : null;
}

/** "Reset demo" for operators whose role the deployment allows. Starts a
 *  fresh copy of the sample data; everyone signs in again afterwards. */
export function DemoReset({ role }: { role: string }) {
  const [info, setInfo] = useState<ResetStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    status().then(setInfo).catch(() => setInfo(null));
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, []);

  if (!info?.enabled || !info.required_role || (RANK[role] ?? -1) < (RANK[info.required_role] ?? 99)) return null;

  function watch() {
    timer.current = setInterval(() => {
      void status().then((s) => {
        if (!s) return;
        if (s.state === "running") setStep(s.step ?? "working");
        if (s.state === "done") {
          if (timer.current) clearInterval(timer.current);
          setStep("Done. Taking you to sign in…");
          void fetch("/api/auth/logout", { method: "POST" }).finally(() => window.location.assign("/login?reset=1"));
        }
        if (s.state === "failed") {
          if (timer.current) clearInterval(timer.current);
          (window as { __cnResetting?: boolean }).__cnResetting = false;
          setBusy(false);
          setStep(null);
          setError(s.error ?? "The reset failed. Nothing changed.");
        }
      });
    }, 2000);
  }

  async function start() {
    (window as { __cnResetting?: boolean }).__cnResetting = true;
    setBusy(true);
    setError(null);
    setStep("Starting");
    const r = await fetch("/api/ops/admin/demo-reset", { method: "POST", body: "{}" });
    if (r.status === 202 || r.status === 409) {
      watch();
      return;
    }
    (window as { __cnResetting?: boolean }).__cnResetting = false;
    setBusy(false);
    setStep(null);
    const body = (await r.json().catch(() => ({}))) as { detail?: string };
    setError(body.detail ?? `Reset refused (${r.status})`);
  }

  return (
    <>
      <button type="button" className="self-start underline hover:text-white" onClick={() => setOpen(true)}>
        Reset demo
      </button>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4" role="presentation">
          <div role="dialog" aria-modal="true" aria-labelledby="reset-title" className="w-full max-w-md rounded-xl bg-white p-6 text-slate-800 shadow-2xl">
            <h2 id="reset-title" className="text-lg font-semibold text-slate-900">
              Reset the demo?
            </h2>
            <p className="mt-2 text-sm">
              This loads a fresh copy of the Thanksgiving sample data: 500 meals committed, the rice donation not yet cancelled.
              Accounts and passwords stay the same, but everyone who is signed in will need to sign in again.
            </p>
            <p className="mt-2 text-sm text-slate-500">Nothing is deleted. Earlier runs stay in the audit history.</p>
            {step && (
              <p role="status" className="mt-4 flex items-center gap-2 rounded-md bg-violet-50 p-3 text-sm text-violet-900">
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-violet-300 border-t-violet-700" aria-hidden />
                {step.charAt(0).toUpperCase() + step.slice(1)}
              </p>
            )}
            {error && (
              <p role="alert" className="mt-4 rounded-md bg-red-50 p-3 text-sm text-red-900">
                {error}
              </p>
            )}
            <div className="mt-6 flex justify-end gap-2">
              <button type="button" disabled={busy} onClick={() => setOpen(false)} className="rounded-md border border-slate-300 px-4 py-2 text-sm disabled:opacity-50">
                Cancel
              </button>
              <button type="button" disabled={busy} onClick={() => void start()} className="rounded-md bg-red-700 px-4 py-2 text-sm font-medium text-white hover:bg-red-800 disabled:opacity-50">
                {busy ? "Resetting…" : "Reset demo"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
