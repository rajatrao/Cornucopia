import { NextResponse } from "next/server";

import { forward } from "@/lib/api/server";
import { SESSION_COOKIE } from "@/lib/session-cookie";

// Exchanges credentials for a signed operator session. The token goes into an
// HttpOnly cookie: page JavaScript can never read it.
export async function POST(request: Request) {
  let body: { username?: unknown; password?: unknown };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return NextResponse.json({ error: "invalid JSON" }, { status: 400 });
  }
  if (typeof body.username !== "string" || typeof body.password !== "string") {
    return NextResponse.json({ error: "username and password are required" }, { status: 422 });
  }
  const res = await forward("POST", "/api/v1/auth/login", JSON.stringify({ username: body.username.trim().toLowerCase(), password: body.password }), false);
  if (!res.ok) {
    return NextResponse.json({ error: res.status === 401 ? "invalid username or password" : "sign-in failed" }, { status: res.status === 401 ? 401 : 502 });
  }
  const data = (await res.json()) as { token: string; expires_at: string; operator: { username: string; display_name: string; role: string } };
  const out = NextResponse.json({ operator: data.operator });
  out.cookies.set(SESSION_COOKIE, data.token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production" && !process.env.CORNUCOPIA_INSECURE_COOKIES,
    path: "/",
    expires: new Date(data.expires_at),
  });
  return out;
}
