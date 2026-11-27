import type { Metadata } from "next";
import Link from "next/link";

import { ProfileView } from "@/components/profile/profile-view";

export const metadata: Metadata = {
  title: "Resume and profile",
  description: "Your resumes, their extracted fields and variants, and the profile every application is built from.",
};

/** Shown once, right after a first sign-in (the callback sends new accounts here). */
function Welcome() {
  return (
    <section
      aria-label="Getting started"
      className="mb-6 rounded-xl border border-violet/25 bg-violet-soft px-5 py-4 text-sm text-text-1"
    >
      <h2 className="font-heading text-base font-semibold">Welcome to JobOrbit</h2>
      <ol className="mt-2 list-decimal space-y-1 pl-5 text-text-2">
        <li>Upload your resume below. JobOrbit reads it and shows what it found.</li>
        <li>Check the details, add your target roles and locations, and save your profile.</li>
        <li>
          Open{" "}
          <Link href="/jobs" className="font-medium text-violet underline-offset-4 hover:underline">
            Job discovery
          </Link>{" "}
          and press <span className="font-medium text-text-1">Score jobs</span> to rank every listing against you.
        </li>
      </ol>
    </section>
  );
}

export default async function Page({ searchParams }: { searchParams: Promise<{ welcome?: string }> }) {
  const { welcome } = await searchParams;
  return (
    <>
      {welcome === "1" ? <Welcome /> : null}
      <ProfileView />
    </>
  );
}
