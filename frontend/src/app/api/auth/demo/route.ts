import { NextResponse, type NextRequest } from "next/server";

import { SEPARATE_DEMO, publicOrigin } from "@/lib/auth/session";
import { DEMO_COOKIE, demoCookieOptions, isDemoKey, newDemoKey } from "@/lib/demo/session";

/** "Try the demo" on a sign-in site: give this browser a private demo copy, then open it. */
export async function GET(request: NextRequest) {
  const origin = publicOrigin(request.nextUrl.origin);
  if (!SEPARATE_DEMO) return NextResponse.redirect(`${origin}/signin`);
  const current = request.cookies.get(DEMO_COOKIE)?.value;
  const response = NextResponse.redirect(`${origin}/dashboard`);
  response.cookies.set(DEMO_COOKIE, isDemoKey(current) ? current : newDemoKey(), demoCookieOptions(origin.startsWith("https://")));
  return response;
}
