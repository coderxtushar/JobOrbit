"use client";

import { motion, useReducedMotion } from "motion/react";

import { Surface } from "@/components/shared/surface";
import { SectionHeading } from "@/components/shared/page-header";
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
 * Discovered → offers as one column of stages. Bars use a log scale because the stages
 * span orders of magnitude; the printed count is always the real number. Attempts (Submit
 * was pressed) and confirmations (confirmation evidence seen) are separate stages, and the
 * attempt outcomes are broken out below so an unclear attempt never reads as sent.
 */
export function SubmissionFunnel({ report, loading }: { report?: OutcomeReport; loading: boolean }) {
  const reduced = useReducedMotion();
  const f = report?.funnel;
  const stages: Stage[] = f
    ? [
        { key: "discovered", label: "Discovered", value: f.jobs_discovered, hint: "every stored listing", color: "var(--text-3)" },
        { key: "eligible", label: "Eligible", value: f.eligible_jobs, hint: "scored and not filtered out", color: "var(--indigo)" },
        { key: "prepared", label: "Prepared", value: f.applications_prepared, hint: "drafted for review, not sent", color: "var(--violet)" },
        { key: "attempts", label: "Submission attempts", value: f.submission_attempts, hint: "auto-apply pressed Submit", color: "var(--cyan)" },
        {
          key: "confirmed",
          label: "Confirmed",
          value: f.applications_confirmed,
          hint: "applications with confirmation recorded",
          color: "var(--success)",
        },
        { key: "interviews", label: "Interviews", value: f.interviews, hint: "outcome you recorded", color: "var(--violet)" },
        { key: "offers", label: "Offers", value: f.offers, hint: "outcome you recorded", color: "var(--success)" },
      ]
    : [];
  const max = Math.max(1, ...stages.map((stage) => stage.value));
  const width = (value: number) =>
    value <= 0 ? 0 : Math.max(1.5, (Math.log10(value + 1) / Math.log10(max + 1)) * 100);

  const breakdown = f
    ? [
        { label: "Confirmed by auto-apply", value: f.confirmed_submissions, tone: "text-success" },
        { label: "Outcome unknown", value: f.unknown_outcomes, tone: "text-warning" },
        { label: "Failed after Submit", value: f.failed_submissions, tone: "text-danger" },
        { label: "Failed before Submit", value: f.failed_before_submit, tone: "text-danger" },
        { label: "Waiting on you", value: f.waiting_on_you, tone: "text-warning" },
        { label: "Marked submitted (any route)", value: f.applications_marked_submitted, tone: "text-text-1" },
      ]
    : [];

  return (
    <Surface className="p-5">
      <SectionHeading
        title="Submission funnel"
        description="Counts from recorded data. Bar length uses a log scale; the number is exact."
      />
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 7 }, (_, index) => (
            <Skeleton key={index} className="h-7 w-full" />
          ))}
        </div>
      ) : (
        <>
          <ol className="space-y-2.5">
            {stages.map((stage, index) => (
              <li key={stage.key} className="grid grid-cols-[minmax(0,9.5rem)_1fr_auto] items-center gap-3 sm:grid-cols-[11rem_1fr_5rem]">
                <div className="min-w-0">
                  <p className="truncate text-[13px] font-medium text-text-1">{stage.label}</p>
                  <p className="truncate text-[11px] text-text-3">{stage.hint}</p>
                </div>
                <div className="h-2.5 overflow-hidden rounded-full bg-surface-2">
                  <motion.div
                    className="h-full rounded-full"
                    style={{ background: stage.color }}
                    initial={reduced ? false : { width: 0 }}
                    animate={{ width: `${width(stage.value)}%` }}
                    transition={{ duration: 0.7, delay: index * 0.05, ease: [0.22, 1, 0.36, 1] }}
                  />
                </div>
                <p
                  className={cn(
                    "text-right font-heading text-[15px] font-semibold tabular",
                    stage.value === 0 ? "text-text-3" : "text-text-1",
                  )}
                >
                  {formatNumber(stage.value)}
                </p>
              </li>
            ))}
          </ol>
          <div className="mt-5 border-t border-line pt-4">
            <p className="mb-2.5 text-[11px] font-semibold uppercase tracking-wider text-text-3">
              What happened to submission attempts
            </p>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 sm:grid-cols-3">
              {breakdown.map((item) => (
                <div key={item.label} className="min-w-0">
                  <dt className="truncate text-[11.5px] text-text-3">{item.label}</dt>
                  <dd className={cn("font-heading text-base font-semibold tabular", item.value ? item.tone : "text-text-3")}>
                    {formatNumber(item.value)}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="mt-3 text-[11.5px] leading-relaxed text-text-3">
              Prepared applications are never counted as sent. &ldquo;Confirmed&rdquo; above counts applications;
              &ldquo;Confirmed by auto-apply&rdquo; counts attempts whose confirmation page was captured.
            </p>
          </div>
        </>
      )}
    </Surface>
  );
}
