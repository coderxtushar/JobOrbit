import { NextResponse, type NextRequest } from "next/server";

import { AUTH_ENABLED, SEPARATE_DEMO, SESSION_COOKIE, isSessionToken } from "@/lib/auth/session";
import { DEMO_COOKIE, DEMO_ENABLED, demoCookieOptions, isDemoKey, newDemoKey } from "@/lib/demo/session";

/** Pages anyone may open without signing in. */
const PUBLIC_PAGES = new Set(["/", "/signin", "/privacy"]);

/**
 * Two jobs, depending on how the site is deployed:
 *
 * - Sign-in site (JOBORBIT_AUTH=google): workspace pages need a session, or a demo key
 *   from "Try the demo". Anyone else is sent to /signin and brought back afterwards. The
 *   API checks the session again on every call; this only spares a page of 401s.
 * - Demo-only site (JOBORBIT_DEMO=1): hands each visitor a demo key on first page load.
 */
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const secure = request.nextUrl.protocol === "https:";
  const demoKey = request.cookies.get(DEMO_COOKIE)?.value;

  if (AUTH_ENABLED) {
    const signedIn = isSessionToken(request.cookies.get(SESSION_COOKIE)?.value);
    const inDemo = SEPARATE_DEMO && isDemoKey(demoKey);
    if (!PUBLIC_PAGES.has(pathname) && !signedIn && !inDemo) {
      const signin = new URL("/signin", request.url);
      signin.searchParams.set("next", `${pathname}${search}`);
      return NextResponse.redirect(signin);
    }
    const response = NextResponse.next();
    // Keep an active demo visitor's private copy alive.
    if (inDemo && !signedIn) response.cookies.set(DEMO_COOKIE, demoKey, demoCookieOptions(secure));
    return response;
  }

  const response = NextResponse.next();
  if (!DEMO_ENABLED) return response;
  // Refreshed on every page load, so an active visitor keeps the same copy.
  response.cookies.set(DEMO_COOKIE, isDemoKey(demoKey) ? demoKey : newDemoKey(), demoCookieOptions(secure));
  return response;
}

export const config = {
  // Pages only: assets and the API proxy never need to mint a key or redirect.
  matcher: ["/((?!api/|_next/|icons/|favicon.ico|icon.svg|apple-icon.png).*)"],
};
