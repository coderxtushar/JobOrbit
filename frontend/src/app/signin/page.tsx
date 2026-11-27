import type { Metadata } from "next";
import Link from "next/link";

import { OrbitMark, Wordmark } from "@/components/brand/orbit-mark";
import { buttonVariants } from "@/components/ui/button";
import { AUTH_ENABLED, SEPARATE_DEMO, safeNext } from "@/lib/auth/session";
import { cn } from "@/lib/utils";

export const metadata: Metadata = {
  title: "Sign in",
  description: "Sign in to JobOrbit with your Google account.",
};

const ERRORS: Record<string, string> = {
  cancelled: "Sign-in was cancelled. Nothing was saved.",
  state_mismatch: "That sign-in link expired or was opened in another browser. Please try again.",
  not_configured: "Sign-in is not set up on this site yet.",
  google_error: "Google could not complete the sign-in. Please try again.",
  google_unreachable: "Google could not be reached. Check your connection and try again.",
  api_unreachable: "JobOrbit's server is waking up. Wait a few seconds and try again.",
  email_not_verified: "Google has not verified this account's email address.",
  sign_ups_closed: "JobOrbit has reached its account limit for now, so new sign-ups are paused.",
  account_disabled: "This account has been disabled.",
};

function GoogleG() {
  return (
    <svg viewBox="0 0 48 48" aria-hidden className="size-5">
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
      <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2c-2 1.5-4.5 2.4-7.2 2.4-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
    </svg>
  );
}

export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; error?: string }>;
}) {
  const { next, error } = await searchParams;
  const target = safeNext(next);
  const message = error ? (ERRORS[error] ?? "Sign-in did not complete. Please try again.") : null;

  return (
    <main className="flex min-h-dvh items-center justify-center bg-surface-0 px-4 py-16">
      <div className="w-full max-w-sm">
        <Link href="/" className="mb-8 flex items-center justify-center gap-2" aria-label="JobOrbit home">
          <OrbitMark className="size-8" />
          <Wordmark className="text-lg" />
        </Link>
        <div className="rounded-xl border border-border bg-surface-1 p-6 shadow-sm">
          <h1 className="font-heading text-xl font-semibold text-text-1">Sign in to JobOrbit</h1>
          <p className="mt-2 text-sm text-text-2">
            Your profile, answers and applications stay private to your account.
          </p>

          {message ? (
            <p role="alert" className="mt-4 rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-sm text-text-1">
              {message}
            </p>
          ) : null}

          {AUTH_ENABLED ? (
            <a
              href={`/api/auth/google/start?next=${encodeURIComponent(target)}`}
              className={cn(buttonVariants({ variant: "outline", size: "lg" }), "mt-6 w-full gap-3")}
            >
              <GoogleG />
              Continue with Google
            </a>
          ) : (
            <p className="mt-6 text-sm text-text-2">
              This JobOrbit runs on one computer for one person, so there is nothing to sign in to.{" "}
              <Link href="/dashboard" className="font-medium text-violet underline-offset-4 hover:underline">
                Open the dashboard
              </Link>
            </p>
          )}

          {SEPARATE_DEMO ? (
            <p className="mt-4 text-center text-sm text-text-2">
              Just looking?{" "}
              <a href="/api/auth/demo" className="font-medium text-violet underline-offset-4 hover:underline">
                Try the demo
              </a>{" "}
              with sample data, no account needed.
            </p>
          ) : null}
        </div>
        <p className="mt-6 text-center text-xs text-text-3">
          JobOrbit asks Google only for your name, email and picture.{" "}
          <Link href="/privacy" className="underline underline-offset-4">
            How your data is handled
          </Link>
        </p>
      </div>
    </main>
  );
}
