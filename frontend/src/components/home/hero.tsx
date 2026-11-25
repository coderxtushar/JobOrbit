"use client";

import {
  ArrowDown,
  ArrowRight,
  Check,
  CircleAlert,
  MessageSquareText,
  ShieldCheck,
} from "lucide-react";
import { animate, motion } from "motion/react";
import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

import { Aurora, Starfield } from "./effects";
import { Container, CtaLink, useCalmMotion, useEnter } from "./primitives";

/**
 * The hero's sky: drifting colour, a masked grid, stars (dark only) and two slow orbits whose
 * satellites glow in the dark theme. CSS rotation only; still under reduced motion.
 */
function HeroOrbits() {
  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-0 -z-10 overflow-hidden"
    >
      <Aurora />
      <Starfield />
      <div
        className="absolute inset-0 opacity-[0.35] [mask-image:radial-gradient(70%_60%_at_50%_30%,black,transparent)] dark:opacity-60"
        style={{
          backgroundImage:
            "linear-gradient(var(--line) 1px, transparent 1px), linear-gradient(90deg, var(--line) 1px, transparent 1px)",
          backgroundSize: "56px 56px",
        }}
      />
      <svg
        viewBox="0 0 1200 1200"
        className="absolute -right-[22rem] -top-[20rem] size-[62rem] animate-orbit-spin"
      >
        <defs>
          <linearGradient id="hero-ring-a" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0%" stopColor="var(--violet)" stopOpacity="0" />
            <stop offset="55%" stopColor="var(--violet)" />
            <stop offset="100%" stopColor="var(--cyan)" />
          </linearGradient>
        </defs>
        <ellipse
          cx="600"
          cy="600"
          rx="560"
          ry="230"
          fill="none"
          stroke="url(#hero-ring-a)"
          strokeWidth="1.6"
          style={{ strokeOpacity: "var(--fx-ring)" }}
          transform="rotate(-22 600 600)"
        />
        <circle
          className="fx-glow"
          cx="1105"
          cy="390"
          r="7"
          fill="var(--violet)"
        />
      </svg>
      <svg
        viewBox="0 0 1200 1200"
        className="absolute -right-[12rem] -top-[10rem] size-[46rem] animate-orbit-spin-reverse"
      >
        <ellipse
          cx="600"
          cy="600"
          rx="540"
          ry="320"
          fill="none"
          stroke="var(--cyan)"
          strokeWidth="1.4"
          strokeDasharray="2 10"
          strokeLinecap="round"
          style={{ strokeOpacity: "var(--fx-ring)" }}
          transform="rotate(16 600 600)"
        />
        <circle
          className="fx-glow-cyan"
          cx="90"
          cy="760"
          r="6"
          fill="var(--cyan)"
        />
      </svg>
    </div>
  );
}

function Ring({
  score,
  tone,
  delay,
}: {
  score: number;
  tone: string;
  delay: number;
}) {
  const reduced = useCalmMotion();
  const [value, setValue] = useState(0);
  useEffect(() => {
    if (reduced) return;
    const controls = animate(0, score, {
      duration: 1.1,
      delay,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (latest) => setValue(Math.round(latest)),
    });
    return () => controls.stop();
  }, [delay, reduced, score]);
  const circumference = 2 * Math.PI * 15;
  return (
    <span className="relative grid size-10 shrink-0 place-items-center">
      <svg viewBox="0 0 36 36" className="absolute inset-0 -rotate-90">
        <circle
          cx="18"
          cy="18"
          r="15"
          fill="none"
          stroke="var(--line-strong)"
          strokeWidth="3"
        />
        <circle
          cx="18"
          cy="18"
          r="15"
          fill="none"
          stroke={tone}
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={
            circumference * (1 - (reduced ? score : value) / 100)
          }
        />
      </svg>
      <span className="font-heading text-[11px] font-semibold text-text-1 tabular">
        {reduced ? score : value}
      </span>
    </span>
  );
}

type Row = {
  title: string;
  company: string;
  platform: string;
  score: number;
  status: "ready" | "answer" | "blocked";
  note: string;
};

const ROWS: Row[] = [
  {
    title: "Backend Developer (Python)",
    company: "Northwind Systems",
    platform: "Greenhouse",
    score: 86,
    status: "ready",
    note: "Form filled · awaiting your tick",
  },
  {
    title: "Cloud Engineer - Associate",
    company: "Stratus Works",
    platform: "Lever",
    score: 78,
    status: "ready",
    note: "Form filled · awaiting your tick",
  },
  {
    title: "Frontend Developer - React",
    company: "Palewind Labs",
    platform: "Ashby",
    score: 72,
    status: "answer",
    note: "Asks your notice period",
  },
  {
    title: "Senior Staff Software Engineer",
    company: "Northwind Systems",
    platform: "Greenhouse",
    score: 69,
    status: "blocked",
    note: "Title is three levels above yours",
  },
];

const STATUS = {
  ready: {
    label: "Ready",
    className: "bg-success-soft text-success ring-success/25",
    icon: Check,
  },
  answer: {
    label: "Needs you",
    className: "bg-warning-soft text-warning ring-warning/25",
    icon: MessageSquareText,
  },
  blocked: {
    label: "Held back",
    className: "bg-danger-soft text-danger ring-danger/25",
    icon: CircleAlert,
  },
} as const;

/** The product itself: an auto-apply preflight, drawn as live HTML in an app frame. */
function PreflightFrame() {
  const reduced = useCalmMotion();
  return (
    <div className="fx-beam relative rounded-2xl">
      <div className="absolute -inset-6 -z-10 rounded-[2rem] bg-[radial-gradient(closest-side,var(--violet-soft),transparent)] blur-2xl dark:-inset-10 dark:bg-[radial-gradient(closest-side,color-mix(in_oklch,var(--violet)_38%,transparent),transparent)]" />
      <div className="overflow-hidden rounded-2xl border border-line-strong bg-surface-1/90 shadow-raised backdrop-blur dark:bg-surface-1/80">
        <div className="flex items-center gap-2 border-b border-line px-4 py-3">
          <span className="size-2.5 rounded-full bg-danger/70" />
          <span className="size-2.5 rounded-full bg-warning/70" />
          <span className="size-2.5 rounded-full bg-success/70" />
          <span className="ml-3 truncate text-[12px] text-text-3">
            JobOrbit · Auto-apply preflight
          </span>
          <span className="ml-auto rounded-md bg-cyan-soft px-2 py-0.5 text-[11px] font-medium text-cyan">
            Dry run
          </span>
        </div>
        <div className="grid grid-cols-3 gap-px border-b border-line bg-line">
          {[
            ["Ready", "2", "text-success"],
            ["Need your answer", "1", "text-warning"],
            ["Held back", "1", "text-danger"],
          ].map(([label, value, tone]) => (
            <div key={label} className="bg-surface-1 px-4 py-3">
              <p className="text-[11px] text-text-3">{label}</p>
              <p
                className={cn(
                  "font-heading text-lg font-semibold tabular",
                  tone,
                )}
              >
                {value}
              </p>
            </div>
          ))}
        </div>
        <ul className="divide-y divide-line">
          {ROWS.map((row, index) => {
            const status = STATUS[row.status];
            return (
              <motion.li
                key={row.title}
                initial={reduced ? false : { opacity: 0, x: 14 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{
                  duration: 0.5,
                  delay: 0.55 + index * 0.12,
                  ease: [0.22, 1, 0.36, 1],
                }}
                className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-surface-2/60"
              >
                <span
                  aria-hidden
                  className={cn(
                    "grid size-4 place-items-center rounded border",
                    row.status === "ready"
                      ? "border-violet bg-violet text-primary-foreground"
                      : "border-line-strong",
                  )}
                >
                  {row.status === "ready" ? <Check className="size-3" /> : null}
                </span>
                <Ring
                  score={row.score}
                  delay={0.7 + index * 0.12}
                  tone={
                    row.status === "blocked"
                      ? "var(--text-3)"
                      : row.status === "answer"
                        ? "var(--violet)"
                        : "var(--success)"
                  }
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-medium text-text-1">
                    {row.title}
                  </span>
                  <span className="block truncate text-[11.5px] text-text-3">
                    {row.company} · {row.platform} · {row.note}
                  </span>
                </span>
                <span
                  className={cn(
                    "hidden shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset sm:inline-flex",
                    status.className,
                  )}
                >
                  <status.icon className="size-3" />
                  {status.label}
                </span>
              </motion.li>
            );
          })}
        </ul>
        <div className="flex items-center justify-between gap-3 border-t border-line bg-surface-2/40 px-4 py-3">
          <span className="flex items-center gap-1.5 text-[11.5px] text-text-3">
            <ShieldCheck className="size-3.5 text-success" /> 2 ticked · nothing
            is sent in a dry run
          </span>
          <span className="rounded-lg bg-violet px-3 py-1.5 text-[12px] font-semibold text-primary-foreground">
            Start dry run
          </span>
        </div>
      </div>
    </div>
  );
}

export function Hero() {
  const { container, item } = useEnter();
  return (
    <section
      aria-label="JobOrbit"
      className="relative isolate flex min-h-svh items-center pb-16 pt-28"
      data-enter
    >
      <HeroOrbits />
      <Container className="grid items-center gap-14 lg:grid-cols-[minmax(0,1.02fr)_minmax(0,1fr)]">
        <motion.div
          variants={container}
          initial="hidden"
          animate="show"
          className="max-w-xl"
        >
          <motion.p
            variants={item}
            className="inline-flex items-center gap-2 rounded-full border border-line-strong bg-surface-1/60 px-3 py-1 text-[12px] text-text-2 backdrop-blur"
          >
            <span className="relative flex size-2">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-success/60 motion-reduce:hidden" />
              <span className="relative inline-flex size-2 rounded-full bg-success" />
            </span>
            A job-search workspace that runs on your own laptop
          </motion.p>
          <motion.h1
            variants={item}
            className="mt-6 font-heading text-[2.6rem] font-semibold leading-[1.04] tracking-tight text-text-1 sm:text-6xl"
          >
            Find the right jobs.{" "}
            <span className="orbit-gradient-text">
              Let JobOrbit fill the forms.
            </span>
          </motion.h1>
          <motion.p
            variants={item}
            className="mt-6 text-[17px] leading-relaxed text-text-2"
          >
            JobOrbit pulls openings from company job boards, scores each one
            against your résumé, prepares the application, and fills Greenhouse,
            Lever and Ashby forms in its own Chrome window, only for the jobs
            you approve.
          </motion.p>
          <motion.div
            variants={item}
            className="mt-8 flex flex-col gap-3 sm:flex-row"
          >
            <CtaLink href="/dashboard">
              Open the dashboard{" "}
              <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
            </CtaLink>
            <CtaLink href="#pipeline" variant="ghost">
              See how it works{" "}
              <ArrowDown className="size-4 transition-transform group-hover:translate-y-0.5" />
            </CtaLink>
          </motion.div>
          <motion.ul
            variants={item}
            className="mt-9 flex flex-wrap gap-x-5 gap-y-2 text-[13px] text-text-2"
          >
            {[
              "Nothing is sent without your tick",
              "Résumé stays on your machine",
              "Dry run before every live run",
            ].map((fact) => (
              <li key={fact} className="flex items-center gap-1.5">
                <Check className="size-3.5 text-success" /> {fact}
              </li>
            ))}
          </motion.ul>
        </motion.div>
        <motion.div
          initial={{ opacity: 0, y: 26, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.9, delay: 0.35, ease: [0.22, 1, 0.36, 1] }}
        >
          <PreflightFrame />
        </motion.div>
      </Container>
    </section>
  );
}
