// Client-safe helpers for the /api/ops proxy. No secrets here.

export type Row = Record<string, unknown> & { id: string };

export class OpsError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

function describe(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).slice(1).join(".") || "body"}: ${d.msg}`)
      .join("; ");
  }
  if (detail && typeof detail === "object" && "code" in detail && !("message" in detail)) return String((detail as { code: unknown }).code);
  if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message);
  return "request failed";
}

export async function ops<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api/ops/${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
    cache: "no-store",
  });
  if (res.status === 401 && typeof window !== "undefined") {
    window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail = data && typeof data === "object" && "detail" in data ? (data as { detail: unknown }).detail : (data as { error?: string })?.error;
    throw new OpsError(res.status, describe(detail));
  }
  return data as T;
}

export const UNITS = ["g", "kg", "oz", "lb", "ml", "l", "tsp", "tbsp", "cup", "fl_oz", "qt", "gal", "each", "portion"] as const;
export const DIETS = ["vegetarian", "vegan", "gluten_free", "nut_free", "dairy_free", "halal"] as const;
export const ATTRIBUTES = [
  "meat", "pork", "poultry", "fish", "shellfish", "dairy", "egg", "gluten", "nuts", "peanuts", "soy", "sesame", "alcohol", "animal_product",
] as const;

export function newKey(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

export function fmtTime(v: unknown): string {
  if (!v) return "—";
  const d = new Date(String(v));
  return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleString();
}
