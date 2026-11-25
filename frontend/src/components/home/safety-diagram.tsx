"use client";

import {
  Check,
  CircleAlert,
  Gauge,
  Inbox,
  KeyRound,
  OctagonX,
  RefreshCcw,
  ScanSearch,
  TestTubeDiagonal,
  type LucideIcon,
} from "lucide-react";
import { motion } from "motion/react";

import { cn } from "@/lib/utils";

import { Starfield } from "./effects";
import { Chapter, Eyebrow, useCalmMotion } from "./primitives";

const LANES: {
  name: string;
  detail: string;
  icon: LucideIcon;
  tone: string;
  stroke: string;
}[] = [
  {
    name: "Ready",
    detail: "Form filled and checked. It waits for your tick.",
    icon: Check,
    tone: "text-success bg-success-soft border-success/25",
    stroke: "var(--success)",
  },
  {
    name: "Needs your answer",
    detail:
      "One question goes to your Action inbox. Answer once, reused after.",
    icon: Inbox,
    tone: "text-warning bg-warning-soft border-warning/25",
    stroke: "var(--warning)",
  },
  {
    name: "Held back",
    detail:
      "Shown with its reason: a login wall, a level too senior, a broken form.",
    icon: CircleAlert,
    tone: "text-danger bg-danger-soft border-danger/25",
    stroke: "var(--danger)",
  },
];

const CHECKS = [
  "Is it still open?",
  "Is it the right level?",
  "Is every answer known?",
  "Is the platform healthy?",
];

const GUARANTEES: { title: string; body: string; icon: LucideIcon }[] = [
  {
    title: "Dry run first",
    body: "Fill every form without pressing Submit, then read the screenshots.",
    icon: TestTubeDiagonal,
  },
  {
    title: "CAPTCHA is yours",
    body: "A CAPTCHA or a one-time code pauses the run and is handed to you.",
    icon: KeyRound,
  },
  {
    title: "No blind retries",
    body: "When an outcome is unclear, JobOrbit asks you instead of applying twice.",
    icon: RefreshCcw,
  },
  {
    title: "Emergency stop",
    body: "One switch stops every run and every queued application.",
    icon: OctagonX,
  },
  {
    title: "Daily cap",
    body: "25 applications a day by default, and a pause after repeated failures.",
    icon: Gauge,
  },
];

/** A path with a short bright dash that keeps running along it. */
function Pulse({
  d,
  stroke,
  delay,
}: {
  d: string;
  stroke: string;
  delay: number;
}) {
  const reduced = useCalmMotion();
  return (
    <>
      <path
        d={d}
        fill="none"
        stroke="var(--line-strong)"
        strokeWidth="1.5"
        vectorEffect="non-scaling-stroke"
      />
      {reduced ? null : (
        <motion.path
          d={d}
          fill="none"
          className="fx-glow-current"
          style={{ color: stroke }}
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
          pathLength={100}
          strokeDasharray="10 90"
          initial={{ strokeDashoffset: 100 }}
          animate={{ strokeDashoffset: 0 }}
          transition={{
            duration: 2.6,
            delay,
            repeat: Infinity,
            ease: "linear",
          }}
        />
      )}
    </>
  );
}

function Diagram() {
  return (
    <div className="orbit-card relative overflow-hidden p-5 sm:p-8">
      <div className="pointer-events-none absolute inset-0 opacity-50 [background-image:radial-gradient(var(--line-strong)_1px,transparent_1px)] [background-size:22px_22px] [mask-image:radial-gradient(70%_70%_at_50%_50%,black,transparent)]" />
      <div className="relative grid items-stretch gap-4 md:grid-cols-[9rem_3rem_minmax(0,14rem)_4.5rem_minmax(0,1fr)] md:gap-0">
        {/* input */}
        <div className="flex items-center">
          <div className="w-full rounded-xl border border-line-strong bg-surface-1 p-3.5 shadow-card">
            <p className="text-[11px] uppercase tracking-[0.14em] text-text-3">
              Input
            </p>
            <p className="mt-1 text-[14px] font-medium text-text-1">
              A job you ticked
            </p>
          </div>
        </div>
        <svg
          aria-hidden
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          className="hidden h-full w-full md:block"
        >
          <Pulse d="M0 50 L100 50" stroke="var(--violet)" delay={0} />
        </svg>
        {/* the hub */}
        <div className="flex items-center">
          <div className="w-full rounded-2xl border border-violet/40 bg-surface-1 p-4 shadow-glow">
            <div className="flex items-center gap-2">
              <span className="grid size-8 place-items-center rounded-lg bg-violet text-primary-foreground">
                <ScanSearch className="size-4" />
              </span>
              <p className="font-heading text-[16px] font-semibold text-text-1">
                Preflight
              </p>
            </div>
            <ul className="mt-3 space-y-1.5">
              {CHECKS.map((check) => (
                <li
                  key={check}
                  className="flex items-center gap-2 text-[12.5px] text-text-2"
                >
                  <span className="size-1 rounded-full bg-violet" /> {check}
                </li>
              ))}
            </ul>
          </div>
        </div>
        <svg
          aria-hidden
          viewBox="0 0 100 300"
          preserveAspectRatio="none"
          className="hidden h-full w-full md:block"
        >
          <Pulse
            d="M0 150 C 55 150, 45 50, 100 50"
            stroke={LANES[0].stroke}
            delay={0.9}
          />
          <Pulse d="M0 150 L100 150" stroke={LANES[1].stroke} delay={1.3} />
          <Pulse
            d="M0 150 C 55 150, 45 250, 100 250"
            stroke={LANES[2].stroke}
            delay={1.7}
          />
        </svg>
        {/* three lanes */}
        <ul className="grid gap-3 md:grid-rows-3">
          {LANES.map((lane) => (
            <li key={lane.name} className="flex items-center">
              <div className="flex w-full items-start gap-3 rounded-xl border border-line bg-surface-1 p-3.5 transition-transform duration-200 hover:-translate-y-0.5">
                <span
                  className={cn(
                    "grid size-8 shrink-0 place-items-center rounded-lg border",
                    lane.tone,
                  )}
                >
                  <lane.icon className="size-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-[14px] font-medium text-text-1">
                    {lane.name}
                  </span>
                  <span className="block text-[12.5px] leading-snug text-text-3">
                    {lane.detail}
                  </span>
                </span>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export function SafetyDiagram() {
  return (
    <Chapter
      id="safety"
      label="Safety and control"
      className="lg:py-20"
      backdrop={<Starfield count={30} />}
    >
      <div className="max-w-2xl">
        <Eyebrow>Safety</Eyebrow>
        <h2 className="mt-4 font-heading text-4xl font-semibold tracking-tight text-text-1 sm:text-5xl">
          Every application is checked before a single field is filled.
        </h2>
        <p className="mt-5 text-[17px] leading-relaxed text-text-2">
          Preflight sorts the jobs you ticked into three lanes. Only the first
          one is ever sent, and only when you say so.
        </p>
      </div>
      <div className="mt-10">
        <Diagram />
      </div>
      <ul className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {GUARANTEES.map((item) => (
          <li
            key={item.title}
            className="group rounded-xl border border-line bg-surface-1/60 p-4 transition-[transform,border-color] duration-200 hover:-translate-y-0.5 hover:border-violet/35"
          >
            <item.icon className="size-5 text-violet transition-transform duration-300 group-hover:scale-110" />
            <p className="mt-3 text-[14px] font-medium text-text-1">
              {item.title}
            </p>
            <p className="mt-1 text-[12.5px] leading-snug text-text-3">
              {item.body}
            </p>
          </li>
        ))}
      </ul>
    </Chapter>
  );
}
