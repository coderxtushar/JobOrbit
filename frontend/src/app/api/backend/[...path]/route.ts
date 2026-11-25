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
 * origin, so this cannot be used to make requests anywhere else. Cookies are not forwarded.
 */
import type { NextRequest } from "next/server";

const BACKEND = (process.env.JOBORBIT_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
const TOKEN = process.env.JOBORBIT_API_TOKEN ?? process.env.JA_API_TOKEN ?? "";

const FORWARDED_REQUEST_HEADERS = ["content-type", "accept", "x-demo-session"];
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
  if (TOKEN) headers.set("authorization", `Bearer ${TOKEN}`);

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
