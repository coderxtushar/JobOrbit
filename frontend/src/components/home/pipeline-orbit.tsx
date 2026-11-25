"use client";

import {
  BarChart3,
  Bot,
  Check,
  FilePen,
  Mail,
  Radar,
  Sparkles,
  Send,
  type LucideIcon,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";

import { cn } from "@/lib/utils";

import { Starfield } from "./effects";
import { Chapter, Eyebrow, useCalmMotion } from "./primitives";

interface Stage {
  key: string;
  name: string;
  icon: LucideIcon;
  line: string;
  body: string;
  Panel: () => React.ReactNode;
}

function PanelRow({
  children,
  delay,
}: {
  children: React.ReactNode;
  delay: number;
}) {
  const reduced = useCalmMotion();
  return (
    <motion.li
      initial={reduced ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay, ease: [0.22, 1, 0.36, 1] }}
      className="flex items-center gap-3 rounded-lg border border-line bg-surface-2/50 px-3 py-2.5 text-[13px] text-text-1"
    >
      {children}
    </motion.li>
  );
}

const STAGES: Stage[] = [
  {
    key: "discover",
    name: "Discover",
    icon: Radar,
    line: "Openings from the boards you follow",
    body: "JobOrbit reads the public job boards of the companies you list and keeps one copy of each opening, however many places it appears. Jobs you find elsewhere come in with the browser extension.",
    Panel: () => (
      <ul className="space-y-2">
        {[
          ["Greenhouse boards", "public job-board API"],
          ["Lever boards", "public postings API"],
          ["Ashby boards", "public job-board API"],
          ["Browser capture", "the page you are on, one click"],
        ].map(([name, how], index) => (
          <PanelRow key={name} delay={index * 0.07}>
            <Check className="size-4 text-success" />
            <span className="font-medium">{name}</span>
            <span className="ml-auto text-[12px] text-text-3">{how}</span>
          </PanelRow>
        ))}
      </ul>
    ),
  },
  {
    key: "match",
    name: "Match",
    icon: Sparkles,
    line: "A score with its reasons",
    body: "Every job is scored against your résumé and profile. The score comes with the skills you match, the ones you miss, and the exact reason a job is held back.",
    Panel: () => (
      <ul className="space-y-2">
        {[
          ["Python, FastAPI, PostgreSQL", "matched", "text-success"],
          ["Docker", "missing, worth learning", "text-warning"],
          ["0–2 years asked, you have 1", "experience fits", "text-success"],
          ["Bengaluru, hybrid", "inside your locations", "text-success"],
        ].map(([what, verdict, tone], index) => (
          <PanelRow key={what} delay={index * 0.07}>
            <span className={cn("size-1.5 rounded-full bg-current", tone)} />
            <span className="font-medium">{what}</span>
            <span className={cn("ml-auto text-[12px]", tone)}>{verdict}</span>
          </PanelRow>
        ))}
      </ul>
    ),
  },
  {
    key: "prepare",
    name: "Prepare",
    icon: FilePen,
    line: "Résumé, letter and every answer",
    body: "A résumé variant tuned to the role, a cover letter from your own facts, and an answer for every screening question. A question JobOrbit cannot answer goes to your inbox, never a guess.",
    Panel: () => (
      <ul className="space-y-2">
        {[
          ["Résumé variant", "backend · your projects first"],
          ["Cover letter", "drafted from your profile"],
          ["Screening answers", "9 filled from your answer bank"],
          ["Notice period?", "waiting in your Action inbox"],
        ].map(([what, detail], index) => (
          <PanelRow key={what} delay={index * 0.07}>
            {index === 3 ? (
              <Mail className="size-4 text-warning" />
            ) : (
              <Check className="size-4 text-success" />
            )}
            <span className="font-medium">{what}</span>
            <span className="ml-auto text-[12px] text-text-3">{detail}</span>
          </PanelRow>
        ))}
      </ul>
    ),
  },
  {
    key: "apply",
    name: "Apply",
    icon: Bot,
    line: "Forms filled in its own Chrome window",
    body: "For the jobs you tick, JobOrbit opens the employer's Greenhouse, Lever or Ashby form, checks it is the right job, fills every field and attaches your résumé. A CAPTCHA or a verification code is always handed to you.",
    Panel: () => <FillingForm />,
  },
  {
    key: "track",
    name: "Track",
    icon: Send,
    line: "Every attempt, every reply",
    body: "Each attempt keeps its answers, a screenshot and a timeline. With Gmail connected read-only, replies are matched to applications and suggest a status change you accept or dismiss.",
    Panel: () => (
      <ol className="relative space-y-3 border-l border-line pl-5">
        {[
          ["Prepared", "résumé variant and letter locked"],
          ["Submitted · confirmed", "the employer's thank-you page"],
          ["Interview invite", "from Gmail · you accepted the change"],
        ].map(([what, detail], index) => (
          <motion.li
            key={what}
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.4, delay: index * 0.1 }}
            className="relative"
          >
            <span className="absolute -left-[25px] top-1.5 size-2.5 rounded-full border-2 border-background bg-violet" />
            <p className="text-[13px] font-medium text-text-1">{what}</p>
            <p className="text-[12px] text-text-3">{detail}</p>
          </motion.li>
        ))}
      </ol>
    ),
  },
  {
    key: "optimize",
    name: "Optimize",
    icon: BarChart3,
    line: "Learn what actually works",
    body: "See which sources, roles and score bands lead to interviews, from what really happened. A rate appears only once enough applications stand behind it.",
    Panel: () => (
      <div className="space-y-3">
        {[
          ["Company boards", 78],
          ["Browser capture", 52],
          ["Bulk preparation", 34],
        ].map(([name, width], index) => (
          <div key={name as string} className="space-y-1">
            <p className="text-[12px] text-text-2">{name}</p>
            <div className="h-2 overflow-hidden rounded-full bg-surface-2">
              <motion.div
                className="h-full rounded-full bg-gradient-to-r from-violet to-cyan"
                initial={{ width: 0 }}
                animate={{ width: `${width}%` }}
                transition={{
                  duration: 0.8,
                  delay: index * 0.1,
                  ease: [0.22, 1, 0.36, 1],
                }}
              />
            </div>
          </div>
        ))}
        <p className="pt-1 text-[11.5px] text-text-3">
          Interviews by source, from your own recorded outcomes.
        </p>
      </div>
    ),
  },
];

/** The Apply panel: fields fill one after another, then Submit waits for the user's tick. */
function FillingForm() {
  const reduced = useCalmMotion();
  const fields = [
    ["First name", "Asha"],
    ["Email", "asha@example.com"],
    ["Country", "India +91"],
    ["Résumé", "asha_resume.pdf"],
  ];
  return (
    <div className="space-y-2">
      {fields.map(([label, value], index) => (
        <div
          key={label}
          className="grid grid-cols-[6rem_1fr] items-center gap-3 text-[13px]"
        >
          <span className="text-text-3">{label}</span>
          <span className="relative h-8 overflow-hidden rounded-md border border-line bg-surface-2/50 px-2.5 leading-8 text-text-1">
            <motion.span
              className="block truncate"
              initial={reduced ? false : { clipPath: "inset(0 100% 0 0)" }}
              animate={{ clipPath: "inset(0 0% 0 0)" }}
              transition={{
                duration: 0.55,
                delay: 0.15 + index * 0.35,
                ease: "linear",
              }}
            >
              {value}
            </motion.span>
          </span>
        </div>
      ))}
      <motion.div
        initial={reduced ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1.7 }}
        className="mt-3 flex items-center justify-between rounded-lg border border-violet/30 bg-violet-soft px-3 py-2 text-[12px] text-violet"
      >
        <span>Right job, right company · checked twice</span>
        <span className="font-semibold">Submit waits for your tick</span>
      </motion.div>
    </div>
  );
}

const RADIUS = 42; // percent of the orbit box

function nodePosition(index: number, total: number) {
  const angle = (index / total) * Math.PI * 2 - Math.PI / 2;
  return {
    left: `${50 + RADIUS * Math.cos(angle)}%`,
    top: `${50 + RADIUS * Math.sin(angle)}%`,
  };
}

export function PipelineOrbit() {
  const [active, setActive] = useState(0);
  const stage = STAGES[active];

  return (
    <Chapter
      id="pipeline"
      label="How JobOrbit works"
      backdrop={<Starfield count={36} />}
    >
      <div className="max-w-2xl">
        <Eyebrow>How it works</Eyebrow>
        <h2 className="mt-4 font-heading text-4xl font-semibold tracking-tight text-text-1 sm:text-5xl">
          Six stages from listing to offer, in one workspace.
        </h2>
      </div>

      <div className="mt-14 grid items-center gap-12 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <div className="relative mx-auto aspect-square w-full max-w-[30rem]">
          <svg
            viewBox="0 0 100 100"
            aria-hidden
            className="absolute inset-0 size-full"
          >
            <circle
              cx="50"
              cy="50"
              r={RADIUS}
              fill="none"
              stroke="var(--violet)"
              strokeWidth="0.35"
              strokeDasharray="0.8 1.6"
              style={{ strokeOpacity: "var(--fx-ring)" }}
            />
            <circle
              cx="50"
              cy="50"
              r="26"
              fill="none"
              stroke="var(--cyan)"
              strokeWidth="0.3"
              style={{ strokeOpacity: "var(--fx-ring-soft)" }}
            />
          </svg>
          {/* One satellite on a slow orbit with a fading tail, the brand's own motif. */}
          <div
            aria-hidden
            className="absolute inset-0 animate-[orbit-spin_22s_linear_infinite] motion-reduce:animate-none"
          >
            <div
              className="fx-glow-cyan absolute inset-0 rounded-full"
              style={{
                background:
                  "conic-gradient(from 0deg, transparent 0deg 290deg, color-mix(in oklch, var(--cyan) 70%, transparent) 360deg)",
                mask: "radial-gradient(circle closest-side, transparent 82.6%, #000 83.2% 84.8%, transparent 85.4%)",
                WebkitMask:
                  "radial-gradient(circle closest-side, transparent 82.6%, #000 83.2% 84.8%, transparent 85.4%)",
              }}
            />
            <span className="fx-glow-cyan absolute left-1/2 top-[8%] size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-cyan shadow-glow-cyan" />
          </div>
          <div className="absolute left-1/2 top-1/2 grid size-[38%] -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-line-strong bg-surface-1/80 text-center shadow-raised backdrop-blur">
            <div>
              <AnimatePresence mode="wait">
                <motion.p
                  key={stage.key}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -6 }}
                  transition={{ duration: 0.25 }}
                  className="font-heading text-2xl font-semibold text-text-1"
                >
                  {stage.name}
                </motion.p>
              </AnimatePresence>
              <p className="mt-1 text-[11px] uppercase tracking-[0.16em] text-text-3">
                Stage {active + 1} of {STAGES.length}
              </p>
            </div>
          </div>
          <div
            role="tablist"
            aria-label="Pipeline stages"
            className="absolute inset-0"
          >
            {STAGES.map((item, index) => {
              const selected = index === active;
              const Icon = item.icon;
              return (
                <button
                  key={item.key}
                  type="button"
                  role="tab"
                  id={`stage-${item.key}`}
                  aria-selected={selected}
                  aria-controls="stage-panel"
                  onClick={() => setActive(index)}
                  onMouseEnter={() => setActive(index)}
                  onKeyDown={(event) => {
                    if (event.key === "ArrowRight" || event.key === "ArrowDown")
                      setActive((active + 1) % STAGES.length);
                    if (event.key === "ArrowLeft" || event.key === "ArrowUp")
                      setActive((active - 1 + STAGES.length) % STAGES.length);
                  }}
                  style={nodePosition(index, STAGES.length)}
                  className={cn(
                    "group absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-2 rounded-2xl p-1 outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  )}
                >
                  <span
                    className={cn(
                      "grid size-14 place-items-center rounded-2xl border transition-[background-color,border-color,box-shadow,transform] duration-300 group-hover:-translate-y-0.5",
                      selected
                        ? "border-violet/60 bg-violet text-primary-foreground shadow-glow"
                        : "border-line-strong bg-surface-1 text-text-2 group-hover:border-violet/40 group-hover:text-text-1",
                    )}
                  >
                    <Icon className="size-6" />
                  </span>
                  <span
                    className={cn(
                      "text-[12px] font-medium",
                      selected ? "text-text-1" : "text-text-3",
                    )}
                  >
                    {item.name}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        <div
          id="stage-panel"
          role="tabpanel"
          aria-labelledby={`stage-${stage.key}`}
          className="orbit-card relative min-h-[26rem] overflow-hidden p-6 sm:p-8"
        >
          <AnimatePresence mode="wait">
            <motion.div
              key={stage.key}
              initial={{ opacity: 0, y: 12, filter: "blur(6px)" }}
              animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              exit={{ opacity: 0, y: -8, filter: "blur(4px)" }}
              transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
            >
              <p className="text-[12px] font-semibold uppercase tracking-[0.16em] text-violet">
                {stage.line}
              </p>
              <p className="mt-3 text-[16px] leading-relaxed text-text-2">
                {stage.body}
              </p>
              <div className="mt-6">
                <stage.Panel />
              </div>
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </Chapter>
  );
}
