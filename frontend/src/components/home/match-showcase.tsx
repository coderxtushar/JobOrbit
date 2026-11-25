"use client";

import { Check, CircleAlert, Minus } from "lucide-react";
import { animate, motion, useInView } from "motion/react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

import { Starfield } from "./effects";
import { Chapter, Eyebrow, useCalmMotion } from "./primitives";

const MATCHED = ["Python", "FastAPI", "PostgreSQL", "REST APIs", "Git"];
const MISSING = ["Docker", "Kubernetes"];

const FACTORS: [string, number, string][] = [
  ["Skills", 88, "5 of the 7 skills the listing asks for"],
  ["Experience", 92, "0–2 years asked · you have 1"],
  ["Title", 84, "Backend Developer · your level"],
  ["Location", 100, "Bengaluru, hybrid · on your list"],
];

/** The page's one dealt moment: the score ring fills and counts when the card comes into view. */
function ScoreDial({ score, run }: { score: number; run: boolean }) {
  const reduced = useCalmMotion();
  const [value, setValue] = useState(0);
  useEffect(() => {
    if (!run || reduced) return;
    const controls = animate(0, score, {
      duration: 1.6,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (latest) => setValue(Math.round(latest)),
    });
    return () => controls.stop();
  }, [run, reduced, score]);
  const shown = reduced ? score : value;
  const circumference = 2 * Math.PI * 52;
  return (
    <div className="relative grid size-40 shrink-0 place-items-center">
      <div
        aria-hidden
        className="absolute inset-0 hidden rounded-full bg-[radial-gradient(closest-side,transparent_62%,color-mix(in_oklch,var(--violet)_45%,transparent)_80%,transparent)] blur-md dark:block"
        style={{ opacity: shown / 100 }}
      />
      <svg viewBox="0 0 120 120" className="absolute inset-0 -rotate-90">
        <defs>
          <linearGradient id="dial" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0%" stopColor="var(--violet)" />
            <stop offset="100%" stopColor="var(--cyan)" />
          </linearGradient>
        </defs>
        <circle
          cx="60"
          cy="60"
          r="52"
          fill="none"
          stroke="var(--line-strong)"
          strokeWidth="8"
        />
        <circle
          cx="60"
          cy="60"
          r="52"
          fill="none"
          stroke="url(#dial)"
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - shown / 100)}
        />
      </svg>
      <div className="text-center">
        <p className="font-heading text-5xl font-semibold text-text-1 tabular">
          {shown}
        </p>
        <p className="text-[11px] uppercase tracking-[0.16em] text-text-3">
          match
        </p>
      </div>
    </div>
  );
}

function MatchCard() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.45 });
  const reduced = useCalmMotion();
  const show = (delay: number) =>
    reduced
      ? {}
      : {
          initial: { opacity: 0, y: 8 },
          animate: inView ? { opacity: 1, y: 0 } : undefined,
          transition: {
            duration: 0.45,
            delay,
            ease: [0.22, 1, 0.36, 1] as const,
          },
        };

  return (
    <div ref={ref} className="orbit-card relative overflow-hidden p-6 sm:p-8">
      <div className="pointer-events-none absolute -right-24 -top-24 size-72 rounded-full bg-[radial-gradient(closest-side,var(--violet-soft),transparent)]" />
      <div className="relative flex flex-col gap-6 sm:flex-row sm:items-center">
        <ScoreDial score={86} run={inView} />
        <div className="min-w-0">
          <p className="text-[12px] text-text-3">
            Northwind Systems · Greenhouse · posted 2 days ago
          </p>
          <h3 className="mt-1 font-heading text-2xl font-semibold text-text-1">
            Backend Developer (Python)
          </h3>
          <p className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-success-soft px-2.5 py-0.5 text-[12px] font-medium text-success">
            <Check className="size-3.5" /> Eligible for auto-apply
          </p>
        </div>
      </div>

      <div className="relative mt-8 space-y-3.5">
        {FACTORS.map(([name, width, detail], index) => (
          <div
            key={name}
            className="grid grid-cols-[5.5rem_1fr] items-center gap-4 sm:grid-cols-[6rem_1fr_15rem]"
          >
            <span className="text-[13px] font-medium text-text-1">{name}</span>
            <div className="h-1.5 overflow-hidden rounded-full bg-surface-2">
              <motion.div
                className="h-full rounded-full bg-gradient-to-r from-violet to-cyan"
                initial={reduced ? false : { width: 0 }}
                animate={inView || reduced ? { width: `${width}%` } : undefined}
                style={reduced ? { width: `${width}%` } : undefined}
                transition={{
                  duration: 0.9,
                  delay: 0.3 + index * 0.1,
                  ease: [0.22, 1, 0.36, 1],
                }}
              />
            </div>
            <span className="col-span-2 text-[12px] text-text-3 sm:col-span-1">
              {detail}
            </span>
          </div>
        ))}
      </div>

      <div className="relative mt-8 grid gap-5 border-t border-line pt-6 sm:grid-cols-2">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-text-3">
            You have
          </p>
          <ul className="mt-3 flex flex-wrap gap-1.5">
            {MATCHED.map((skill, index) => (
              <motion.li
                key={skill}
                {...show(0.6 + index * 0.05)}
                className="inline-flex items-center gap-1 rounded-md bg-success-soft px-2 py-1 text-[12px] font-medium text-success"
              >
                <Check className="size-3" /> {skill}
              </motion.li>
            ))}
          </ul>
        </div>
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-text-3">
            Worth learning
          </p>
          <ul className="mt-3 flex flex-wrap gap-1.5">
            {MISSING.map((skill, index) => (
              <motion.li
                key={skill}
                {...show(0.85 + index * 0.05)}
                className="inline-flex items-center gap-1 rounded-md bg-warning-soft px-2 py-1 text-[12px] font-medium text-warning"
              >
                <Minus className="size-3" /> {skill}
              </motion.li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

const HELD = [
  ["Senior Staff Software Engineer", "Title is three levels above yours"],
  ["Backend Engineer, 5+ years", "Asks for 5 years, you have 1"],
  ["Platform Engineer (on-site, Berlin)", "Outside the locations you chose"],
];

export function MatchShowcase() {
  return (
    <Chapter
      id="match"
      label="Explainable matching"
      backdrop={<Starfield count={24} />}
    >
      <div className="grid items-center gap-12 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
        <div>
          <Eyebrow>Matching</Eyebrow>
          <h2 className="mt-4 font-heading text-4xl font-semibold tracking-tight text-text-1 sm:text-5xl">
            A score you can read, not a black box.
          </h2>
          <p className="mt-5 text-[17px] leading-relaxed text-text-2">
            Each job is measured against your own résumé: skills, years, title
            level and location. You see what lifted the score, what is missing,
            and why a job will never be applied to automatically.
          </p>
          <ul className="mt-8 space-y-2.5">
            {HELD.map(([title, reason]) => (
              <li
                key={title}
                className="flex items-start gap-3 rounded-xl border border-line bg-surface-1/60 px-4 py-3 transition-[transform,border-color] duration-200 hover:-translate-y-0.5 hover:border-danger/30"
              >
                <CircleAlert className="mt-0.5 size-4 shrink-0 text-danger" />
                <span className="min-w-0">
                  <span className="block text-[14px] font-medium text-text-1">
                    {title}
                  </span>
                  <span className={cn("block text-[12.5px] text-text-3")}>
                    Held back · {reason}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <MatchCard />
      </div>
    </Chapter>
  );
}
