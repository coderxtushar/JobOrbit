"use client";

import { AlertOctagon, CalendarClock, LineChart } from "lucide-react";
import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Tooltip, XAxis, YAxis } from "recharts";

import { EmptyState } from "@/components/shared/empty-state";
import { SectionHeading } from "@/components/shared/page-header";
import { Surface } from "@/components/shared/surface";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { OutcomeReport } from "@/lib/api/types";
import { formatNumber, humanize } from "@/lib/formatting";

import { axisProps, CategoryBarChart, CHART, ChartFrame, ChartLegend, ChartTooltip, toCategoryData } from "./chart-kit";
import { segmentLabel } from "./labels";

const SERIES = [
  { key: "sent", label: "Sent", color: CHART.violet },
  { key: "confirmed", label: "Confirmed", color: CHART.cyan },
  { key: "interview_rounds", label: "Interview rounds", color: CHART.neutral },
] as const;

function periodLabel(key: string): string {
  // "2026-W47" → "W47 2026"; "2026-11" → "Nov 2026".
  const week = /^(\d{4})-W(\d{2})$/.exec(key);
  if (week) return `W${week[2]} ${week[1]}`;
  const month = /^(\d{4})-(\d{2})$/.exec(key);
  if (month) {
    return new Date(Date.UTC(Number(month[1]), Number(month[2]) - 1, 1)).toLocaleDateString("en-IN", {
      month: "short",
      year: "numeric",
      timeZone: "UTC",
    });
  }
  return key;
}

/**
 * Weekly or monthly activity, drawn only from the periods the API returned. Periods are
 * dated by submitted_at and logged interview rounds; nothing is back-filled.
 */
export function OutcomeSeries({ report, loading }: { report?: OutcomeReport; loading: boolean }) {
  const [period, setPeriod] = useState<"weekly" | "monthly">("weekly");
  const series = report?.[period];
  const data = useMemo(
    () =>
      Object.entries(series ?? {}).map(([key, values]) => ({
        name: key,
        sent: values.sent ?? 0,
        confirmed: values.confirmed ?? 0,
        interview_rounds: values.interview_rounds ?? 0,
      })),
    [series],
  );
  const missing = report?.missing ?? {};
  const missingEntries = Object.entries(missing).filter(([, value]) => value > 0);

  return (
    <Surface className="p-5">
      <SectionHeading
        title="Activity over time"
        description="Sent and confirmed by submission date; interviews by the rounds you log."
        actions={
          <Tabs value={period} onValueChange={(value) => setPeriod(value as "weekly" | "monthly")}>
            <TabsList>
              <TabsTrigger value="weekly" className="text-xs">
                Weekly
              </TabsTrigger>
              <TabsTrigger value="monthly" className="text-xs">
                Monthly
              </TabsTrigger>
            </TabsList>
          </Tabs>
        }
      />
      {loading ? (
        <Skeleton className="h-60 w-full rounded-xl" />
      ) : data.length === 0 ? (
        <EmptyState
          compact
          icon={LineChart}
          title="No dated activity yet"
          description="This fills in once an application is recorded as submitted or an interview round is logged with a date. Prepared applications do not appear here."
        />
      ) : (
        <div className="space-y-3">
          <ChartLegend items={SERIES.map((item) => ({ label: item.label, color: item.color }))} />
          <ChartFrame height={240} label={`${period === "weekly" ? "Weekly" : "Monthly"} sent, confirmed and interview rounds`}>
            <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -12 }} barGap={2} barCategoryGap="24%">
              <CartesianGrid stroke={CHART.grid} vertical={false} strokeDasharray="3 3" />
              <XAxis dataKey="name" tickFormatter={periodLabel} minTickGap={8} {...axisProps} />
              <YAxis allowDecimals={false} width={44} {...axisProps} axisLine={false} />
              <Tooltip
                cursor={{ fill: "var(--violet-soft)" }}
                content={(props) => (
                  <ChartTooltip active={props.active} payload={props.payload} label={props.label} formatLabel={periodLabel} />
                )}
              />
              {SERIES.map((item) => (
                <Bar key={item.key} dataKey={item.key} name={item.label} fill={item.color} radius={[4, 4, 0, 0]} maxBarSize={22} />
              ))}
            </BarChart>
          </ChartFrame>
        </div>
      )}
      {!loading && missingEntries.length ? (
        <p className="mt-3 text-[11.5px] text-text-3">
          Not in the chart because a date was never recorded:{" "}
          {missingEntries.map(([key, value]) => `${humanize(key)} (${formatNumber(value)})`).join(" · ")}
        </p>
      ) : null}
    </Surface>
  );
}

export function FailureReasons({ report, loading }: { report?: OutcomeReport; loading: boolean }) {
  const data = toCategoryData(report?.failure_reasons);
  return (
    <Surface className="p-5">
      <SectionHeading
        title="Failure reasons"
        description="Attempts that failed, need you, or ended with an unknown outcome."
      />
      {loading ? (
        <Skeleton className="h-40 w-full rounded-xl" />
      ) : data.length === 0 ? (
        <EmptyState
          compact
          icon={AlertOctagon}
          title="No failed or stuck attempts"
          description="Auto-apply attempts that fail or need your input are grouped here by cause."
        />
      ) : (
        <CategoryBarChart
          data={data}
          layout="horizontal"
          seriesName="Attempts"
          color={CHART.violet}
          label="Submission attempts by failure category"
          labelFormatter={segmentLabel}
        />
      )}
    </Surface>
  );
}

/** How old postings were when they were sent. Only sent applications with both dates count. */
export function SendFreshness({ report, loading }: { report?: OutcomeReport; loading: boolean }) {
  const freshness = report?.freshness;
  const median = freshness?.median_hours_posted_to_sent ?? null;
  return (
    <Surface className="p-5">
      <SectionHeading title="Posting age when sent" description="Median time from posting to submission." />
      {loading ? (
        <Skeleton className="h-24 w-full rounded-xl" />
      ) : (
        <div className="flex items-start gap-4">
          <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-cyan-soft text-cyan ring-1 ring-inset ring-cyan/20">
            <CalendarClock className="size-5" />
          </span>
          <div className="min-w-0">
            <p className="font-heading text-[28px] font-semibold leading-none text-text-1 tabular">
              {median === null ? (
                <span className="text-text-3">—</span>
              ) : median >= 48 ? (
                <>
                  {(median / 24).toFixed(1)}
                  <span className="ml-1 text-base text-text-3">days</span>
                </>
              ) : (
                <>
                  {median.toFixed(1)}
                  <span className="ml-1 text-base text-text-3">hours</span>
                </>
              )}
            </p>
            <p className="mt-2 text-[11.5px] leading-snug text-text-3">
              {median === null
                ? "Needs a sent application with both a posting date and a submission date."
                : `From ${formatNumber(freshness?.measured ?? 0)} sent application(s) with both dates.`}
              {freshness?.undated_postings
                ? ` ${formatNumber(freshness.undated_postings)} had no posting date and are left out.`
                : ""}
            </p>
          </div>
        </div>
      )}
    </Surface>
  );
}
