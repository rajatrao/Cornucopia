import { NextResponse } from "next/server";

import { ApiError, api } from "@/lib/api/server";

// Backend-for-frontend: the browser posts here; this handler (server side)
// validates input and forwards it to the Sprite API with the server-held token.
export async function POST(request: Request) {
  let note: unknown;
  try {
    ({ note } = (await request.json()) as { note?: unknown });
  } catch {
    return NextResponse.json({ error: "invalid JSON" }, { status: 400 });
  }
  if (typeof note !== "string" || note.trim().length < 1 || note.length > 500) {
    return NextResponse.json({ error: "note must be 1-500 characters" }, { status: 422 });
  }
  try {
    const probe = await api.createProbe(note.trim());
    return NextResponse.json(probe, { status: 201 });
  } catch (err) {
    const status = err instanceof ApiError ? err.status : 502;
    return NextResponse.json({ error: "backend request failed" }, { status: status >= 500 ? 502 : status });
  }
}
