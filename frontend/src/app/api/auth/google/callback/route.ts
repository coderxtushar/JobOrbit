import { NextResponse, type NextRequest } from "next/server";

import {
  AUTH_ENABLED,
  GOOGLE_CLIENT_ID,
  GOOGLE_CLIENT_SECRET,
  NEXT_COOKIE,
  SESSION_COOKIE,
  STATE_COOKIE,
  VERIFIER_COOKIE,
  callBackend,
  flowCookieOptions,
  publicOrigin,
  safeNext,
  sessionCookieOptions,
} from "@/lib/auth/session";

type SessionResponse = { session_token: string; expires_at: string; is_new_user: boolean };

/** Step 2 of sign-in: check the state, trade the code for an ID token, open a session. */
export async function GET(request: NextRequest) {
  const origin = publicOrigin(request.nextUrl.origin);
  const secure = origin.startsWith("https://");
  const fail = (code: string) => {
    const response = NextResponse.redirect(`${origin}/signin?error=${encodeURIComponent(code)}`);
    for (const name of [STATE_COOKIE, VERIFIER_COOKIE, NEXT_COOKIE]) {
      response.cookies.set(name, "", { ...flowCookieOptions(secure), maxAge: 0 });
    }
    return response;
  };

  if (!AUTH_ENABLED || !GOOGLE_CLIENT_ID || !GOOGLE_CLIENT_SECRET) return fail("not_configured");
  const params = request.nextUrl.searchParams;
  if (params.get("error")) return fail(params.get("error") === "access_denied" ? "cancelled" : "google_error");

  const state = request.cookies.get(STATE_COOKIE)?.value;
  const verifier = request.cookies.get(VERIFIER_COOKIE)?.value;
  const code = params.get("code");
  // The state ties this callback to the browser that started sign-in (no login CSRF).
  if (!state || !verifier || !code || params.get("state") !== state) return fail("state_mismatch");

  let idToken: string | undefined;
  try {
    const exchange = await fetch("https://oauth2.googleapis.com/token", {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        code,
        client_id: GOOGLE_CLIENT_ID,
        client_secret: GOOGLE_CLIENT_SECRET,
        redirect_uri: `${origin}/api/auth/google/callback`,
        grant_type: "authorization_code",
        code_verifier: verifier,
      }),
      cache: "no-store",
    });
    idToken = exchange.ok ? ((await exchange.json()) as { id_token?: string }).id_token : undefined;
  } catch {
    return fail("google_unreachable");
  }
  if (!idToken) return fail("google_error");

  let created: Response;
  try {
    created = await callBackend("/api/auth/session", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ id_token: idToken, user_agent: (request.headers.get("user-agent") ?? "").slice(0, 300) }),
    });
  } catch {
    return fail("api_unreachable");
  }
  if (!created.ok) {
    const body = (await created.json().catch(() => ({}))) as { error?: { code?: string } };
    return fail(body.error?.code ?? "signin_failed");
  }
  const session = (await created.json()) as SessionResponse;

  const next = session.is_new_user ? "/profile?welcome=1" : safeNext(request.cookies.get(NEXT_COOKIE)?.value);
  const response = NextResponse.redirect(`${origin}${next}`);
  const maxAge = Math.max(60, Math.floor((Date.parse(session.expires_at) - Date.now()) / 1000));
  response.cookies.set(SESSION_COOKIE, session.session_token, sessionCookieOptions(secure, maxAge));
  for (const name of [STATE_COOKIE, VERIFIER_COOKIE, NEXT_COOKIE]) {
    response.cookies.set(name, "", { ...flowCookieOptions(secure), maxAge: 0 });
  }
  return response;
}
