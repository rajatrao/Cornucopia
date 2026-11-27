"use client";

import { useEffect, useState } from "react";

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
    <span className="flex items-center gap-2 text-xs text-stone-600">
      <span>
        {me.display_name} <span className="rounded bg-amber-100 px-1">{me.role}</span>
      </span>
      <button
        type="button"
        className="underline hover:text-amber-900"
        onClick={() => {
          void fetch("/api/auth/logout", { method: "POST" }).then(() => {
            window.location.href = "/login";
          });
        }}
      >
        Sign out
      </button>
    </span>
  );
}
