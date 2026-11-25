"use client";

import { ArrowRight, ArrowUpRight, Terminal } from "lucide-react";
import {
  motion,
  useScroll,
  useTransform,
  type MotionValue,
} from "motion/react";
import Link from "next/link";
import { useRef } from "react";

import { OrbitMark, Wordmark } from "@/components/brand/orbit-mark";

import { Starfield } from "./effects";
import { AUTHOR, GithubMark, REPO_URL } from "./github-mark";
import { Container, CtaLink, useCalmMotion } from "./primitives";

const STATEMENT =
  "You choose the jobs. JobOrbit does the searching, the scoring and the typing, and stops at every step that should be yours.";

function Word({
  word,
  progress,
  range,
}: {
  word: string;
  progress: MotionValue<number>;
  range: [number, number];
}) {
  const opacity = useTransform(progress, range, [0.18, 1]);
  return (
    <motion.span style={{ opacity }} className="inline-block whitespace-pre">
      {word}{" "}
    </motion.span>
  );
}

/** The second moment: the statement lights up word by word as it scrolls through the screen. */
function Statement() {
  const ref = useRef<HTMLParagraphElement>(null);
  const reduced = useCalmMotion();
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start 0.85", "end 0.45"],
  });
  const words = STATEMENT.split(" ");
  const className =
    "font-heading text-[2.1rem] font-semibold leading-[1.12] tracking-tight text-text-1 sm:text-5xl lg:text-[3.6rem]";
  if (reduced)
    return (
      <p ref={ref} className={className}>
        {STATEMENT}
      </p>
    );
  return (
    <p ref={ref} className={className}>
      {words.map((word, index) => (
        <Word
          key={`${word}-${index}`}
          word={word}
          progress={scrollYProgress}
          range={[index / words.length, (index + 1) / words.length]}
        />
      ))}
    </p>
  );
}

export function Closing() {
  return (
    <section
      aria-label="Start with JobOrbit"
      className="relative isolate flex min-h-svh items-center overflow-hidden py-24"
    >
      <div
        aria-hidden
        className="absolute inset-0 -z-10 bg-[radial-gradient(50rem_30rem_at_50%_110%,var(--violet-soft),transparent_70%)] dark:bg-[radial-gradient(56rem_34rem_at_50%_115%,color-mix(in_oklch,var(--violet)_34%,transparent),transparent_70%)]"
      />
      <div aria-hidden className="absolute inset-0 -z-10">
        <Starfield />
      </div>
      <svg
        aria-hidden
        viewBox="0 0 1000 1000"
        className="absolute left-1/2 top-[62%] -z-10 size-[70rem] -translate-x-1/2 animate-orbit-spin"
      >
        <circle
          cx="500"
          cy="500"
          r="420"
          fill="none"
          stroke="var(--violet)"
          strokeWidth="1.4"
          style={{ strokeOpacity: "var(--fx-ring)" }}
        />
        <circle
          cx="500"
          cy="500"
          r="300"
          fill="none"
          stroke="var(--cyan)"
          strokeWidth="1.4"
          strokeDasharray="3 9"
          strokeLinecap="round"
          style={{ strokeOpacity: "var(--fx-ring)" }}
        />
        <circle
          className="fx-glow"
          cx="920"
          cy="500"
          r="7"
          fill="var(--violet)"
        />
        <circle
          className="fx-glow-cyan"
          cx="500"
          cy="200"
          r="5"
          fill="var(--cyan)"
        />
      </svg>
      <Container>
        <div className="max-w-4xl">
          <Statement />
          <div className="mt-12 flex flex-col gap-3 sm:flex-row sm:items-center">
            <CtaLink href="/dashboard">
              Open the dashboard{" "}
              <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
            </CtaLink>
            <CtaLink href="/auto-apply" variant="ghost">
              Start a dry run
            </CtaLink>
          </div>
          <p className="mt-8 inline-flex items-center gap-2 rounded-lg border border-line bg-surface-1/60 px-3 py-2 font-mono text-[12.5px] text-text-2 backdrop-blur">
            <Terminal className="size-4 text-violet" /> runs locally on
            127.0.0.1 · your data stays in one SQLite file
          </p>
        </div>
      </Container>
    </section>
  );
}

const FOOTER_LINKS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/jobs", label: "Jobs" },
  { href: "/auto-apply", label: "Auto-apply" },
  { href: "/action-inbox", label: "Action inbox" },
  { href: "/settings", label: "Settings" },
];

export function HomeFooter() {
  return (
    <footer className="relative border-t border-line py-12">
      <div
        aria-hidden
        className="absolute inset-x-0 -top-px mx-auto h-px max-w-3xl bg-gradient-to-r from-transparent via-violet to-transparent opacity-60"
      />
      <Container className="flex flex-col gap-8 md:flex-row md:items-start md:justify-between">
        <div className="space-y-3">
          <Link href="/" className="flex items-center gap-2.5">
            <OrbitMark />
            <Wordmark />
          </Link>
          <p className="text-[13px] text-text-2">
            Designed and built by{" "}
            <a
              href={AUTHOR.profile}
              target="_blank"
              rel="noreferrer"
              className="font-semibold text-text-1 underline decoration-violet/50 underline-offset-4 transition-colors hover:decoration-violet"
            >
              {AUTHOR.name}
            </a>
          </p>
        </div>
        <div className="flex flex-col gap-5 md:items-end">
          <nav
            aria-label="Workspace"
            className="flex flex-wrap gap-x-6 gap-y-2"
          >
            {FOOTER_LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="relative text-[13px] text-text-2 transition-colors after:absolute after:-bottom-0.5 after:left-0 after:h-px after:w-full after:origin-left after:scale-x-0 after:bg-violet after:transition-transform hover:text-text-1 hover:after:scale-x-100"
              >
                {link.label}
              </Link>
            ))}
          </nav>
          <a
            href={REPO_URL}
            target="_blank"
            rel="noreferrer"
            className="group inline-flex h-10 items-center gap-2.5 rounded-xl border border-line-strong bg-surface-1/60 px-4 text-[13px] font-medium text-text-1 transition-[transform,border-color,box-shadow] duration-200 hover:-translate-y-0.5 hover:border-violet/50 hover:shadow-glow active:translate-y-0 active:scale-[0.98]"
          >
            <GithubMark className="size-[18px] transition-transform duration-300 group-hover:rotate-[8deg]" />
            Star JobOrbit on GitHub
            <ArrowUpRight className="size-3.5 text-text-3 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
          </a>
        </div>
      </Container>
      <Container className="mt-10">
        <div className="flex flex-col gap-2 border-t border-line pt-6 text-[12px] text-text-3 sm:flex-row sm:justify-between">
          <p>© {AUTHOR.name} · JobOrbit</p>
          <p>
            Fictional companies in the examples. Gmail, Chrome and GitHub icons
            from SVG Logos, CC0.
          </p>
        </div>
      </Container>
    </footer>
  );
}
