import { NextResponse } from "next/server";

import { forward } from "@/lib/api/server";

// Backend-for-frontend proxy for operational endpoints. The browser never
// sees the Sprite URL or token; only whitelisted API paths are reachable and
// the backend re-validates every body with its typed schemas.
const ALLOWED = /^(organization|resources\/[a-z-]+(\/[0-9a-f-]{36})?|inventory\/(summary|lots|donations)|events(\/[0-9a-f-]{36})?|audit|compiler\/(plan|graph|impact\/[0-9a-f-]{36})|optimizer\/runs(\/[0-9a-f-]{36})?|agent\/(status|executions(\/[0-9a-f-]{36})?))$/;
const MAX_BODY = 64 * 1024;

async function handle(request: Request, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const joined = path.join("/");
  if (!ALLOWED.test(joined)) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  let body: string | undefined;
  if (request.method === "POST" || request.method === "PATCH") {
    body = await request.text();
    if (body.length > MAX_BODY) return NextResponse.json({ error: "body too large" }, { status: 413 });
    try {
      JSON.parse(body);
    } catch {
      return NextResponse.json({ error: "invalid JSON" }, { status: 400 });
    }
  }
  const url = new URL(request.url);
  const params = new URLSearchParams();
  for (const key of ["limit", "include_pledged"]) {
    const v = url.searchParams.get(key);
    if (v !== null && /^[a-z0-9]{1,8}$/.test(v)) params.set(key, v);
  }
  const query = params.size ? `?${params}` : "";
  const res = await forward(request.method, `/api/v1/${joined}${query}`, body);
  return new NextResponse(res.status === 204 ? null : await res.text(), {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}

export { handle as GET, handle as POST, handle as PATCH, handle as DELETE };
