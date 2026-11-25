/**
 * The hosted demo's per-visitor key.
 *
 * In demo mode the API gives every key its own copy of a fictional database, so one
 * visitor's shortlist or prepared application never shows up for the next. The key lives in
 * an httpOnly cookie set by `src/proxy.ts` on the first page load (before any API call, so
 * the parallel requests a page makes all share it) and is forwarded by the API proxy as
 * the `X-Demo-Session` header. It isolates honest visitors; it authenticates nobody, which
 * is acceptable only because every row in a demo copy is fictional.
 */
export const DEMO_ENABLED = ["1", "true", "yes"].includes((process.env.JOBORBIT_DEMO ?? "").toLowerCase());
export const DEMO_COOKIE = "joborbit_demo";
/** Matches the API's two-hour session lifetime. */
export const DEMO_MAX_AGE_SECONDS = 2 * 60 * 60;

const KEY_SHAPE = /^[A-Za-z0-9_-]{43}$/;

export function isDemoKey(value: string | undefined): value is string {
  return typeof value === "string" && KEY_SHAPE.test(value);
}

/** 32 random bytes, base64url: the same entropy the API's own key generator uses. */
export function newDemoKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function demoCookieOptions(secure: boolean) {
  return { httpOnly: true, sameSite: "lax" as const, secure, path: "/", maxAge: DEMO_MAX_AGE_SECONDS };
}
