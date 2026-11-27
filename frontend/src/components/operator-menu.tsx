"use client";

import { useEffect, useState } from "react";

import { DemoReset } from "@/components/demo-reset";

interface Me {
  username: string;
  display_name: string;
  role: string;
}

export function OperatorMenu() {
  const [me, setMe] = useState<Me | null>(null);
  useEffect(() => {
    fetch("/api/ops/auth/me", { cache: "no-store" })
      .then((r) => (r.ok ? (r.json() as Promise<Me>) : null))
      .then(setMe)
      .catch(() => setMe(null));
  }, []);
  if (!me) return null;
  return (
    <span className="flex flex-col gap-1 text-xs text-slate-400">
      <span className="text-sm text-slate-200">
        {me.display_name} <span className="ml-1 rounded-full bg-violet-500/20 px-2 py-0.5 text-[10px] uppercase tracking-wide text-violet-200">{me.role}</span>
      </span>
      <button
        type="button"
        className="self-start underline hover:text-white"
        onClick={() => {
          void fetch("/api/auth/logout", { method: "POST" }).then(() => {
            window.location.href = "/login";
          });
        }}
      >
        Sign out
      </button>
      <DemoReset role={me.role} />
    </span>
  );
}
