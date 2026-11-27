"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { inputCls } from "@/components/field-input";

export function LoginForm() {
  const params = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const res = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, password }) });
    setBusy(false);
    if (!res.ok) {
      setError(((await res.json().catch(() => ({}))) as { error?: string }).error ?? "sign-in failed");
      return;
    }
    const next = params.get("next");
    // full navigation: route data prefetched before sign-in must not be reused
    window.location.assign(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
  }

  return (
    <form onSubmit={submit} aria-label="Sign in" className="flex flex-col gap-4 rounded-lg border border-amber-900/20 bg-white/60 p-5">
      <label htmlFor="username" className="block text-sm">
        <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-stone-600">Username</span>
        <input id="username" autoComplete="username" required className={inputCls} value={username} onChange={(e) => setUsername(e.target.value)} />
      </label>
      <label htmlFor="password" className="block text-sm">
        <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-stone-600">Password</span>
        <input id="password" type="password" autoComplete="current-password" required className={inputCls} value={password} onChange={(e) => setPassword(e.target.value)} />
      </label>
      {error && (
        <p role="alert" className="text-sm text-red-800">
          {error}
        </p>
      )}
      <button type="submit" disabled={busy} className="rounded-md bg-amber-800 px-4 py-2 text-sm font-medium text-amber-50 hover:bg-amber-900 disabled:opacity-50">
        {busy ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
