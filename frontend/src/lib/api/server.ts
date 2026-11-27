import "server-only";

import type { components } from "./contract.gen";

/**
 * Server-side client for the CORNUCOPIA API on the Fly.io Sprite.
 *
 * `server-only` makes the build fail if this module is ever imported into a
 * Client Component, so the API token can never reach the browser. Neither
 * variable is NEXT_PUBLIC_, so Next.js never inlines them into client JS.
 * The browser has no knowledge of Supabase or the Sprites gateway at all.
 */

export type Liveness = components["schemas"]["Liveness"];
export type DbHealth = components["schemas"]["DbHealthOut"];
export type Probe = components["schemas"]["ProbeOut"];

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

function config(): { baseUrl: string; token: string | undefined } {
  const baseUrl = process.env.CORNUCOPIA_API_URL;
  if (!baseUrl) throw new ApiError(500, "CORNUCOPIA_API_URL is not configured");
  return { baseUrl: baseUrl.replace(/\/$/, ""), token: process.env.CORNUCOPIA_API_TOKEN };
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { baseUrl, token } = config();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body) headers.set("Content-Type", "application/json");
  // A Sprite that was paused wakes on the first request; an idempotent read is
  // retried once so a slow wake does not surface as an outage.
  const attempts = (init.method ?? "GET") === "GET" ? 2 : 1;
  let res: Response | undefined;
  for (let i = 0; i < attempts; i++) {
    try {
      res = await fetch(`${baseUrl}${path}`, { ...init, headers, cache: "no-store", signal: AbortSignal.timeout(15_000) });
      if (res.status < 500 || i === attempts - 1) break;
    } catch (err) {
      if (i === attempts - 1) throw err;
    }
  }
  if (!res) throw new ApiError(502, `API unreachable on ${path}`);
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new ApiError(res.status, `API ${res.status} on ${path}: ${detail.slice(0, 200)}`);
  }
  return (await res.json()) as T;
}

/** Raw pass-through used by the /api/ops proxy (status codes preserved). */
export async function forward(method: string, path: string, body?: string): Promise<Response> {
  const { baseUrl, token } = config();
  const headers = new Headers({ Accept: "application/json" });
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (body !== undefined) headers.set("Content-Type", "application/json");
  // Phase 2: one shared operator identity asserted by this trusted server.
  // Per-operator sign-in replaces this in Phase 6/8.
  headers.set("X-Cornucopia-Actor", process.env.CORNUCOPIA_ACTOR ?? "operator:console");
  try {
    return await fetch(`${baseUrl}${path}`, {
      method,
      headers,
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(30_000),
    });
  } catch {
    return new Response(JSON.stringify({ error: "backend unreachable" }), { status: 502 });
  }
}

export const api = {
  liveness: () => call<Liveness>("/health"),
  dbHealth: () => call<DbHealth>("/health/db"),
  listProbes: () => call<Probe[]>("/api/v1/system/probes"),
  createProbe: (note: string) =>
    call<Probe>("/api/v1/system/probes", { method: "POST", body: JSON.stringify({ note }) }),
};
