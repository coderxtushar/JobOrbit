import { NextResponse, type NextRequest } from "next/server";

import { DEMO_COOKIE, DEMO_ENABLED, demoCookieOptions, isDemoKey, newDemoKey } from "@/lib/demo/session";

/** Hands each demo visitor a key on their first page load; does nothing outside the demo. */
export function proxy(request: NextRequest) {
  const response = NextResponse.next();
  if (!DEMO_ENABLED) return response;
  const current = request.cookies.get(DEMO_COOKIE)?.value;
  const secure = request.nextUrl.protocol === "https:";
  // Refreshed on every page load, so an active visitor keeps the same copy.
  response.cookies.set(DEMO_COOKIE, isDemoKey(current) ? current : newDemoKey(), demoCookieOptions(secure));
  return response;
}

export const config = {
  // Pages only: assets and the API proxy never need to mint a key.
  matcher: ["/((?!api/|_next/|icons/|favicon.ico|icon.svg|apple-icon.png).*)"],
};
