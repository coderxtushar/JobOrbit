"use client";

import Link from "next/link";

import { EmptyState } from "@/components/shared/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import type { Schemas } from "@/lib/api/client";
import { APPLICATION_STATUS, OUTCOME, type Tone } from "@/lib/constants/states";
import { formatNumber } from "@/lib/formatting";
import { cn } from "@/lib/utils";

/** Backend application statuses in lifecycle order, then what employers did back. */
const STATUS_ORDER = [
  "SHORTLISTED",
  "READY_FOR_REVIEW",
  "APPROVED",
  "SUBMISSION_UNKNOWN",
  "SUBMITTED",
  "CONFIRMED",
  "FAILED",
  "SKIPPED",
];
const OUTCOME_ORDER = ["screening", "interviewing", "offer", "accepted", "rejected", "no_response", "withdrawn"];

const BAR: Record<Tone, string> = {
  neutral: "bg-text-3",
  violet: "bg-violet",
  cyan: "bg-cyan",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
};

function Column({
  label,
  value,
  tone,
  href,
}: {
  label: string;
  value: number;
  tone: Tone;
  href: string;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "group flex min-w-[7.5rem] flex-1 flex-col gap-2 rounded-xl border border-line bg-surface-2/40 p-3 transition-colors hover:border-line-strong hover:bg-surface-2",
        value === 0 && "opacity-60",
      )}
    >
      <span className="flex items-center gap-1.5 text-[11.5px] text-text-2">
        <span className={cn("size-1.5 rounded-full", BAR[tone])} />
        {label}
      </span>
      <span className="font-heading text-xl font-semibold text-text-1 tabular">{formatNumber(value)}</span>
    </Link>
  );
}

export function ApplicationPipeline({
  outcomes,
  loading,
}: {
  outcomes?: Schemas["OutcomeAnalyticsRead"];
  loading: boolean;
}) {
  const byStatus = outcomes?.applications_by_status ?? {};
  const byOutcome = outcomes?.applications_by_outcome ?? {};
  const total = Object.values(byStatus).reduce((sum, value) => sum + value, 0);
  const statuses = STATUS_ORDER.filter((status) => status in byStatus || ["READY_FOR_REVIEW", "SUBMITTED", "CONFIRMED"].includes(status));
  const outcomesShown = OUTCOME_ORDER.filter((outcome) => (byOutcome[outcome] ?? 0) > 0);

  return (
    <div className="orbit-card p-5">
      <div className="mb-4">
        <h2 className="font-heading text-[15px] font-semibold text-text-1">Applications</h2>
        <p className="text-xs text-text-3">
          {total ? `${formatNumber(total)} application(s) by status. Prepared is never counted as sent.` : "By status, once you prepare some."}
        </p>
      </div>
      {loading ? (
        <Skeleton className="h-20 w-full" />
      ) : total === 0 ? (
        <EmptyState
          compact
          title="No applications yet"
          description="Prepare one from a job, or many at once with bulk preparation."
        />
      ) : (
        <div className="space-y-4">
          <div className="flex gap-2 overflow-x-auto pb-1">
            {statuses.map((status) => (
              <Column
                key={status}
                label={APPLICATION_STATUS[status]?.label ?? status}
                value={byStatus[status] ?? 0}
                tone={APPLICATION_STATUS[status]?.tone ?? "neutral"}
                href={`/applications?status=${status}`}
              />
            ))}
          </div>
          {outcomesShown.length ? (
            <div>
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-text-3">Employer responses</p>
              <div className="flex flex-wrap gap-2">
                {outcomesShown.map((outcome) => (
                  <Column
                    key={outcome}
                    label={OUTCOME[outcome]?.label ?? outcome}
                    value={byOutcome[outcome] ?? 0}
                    tone={OUTCOME[outcome]?.tone ?? "neutral"}
                    href={`/applications?outcome=${outcome}`}
                  />
                ))}
              </div>
            </div>
          ) : (
            <p className="text-xs text-text-3">No employer response recorded yet.</p>
          )}
        </div>
      )}
    </div>
  );
}
