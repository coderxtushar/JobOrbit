"use client";

import { Check, Plus, RotateCcw, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Image from "next/image";
import { useState } from "react";

import { cn } from "@/lib/utils";

import { Starfield } from "./effects";
import { Chapter, Eyebrow } from "./primitives";

const BASE_STEPS = [
  { name: "Saved", detail: "From the Stratus Works job board", when: "Mon" },
  {
    name: "Prepared",
    detail: "Cloud résumé variant · cover letter",
    when: "Mon",
  },
  {
    name: "Submitted",
    detail: "Confirmed by the employer's thank-you page",
    when: "Tue",
  },
];

function Timeline({ interview }: { interview: boolean }) {
  const steps = interview
    ? [
        ...BASE_STEPS,
        {
          name: "Interview",
          detail: "Moved from a Gmail reply you accepted",
          when: "Thu",
        },
      ]
    : BASE_STEPS;
  return (
    <div className="orbit-card p-6 lg:row-span-2">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[12px] text-text-3">Stratus Works · Lever</p>
          <h3 className="mt-0.5 font-heading text-xl font-semibold text-text-1">
            Cloud Engineer - Associate
          </h3>
        </div>
        <motion.span
          key={interview ? "interview" : "submitted"}
          initial={{ scale: 0.85, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: "spring", stiffness: 420, damping: 22 }}
          className={cn(
            "shrink-0 rounded-full px-2.5 py-0.5 text-[12px] font-medium",
            interview ? "bg-violet-soft text-violet" : "bg-cyan-soft text-cyan",
          )}
        >
          {interview ? "Interview" : "Submitted"}
        </motion.span>
      </div>
      <ol className="relative mt-6 space-y-5 border-l border-line pl-6">
        <AnimatePresence initial={false}>
          {steps.map((step, index) => (
            <motion.li
              key={step.name}
              layout
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
              className="relative"
            >
              <span
                className={cn(
                  "absolute -left-[31px] top-1 grid size-3.5 place-items-center rounded-full border-2 border-background",
                  index === steps.length - 1
                    ? "bg-violet ring-4 ring-violet/20"
                    : "bg-text-3",
                )}
              />
              <div className="flex items-baseline justify-between gap-3">
                <p className="text-[14px] font-medium text-text-1">
                  {step.name}
                </p>
                <p className="text-[12px] text-text-3">{step.when}</p>
              </div>
              <p className="text-[12.5px] text-text-3">{step.detail}</p>
            </motion.li>
          ))}
        </AnimatePresence>
      </ol>
      <div className="mt-6 grid grid-cols-3 gap-2 border-t border-line pt-5 text-[12px]">
        {[
          ["Answers kept", "14"],
          ["Screenshots", "3"],
          ["Résumé", "v4"],
        ].map(([label, value]) => (
          <div key={label}>
            <p className="text-text-3">{label}</p>
            <p className="font-heading text-[15px] font-semibold text-text-1 tabular">
              {value}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

type Decision = "accepted" | "dismissed" | null;

function GmailCard({
  decision,
  onDecide,
}: {
  decision: Decision;
  onDecide: (value: Decision) => void;
}) {
  return (
    <div className="orbit-card p-5">
      <div className="flex items-center gap-2.5">
        <Image
          src="/icons/gmail.svg"
          alt="Gmail"
          width={22}
          height={22}
          className="h-[18px] w-auto"
        />
        <p className="text-[13px] font-medium text-text-1">
          Reply matched to an application
        </p>
      </div>
      <div className="mt-4 rounded-lg border border-line bg-surface-2/50 p-3">
        <p className="text-[12px] text-text-3">
          recruiting@stratusworks.example
        </p>
        <p className="mt-0.5 text-[13px] font-medium text-text-1">
          Next steps: technical interview
        </p>
        <p className="mt-1 text-[12px] text-text-2">
          Suggested change: Submitted → Interview
        </p>
      </div>
      <div className="mt-4 h-9">
        <AnimatePresence mode="wait" initial={false}>
          {decision ? (
            <motion.div
              key={decision}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              className="flex h-9 items-center justify-between text-[13px]"
            >
              {decision === "accepted" ? (
                <span className="flex items-center gap-1.5 text-success">
                  <Check className="size-4" /> Moved to Interview
                </span>
              ) : (
                <span className="flex items-center gap-1.5 text-text-2">
                  <X className="size-4" /> Dismissed · status unchanged
                </span>
              )}
              <button
                type="button"
                onClick={() => onDecide(null)}
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[12px] text-text-3 transition-colors hover:text-text-1 active:scale-95"
              >
                <RotateCcw className="size-3.5" /> Undo
              </button>
            </motion.div>
          ) : (
            <motion.div
              key="ask"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              className="flex gap-2"
            >
              <button
                type="button"
                onClick={() => onDecide("accepted")}
                className="inline-flex h-9 flex-1 items-center justify-center gap-1.5 rounded-lg bg-violet text-[13px] font-semibold text-primary-foreground transition-transform hover:-translate-y-0.5 active:scale-[0.97]"
              >
                <Check className="size-4" /> Accept
              </button>
              <button
                type="button"
                onClick={() => onDecide("dismissed")}
                className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-line-strong px-3 text-[13px] text-text-2 transition-transform hover:-translate-y-0.5 active:scale-[0.97]"
              >
                <X className="size-4" /> Dismiss
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

function CaptureCard() {
  const [saved, setSaved] = useState(false);
  return (
    <div className="orbit-card p-5">
      <div className="flex items-center gap-2.5">
        <Image
          src="/icons/chrome.svg"
          alt="Chrome"
          width={20}
          height={20}
          className="size-[18px]"
        />
        <p className="text-[13px] font-medium text-text-1">
          Save a job from any page
        </p>
      </div>
      <div className="mt-4 overflow-hidden rounded-lg border border-line">
        <div className="flex items-center gap-2 border-b border-line bg-surface-2/60 px-3 py-2">
          <span className="truncate rounded bg-surface-1 px-2 py-0.5 text-[11px] text-text-3">
            careers.palewind.example/frontend-developer
          </span>
        </div>
        <div className="space-y-3 p-3">
          <div className="min-w-0">
            <p className="truncate text-[13px] font-medium text-text-1">
              Frontend Developer - React
            </p>
            <p className="text-[12px] text-text-3">Palewind Labs · Pune</p>
          </div>
          <button
            type="button"
            onClick={() => setSaved((value) => !value)}
            aria-pressed={saved}
            className={cn(
              "inline-flex h-9 w-full items-center justify-center gap-1.5 rounded-lg px-3 text-[12px] font-semibold transition-[transform,background-color] hover:-translate-y-0.5 active:scale-[0.96]",
              saved
                ? "bg-success-soft text-success"
                : "bg-violet text-primary-foreground",
            )}
          >
            <AnimatePresence mode="wait" initial={false}>
              <motion.span
                key={saved ? "saved" : "save"}
                initial={{ opacity: 0, scale: 0.6 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.6 }}
                transition={{ duration: 0.15 }}
              >
                {saved ? (
                  <Check className="size-3.5" />
                ) : (
                  <Plus className="size-3.5" />
                )}
              </motion.span>
            </AnimatePresence>
            {saved ? "Saved · 72" : "Save to JobOrbit"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function TrackingShowcase() {
  const [decision, setDecision] = useState<Decision>(null);
  return (
    <Chapter id="tracking" label="Tracking" backdrop={<Starfield count={24} />}>
      <div className="grid items-center gap-12 lg:grid-cols-[minmax(0,0.75fr)_minmax(0,1.25fr)]">
        <div>
          <Eyebrow>Tracking</Eyebrow>
          <h2 className="mt-4 font-heading text-4xl font-semibold tracking-tight text-text-1 sm:text-5xl">
            Every application remembers what it sent.
          </h2>
          <p className="mt-5 text-[17px] leading-relaxed text-text-2">
            The résumé version, each answer and a screenshot stay with the
            application. Connect Gmail read-only and replies arrive as
            suggestions you accept or dismiss. Nothing in your inbox is ever
            sent, moved or deleted.
          </p>
          <p className="mt-4 text-[14px] text-text-3">
            Try Accept on the Gmail card.
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <Timeline interview={decision === "accepted"} />
          <GmailCard decision={decision} onDecide={setDecision} />
          <CaptureCard />
        </div>
      </div>
    </Chapter>
  );
}
