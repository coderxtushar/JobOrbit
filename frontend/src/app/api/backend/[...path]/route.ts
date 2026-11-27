/**
 * Same-origin proxy to the JobOrbit FastAPI backend.
 *
 * The browser only ever calls /api/backend/..., and this handler forwards the request to
 * JOBORBIT_API_URL. Two reasons:
 *
 * - The backend's bearer token (JA_API_TOKEN) is added here, on the server. It is never
 *   shipped to the browser, so a token-protected API stays protected.
 * - The backend needs no CORS configuration: it is reached server-to-server.
 *
 * Only the backend's own /api/* and /health paths are forwarded, to the one configured
 * origin, so this cannot be used to make requests anywhere else. Cookies are not forwarded:
 * a signed-in visitor's session and a demo visitor's key are read from this site's httpOnly
 * cookies and sent as headers (see src/lib/auth/session.ts).
 */
import type { NextRequest } from "next/server";

import {
  BACKEND_TOKEN,
  BACKEND_URL,
  DEMO_API_TOKEN,
  DEMO_API_URL,
  SEPARATE_DEMO,
  SESSION_COOKIE,
  isSessionToken,
} from "@/lib/auth/session";
import { DEMO_COOKIE, DEMO_ENABLED, isDemoKey } from "@/lib/demo/session";

// The demo key comes from this site's own httpOnly cookie, never from a header the browser
// could set, so a page script cannot point a request at another visitor's copy.
const FORWARDED_REQUEST_HEADERS = ["content-type", "accept"];
const FORWARDED_RESPONSE_HEADERS = [
  "content-type",
  "content-disposition",
  "cache-control",
  "x-content-type-options",
];

async function forward(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await params;
  const joined = path.map(encodeURIComponent).join("/");
  if (!(joined === "health" || joined.startsWith("api/")) || path.includes("..")) {
    return Response.json(
      { error: { code: "not_proxied", message: "Only backend API paths are proxied." } },
      { status: 404 },
    );
  }

  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  // Which API, and as whom. Both come from this site's own httpOnly cookies, never from a
  // header the browser could set, so page script cannot act as another visitor.
  const session = request.cookies.get(SESSION_COOKIE)?.value;
  const demoKey = request.cookies.get(DEMO_COOKIE)?.value;
  let BACKEND = BACKEND_URL;
  let token = BACKEND_TOKEN;
  if (isSessionToken(session)) {
    headers.set("x-joborbit-session", session);
  } else if (SEPARATE_DEMO && isDemoKey(demoKey)) {
    // A signed-out visitor who chose "Try the demo" talks to the demo API instead.
    BACKEND = DEMO_API_URL;
    token = DEMO_API_TOKEN;
    headers.set("x-demo-session", demoKey);
  } else if (DEMO_ENABLED && isDemoKey(demoKey)) {
    headers.set("x-demo-session", demoKey);
  }
  if (token) headers.set("authorization", `Bearer ${token}`);

  const hasBody = !["GET", "HEAD"].includes(request.method);
  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND}/${joined}${request.nextUrl.search}`, {
      method: request.method,
      headers,
      body: hasBody ? request.body : undefined,
      // Required by undici when streaming a request body.
      ...(hasBody ? { duplex: "half" } : {}),
      cache: "no-store",
      redirect: "manual",
    } as RequestInit);
  } catch {
    return Response.json(
      {
        error: {
          code: "backend_unreachable",
          message: `The JobOrbit API is not reachable at ${BACKEND}. Start it with: .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`,
        },
      },
      { status: 502 },
    );
  }

  const responseHeaders = new Headers();
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
