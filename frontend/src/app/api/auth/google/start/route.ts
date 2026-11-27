import { NextResponse, type NextRequest } from "next/server";

import {
  AUTH_ENABLED,
  GOOGLE_CLIENT_ID,
  NEXT_COOKIE,
  STATE_COOKIE,
  VERIFIER_COOKIE,
  flowCookieOptions,
  pkceChallenge,
  publicOrigin,
  randomToken,
  safeNext,
} from "@/lib/auth/session";

/** Step 1 of sign-in: send the visitor to Google with a fresh state and PKCE verifier. */
export async function GET(request: NextRequest) {
  const origin = publicOrigin(request.nextUrl.origin);
  if (!AUTH_ENABLED || !GOOGLE_CLIENT_ID) {
    return NextResponse.redirect(`${origin}/signin?error=not_configured`);
  }
  const state = randomToken();
  const verifier = randomToken(48);
  const google = new URL("https://accounts.google.com/o/oauth2/v2/auth");
  google.search = new URLSearchParams({
    client_id: GOOGLE_CLIENT_ID,
    redirect_uri: `${origin}/api/auth/google/callback`,
    response_type: "code",
    scope: "openid email profile",
    state,
    code_challenge: await pkceChallenge(verifier),
    code_challenge_method: "S256",
    prompt: "select_account",
  }).toString();

  const response = NextResponse.redirect(google);
  const secure = origin.startsWith("https://");
  response.cookies.set(STATE_COOKIE, state, flowCookieOptions(secure));
  response.cookies.set(VERIFIER_COOKIE, verifier, flowCookieOptions(secure));
  response.cookies.set(NEXT_COOKIE, safeNext(request.nextUrl.searchParams.get("next")), flowCookieOptions(secure));
  return response;
}
