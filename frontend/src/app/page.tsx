import type { Metadata } from "next";
import { cookies } from "next/headers";

import { HomePage } from "@/components/home/home-page";
import { AUTH_ENABLED, SESSION_COOKIE, isSessionToken } from "@/lib/auth/session";

export const metadata: Metadata = {
  title: { absolute: "JobOrbit · Find the right jobs, let it fill the forms" },
  description:
    "JobOrbit finds openings on company job boards, scores them against your résumé, and fills Greenhouse, Lever and Ashby forms only for the jobs you approve.",
};

export default async function Home() {
  const signedIn = isSessionToken((await cookies()).get(SESSION_COOKIE)?.value);
  return <HomePage signInFirst={AUTH_ENABLED && !signedIn} />;
}
