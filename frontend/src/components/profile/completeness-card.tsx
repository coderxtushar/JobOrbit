"use client";

import { Check, ShieldAlert } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";

import { cn } from "@/lib/utils";

import { COMPLETENESS, type ProfileFormValues, type SectionId } from "./profile-schema";

/**
 * A count of filled fields, from the form as it is now (saved or not). It says nothing about
 * whether the content is good, only whether something is there.
 */
export function CompletenessCard({
  values,
  onJump,
}: {
  values: ProfileFormValues;
  onJump: (section: SectionId) => void;
}) {
  const reduced = useReducedMotion();
  const filled = COMPLETENESS.filter((item) => item.filled(values));
  const missing = COMPLETENESS.filter((item) => !item.filled(values));
  const pct = Math.round((filled.length / COMPLETENESS.length) * 100);
  const size = 56;
  const stroke = 5;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;

  return (
    <div className="orbit-card relative overflow-hidden p-4">
      <div className="pointer-events-none absolute -top-10 -right-10 size-32 rounded-full bg-violet-soft blur-2xl" />
      <div className="relative flex items-center gap-3.5">
        <div
          className="relative grid shrink-0 place-items-center"
          style={{ width: size, height: size }}
          role="img"
          aria-label={`Profile ${pct}% complete: ${filled.length} of ${COMPLETENESS.length} fields filled`}
        >
          <svg width={size} height={size} className="-rotate-90">
            <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--line-strong)" strokeWidth={stroke} />
            <motion.circle
              cx={size / 2}
              cy={size / 2}
              r={radius}
              fill="none"
              stroke={pct === 100 ? "var(--success)" : "var(--violet)"}
              strokeWidth={stroke}
              strokeLinecap="round"
              strokeDasharray={circumference}
              initial={false}
              animate={{ strokeDashoffset: circumference * (1 - pct / 100) }}
              transition={reduced ? { duration: 0 } : { duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
            />
          </svg>
          <span className="absolute font-heading text-sm font-semibold text-text-1 tabular">{pct}%</span>
        </div>
        <div className="min-w-0">
          <p className="font-heading text-sm font-semibold text-text-1">Profile completeness</p>
          <p className="text-xs text-text-3 tabular">
            {filled.length} of {COMPLETENESS.length} fields filled
          </p>
        </div>
      </div>
      {missing.length ? (
        <div className="relative mt-3.5 space-y-1.5">
          <p className="text-[11px] font-semibold tracking-wider text-text-3 uppercase">Still empty</p>
          <div className="flex flex-wrap gap-1">
            {missing.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => onJump(item.section)}
                className={cn(
                  "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] ring-1 ring-inset transition-colors",
                  item.sensitive
                    ? "bg-warning-soft text-warning ring-warning/25 hover:bg-warning/20"
                    : "bg-surface-2 text-text-2 ring-line hover:bg-surface-3 hover:text-text-1",
                )}
              >
                {item.sensitive ? <ShieldAlert className="size-3" /> : null}
                {item.label}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <p className="relative mt-3 flex items-center gap-1.5 text-xs text-success">
          <Check className="size-3.5" /> Every tracked field has a value.
        </p>
      )}
    </div>
  );
}
