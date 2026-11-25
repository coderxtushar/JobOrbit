"use client";

import { Clock, Info } from "lucide-react";

import { Surface } from "@/components/shared/surface";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Schemas } from "@/lib/api/client";
import type { OutcomeReport, RateValue } from "@/lib/api/types";
import { formatNumber } from "@/lib/formatting";

import { formatMinutes } from "./labels";

const RATES: { key: keyof OutcomeReport["rates"]; label: string }[] = [
  { key: "interview_rate", label: "Interview rate" },
  { key: "rejection_rate", label: "Rejection rate" },
  { key: "offer_rate", label: "Offer rate" },
  { key: "confirmation_rate", label: "Confirmation rate" },
];

function RateCard({ label, rate, min }: { label: string; rate: RateValue; min: number }) {
  const computed = rate.value !== null;
  return (
    <Surface className="flex flex-col p-4">
      <p className="text-xs font-medium text-text-2">{label}</p>
      <p className="mt-2.5 font-heading text-[28px] font-semibold leading-none tracking-tight tabular">
        {computed ? (
          <span className="text-text-1">
            {rate.value!.toFixed(1)}
            <span className="ml-0.5 text-base text-text-3">%</span>
          </span>
        ) : (
          <span className="text-text-3">—</span>
        )}
      </p>
      <p className="mt-2 text-[11.5px] leading-snug text-text-3">
        {computed ? (
          <>
            <span className="text-text-2 tabular">
              {formatNumber(rate.numerator)} of {formatNumber(rate.denominator)}
            </span>{" "}
            {rate.note}
          </>
        ) : (
          <>{rate.note || `Not computed: needs at least ${min}.`}</>
        )}
      </p>
    </Surface>
  );
}

export function RateCards({ report, loading }: { report?: OutcomeReport; loading: boolean }) {
  if (loading || !report) {
    return (
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {RATES.map((rate) => (
          <Skeleton key={rate.key} className="h-[118px] rounded-xl" />
        ))}
      </div>
    );
  }
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {RATES.map((item) => (
        <RateCard key={item.key} label={item.label} rate={report.rates[item.key]} min={report.min_denominator} />
      ))}
    </div>
  );
}

/**
 * Time saved, which is never measured: two estimates with the assumption printed next to
 * each. The outcome estimate counts only confirmed auto-submissions; the preparation
 * estimate counts drafting time on prepared applications.
 */
export function TimeSavedCard({
  report,
  estimated,
  loading,
}: {
  report?: OutcomeReport;
  estimated?: Schemas["EstimatedMetrics"];
  loading: boolean;
}) {
  return (
    <Surface className="relative overflow-hidden p-5">
      <div className="pointer-events-none absolute -right-16 -top-16 size-48 rounded-full bg-violet-soft blur-3xl" />
      <div className="relative flex items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-violet">Estimate</p>
          <h2 className="mt-1 font-heading text-[15px] font-semibold text-text-1">Time saved</h2>
        </div>
        <span className="grid size-8 place-items-center rounded-lg bg-violet-soft text-violet ring-1 ring-inset ring-violet/20">
          <Clock className="size-4" />
        </span>
      </div>
      {loading ? (
        <div className="relative mt-4 space-y-3">
          <Skeleton className="h-8 w-28" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-8 w-28" />
        </div>
      ) : (
        <div className="relative mt-4 grid gap-4 sm:grid-cols-2">
          <div>
            <p className="text-xs text-text-2">On form filling</p>
            <p className="mt-1 font-heading text-2xl font-semibold text-text-1 tabular">
              {report ? `~${formatMinutes(report.time_saved.estimate_minutes)}` : "—"}
            </p>
            <p className="mt-1.5 text-[11.5px] leading-snug text-text-3 [overflow-wrap:anywhere]">
              {report
                ? `${formatNumber(report.time_saved.confirmed_auto_submissions)} confirmed auto-submission(s) × ${report.time_saved.assumption}.`
                : "Not available."}
            </p>
          </div>
          <div>
            <p className="flex items-center gap-1 text-xs text-text-2">
              On preparation
              <Tooltip>
                <TooltipTrigger asChild>
                  <button type="button" aria-label="How this is estimated" className="text-text-3 hover:text-text-1">
                    <Info className="size-3.5" />
                  </button>
                </TooltipTrigger>
                <TooltipContent className="max-w-64">{estimated?.basis ?? "Not available."}</TooltipContent>
              </Tooltip>
            </p>
            <p className="mt-1 font-heading text-2xl font-semibold text-text-1 tabular">
              {estimated ? `~${formatMinutes(estimated.estimated_minutes_saved)}` : "—"}
            </p>
            <p className="mt-1.5 text-[11.5px] leading-snug text-text-3 [overflow-wrap:anywhere]">
              {estimated?.basis ?? "Not available."}
            </p>
          </div>
        </div>
      )}
    </Surface>
  );
}
