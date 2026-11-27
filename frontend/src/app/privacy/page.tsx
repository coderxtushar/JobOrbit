import type { Metadata } from "next";
import Link from "next/link";

import { OrbitMark, Wordmark } from "@/components/brand/orbit-mark";

export const metadata: Metadata = {
  title: "Privacy",
  description: "What JobOrbit stores for a signed-in account, and how to delete it.",
};

const STORED = [
  ["From Google", "Your name, email address and profile picture. Nothing else: JobOrbit never sees your password or your inbox."],
  ["Your profile", "What you type or confirm: skills, target roles, locations, education, projects and your answers to common application questions."],
  ["Your resume", "The text and fields read from the file you upload. The file itself is not kept on the hosted site."],
  ["Your applications", "The cover letters and answers JobOrbit prepares for you, and the status you record for each one."],
  ["Sign-in sessions", "A random token per signed-in browser. Only a one-way hash of it is stored."],
];

const NEVER = [
  "Sell or share your data, or show it to another account.",
  "Read your Gmail. Email tracking is only available when you run JobOrbit on your own computer.",
  "Submit an application. On the hosted site JobOrbit prepares; you review and submit.",
  "Send your data to an AI service. Hosted cover letters are written by fixed rules from your own facts.",
];

export default function PrivacyPage() {
  return (
    <main className="min-h-dvh bg-surface-0 px-4 py-16">
      <article className="mx-auto max-w-2xl">
        <Link href="/" className="mb-10 inline-flex items-center gap-2" aria-label="JobOrbit home">
          <OrbitMark className="size-7" />
          <Wordmark />
        </Link>
        <h1 className="font-heading text-3xl font-semibold text-text-1">Privacy</h1>
        <p className="mt-3 text-text-2">
          JobOrbit keeps the least it needs to prepare your applications, keeps it private to your account, and deletes
          all of it when you ask.
        </p>

        <h2 className="mt-10 font-heading text-lg font-semibold text-text-1">What is stored</h2>
        <dl className="mt-4 divide-y divide-border rounded-xl border border-border bg-surface-1">
          {STORED.map(([term, detail]) => (
            <div key={term} className="grid gap-1 px-4 py-3 sm:grid-cols-[10rem_1fr] sm:gap-4">
              <dt className="text-sm font-medium text-text-1">{term}</dt>
              <dd className="text-sm text-text-2">{detail}</dd>
            </div>
          ))}
        </dl>

        <h2 className="mt-10 font-heading text-lg font-semibold text-text-1">What JobOrbit never does</h2>
        <ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-text-2">
          {NEVER.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>

        <h2 className="mt-10 font-heading text-lg font-semibold text-text-1">Deleting your account</h2>
        <p className="mt-3 text-sm text-text-2">
          Open the menu under your picture in the top bar and choose <strong className="text-text-1">Delete account</strong>.
          Your profile, resume data, answers, applications and sessions are deleted at once. Job listings are shared
          between accounts and stay.
        </p>

        <h2 className="mt-10 font-heading text-lg font-semibold text-text-1">Where it runs</h2>
        <p className="mt-3 text-sm text-text-2">
          The website is served by Vercel, the API by Render and the database by a managed Postgres provider. JobOrbit is
          open source:{" "}
          <a href="https://github.com/coderxtushar/JobOrbit" className="text-violet underline underline-offset-4">
            read the code
          </a>{" "}
          or{" "}
          <a href="https://github.com/coderxtushar/JobOrbit/issues" className="text-violet underline underline-offset-4">
            ask a question
          </a>
          .
        </p>
      </article>
    </main>
  );
}
