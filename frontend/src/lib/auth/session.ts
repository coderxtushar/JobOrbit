/**
 * Google sign-in for the hosted site. Server-only: nothing here reaches the browser.
 *
 * The browser never holds a Google token. The flow is:
 * 1. /api/auth/google/start sends the visitor to Google with PKCE and a random state,
 *    both kept in short-lived httpOnly cookies.
 * 2. Google returns to /api/auth/google/callback with a code. This server checks the
 *    state, swaps the code for an ID token (with the client secret, which only this server
 *    has), and hands the ID token to the API, which verifies Google's signature itself and
 *    issues a JobOrbit session.
 * 3. That session token lives in the httpOnly `joborbit_session` cookie, and the API proxy
 *    sends it as `X-JobOrbit-Session`. Page script can neither read nor forge it.
 */

/** "google" turns sign-in on; anything else is a local, single-person install. */
export const AUTH_MODE = (process.env.JOBORBIT_AUTH ?? "").toLowerCase() === "google" ? "google" : "local";
export const AUTH_ENABLED = AUTH_MODE === "google";

export const SESSION_COOKIE = "joborbit_session";
export const STATE_COOKIE = "joborbit_oauth_state";
export const VERIFIER_COOKIE = "joborbit_oauth_verifier";
export const NEXT_COOKIE = "joborbit_oauth_next";

/** Matches the API's default JA_SESSION_DAYS. */
const SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60;
/** Long enough to pick an account and consent; short enough to be useless if copied. */
const FLOW_MAX_AGE_SECONDS = 10 * 60;

export const GOOGLE_CLIENT_ID = process.env.GOOGLE_CLIENT_ID ?? "";
export const GOOGLE_CLIENT_SECRET = process.env.GOOGLE_CLIENT_SECRET ?? "";

export const BACKEND_URL = (process.env.JOBORBIT_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
export const BACKEND_TOKEN = process.env.JOBORBIT_API_TOKEN ?? process.env.JA_API_TOKEN ?? "";

/** A separate demo API for signed-out visitors who choose "Try the demo" (optional). */
export const DEMO_API_URL = (process.env.JOBORBIT_DEMO_API_URL ?? "").replace(/\/$/, "");
export const DEMO_API_TOKEN = process.env.JOBORBIT_DEMO_API_TOKEN ?? "";
export const SEPARATE_DEMO = AUTH_ENABLED && Boolean(DEMO_API_URL);

const TOKEN_SHAPE = /^[A-Za-z0-9_-]{20,200}$/;

export function isSessionToken(value: string | undefined): value is string {
  return typeof value === "string" && TOKEN_SHAPE.test(value);
}

export function sessionCookieOptions(secure: boolean, maxAge = SESSION_MAX_AGE_SECONDS) {
  return { httpOnly: true, sameSite: "lax" as const, secure, path: "/", maxAge };
}

export function flowCookieOptions(secure: boolean) {
  // Scoped to the auth routes: no other request carries them.
  return { httpOnly: true, sameSite: "lax" as const, secure, path: "/api/auth", maxAge: FLOW_MAX_AGE_SECONDS };
}

function base64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function randomToken(byteCount = 32): string {
  return base64Url(crypto.getRandomValues(new Uint8Array(byteCount)));
}

export async function pkceChallenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64Url(new Uint8Array(digest));
}

/** Only same-site paths, so the post-sign-in redirect cannot be pointed at another site. */
export function safeNext(value: string | null | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) return "/dashboard";
  return value.slice(0, 500);
}

/** The public origin Google redirects back to; set JOBORBIT_PUBLIC_URL behind a proxy. */
export function publicOrigin(requestOrigin: string): string {
  return (process.env.JOBORBIT_PUBLIC_URL ?? requestOrigin).replace(/\/$/, "");
}

/** A server-to-server call to the API, with the service token and the visitor's session. */
export async function callBackend(path: string, init: RequestInit & { session?: string } = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (BACKEND_TOKEN) headers.set("authorization", `Bearer ${BACKEND_TOKEN}`);
  if (init.session) headers.set("x-joborbit-session", init.session);
  return fetch(`${BACKEND_URL}${path}`, { ...init, headers, cache: "no-store" });
}
