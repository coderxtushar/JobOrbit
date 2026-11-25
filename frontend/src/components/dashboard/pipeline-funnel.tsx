"use client";

import { motion } from "motion/react";

import { Skeleton } from "@/components/ui/skeleton";
import type { OutcomeReport } from "@/lib/api/types";
import { formatNumber } from "@/lib/formatting";
import { cn } from "@/lib/utils";

interface Stage {
  key: string;
  label: string;
  value: number;
  hint: string;
  color: string;
}

/**
 * The search pipeline as one row of stages. Bar length uses a log scale, because the
 * stages span four orders of magnitude (thousands discovered, a handful of offers) and a
 * linear bar would make every later stage invisible. Attempts and confirmations are
 * separate stages: an attempt is not a submission.
 */
export function PipelineFunnel({ outcomes, loading }: { outcomes?: OutcomeReport; loading: boolean }) {
  const f = outcomes?.funnel;
  const stages: Stage[] = f
    ? [
        { key: "discovered", label: "Discovered", value: f.jobs_discovered, hint: "all listings", color: "var(--text-3)" },
        { key: "eligible", label: "Eligible", value: f.eligible_jobs, hint: "pass your filters", color: "var(--indigo)" },
        { key: "prepared", label: "Prepared", value: f.applications_prepared, hint: "ready, not sent", color: "var(--violet)" },
        { key: "attempted", label: "Attempted", value: f.submission_attempts, hint: "Submit was pressed", color: "var(--cyan)" },
        // Application-level: an auto-applied confirmation also confirms its application,
        // so adding the attempt count as well would count it twice.
        {
          key: "confirmed",
          label: "Confirmed",
          value: f.applications_confirmed,
          hint: "with evidence",
          color: "var(--success)",
        },
        { key: "interviews", label: "Interviews", value: f.interviews, hint: "recorded outcome", color: "var(--warning)" },
        { key: "offers", label: "Offers", value: f.offers, hint: "recorded outcome", color: "var(--success)" },
      ]
    : [];
  const max = Math.max(1, ...stages.map((stage) => stage.value));
  const width = (value: number) => (value <= 0 ? 0 : Math.max(3, (Math.log10(value + 1) / Math.log10(max + 1)) * 100));

  return (
    <div className="orbit-card p-5">
      <div className="mb-4 flex items-baseline justify-between gap-3">
        <div>
          <h2 className="font-heading text-[15px] font-semibold text-text-1">Pipeline</h2>
          <p className="text-xs text-text-3">From discovery to offer. Bars use a log scale.</p>
        </div>
        {f && f.unknown_outcomes ? (
          <span className="text-xs text-warning">{f.unknown_outcomes} outcome(s) unknown</span>
        ) : null}
      </div>
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 7 }).map((_, index) => (
            <Skeleton key={index} className="h-6 w-full" />
          ))}
        </div>
      ) : (
        <ol className="space-y-2.5">
          {stages.map((stage, index) => (
            <li key={stage.key} className="grid grid-cols-[6.5rem_1fr_4.5rem] items-center gap-3 text-sm">
              <span className="truncate text-text-2">{stage.label}</span>
              <div className="relative h-6 overflow-hidden rounded-md bg-surface-2">
                <motion.div
                  className="h-full rounded-md"
                  style={{ background: `linear-gradient(90deg, color-mix(in oklch, ${stage.color} 35%, transparent), ${stage.color})` }}
                  initial={{ width: 0 }}
                  animate={{ width: `${width(stage.value)}%` }}
                  transition={{ duration: 0.8, delay: index * 0.06, ease: [0.22, 1, 0.36, 1] }}
                />
                <span className="absolute inset-y-0 left-2 flex items-center text-[11px] text-text-1/80 mix-blend-normal">
                  {stage.hint}
                </span>
              </div>
              <span className={cn("text-right font-heading font-semibold tabular", stage.value ? "text-text-1" : "text-text-3")}>
                {formatNumber(stage.value)}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
