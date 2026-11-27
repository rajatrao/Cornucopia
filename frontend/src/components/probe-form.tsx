"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

export function ProbeForm() {
  const router = useRouter();
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const res = await fetch("/api/probes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note }),
    });
    if (!res.ok) {
      const body = (await res.json().catch(() => ({}))) as { error?: string };
      setError(body.error ?? `request failed (${res.status})`);
      return;
    }
    setNote("");
    startTransition(() => router.refresh());
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row" aria-label="Write a connectivity probe">
      <label htmlFor="probe-note" className="sr-only">
        Probe note
      </label>
      <input
        id="probe-note"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        maxLength={500}
        required
        placeholder="Write a test record through the Sprite"
        className="flex-1 rounded-md border border-amber-900/30 bg-white/70 px-3 py-2 text-sm text-stone-900 placeholder:text-stone-500 focus:outline-2 focus:outline-amber-700"
      />
      <button
        type="submit"
        disabled={pending || note.trim().length === 0}
        className="rounded-md bg-amber-800 px-4 py-2 text-sm font-medium text-amber-50 hover:bg-amber-900 disabled:opacity-50"
      >
        {pending ? "Writing…" : "Write probe"}
      </button>
      {error && (
        <p role="alert" className="text-sm text-red-800">
          {error}
        </p>
      )}
    </form>
  );
}
