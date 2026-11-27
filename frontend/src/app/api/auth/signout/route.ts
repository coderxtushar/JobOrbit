import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE, callBackend, isSessionToken, publicOrigin, sessionCookieOptions } from "@/lib/auth/session";

/** Ends this browser's session on the API and clears the cookie. POST only (no link-CSRF). */
export async function POST(request: NextRequest) {
  const origin = publicOrigin(request.nextUrl.origin);
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (isSessionToken(token)) {
    await callBackend("/api/auth/session", { method: "DELETE", session: token }).catch(() => undefined);
  }
  const response = NextResponse.redirect(`${origin}/`, { status: 303 });
  response.cookies.set(SESSION_COOKIE, "", { ...sessionCookieOptions(origin.startsWith("https://")), maxAge: 0 });
  return response;
}
