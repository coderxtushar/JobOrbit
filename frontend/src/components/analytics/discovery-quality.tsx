"use client";

import { Radar } from "lucide-react";
import { useMemo } from "react";

import { EmptyState } from "@/components/shared/empty-state";
import { SectionHeading } from "@/components/shared/page-header";
import { Surface } from "@/components/shared/surface";
import { Skeleton } from "@/components/ui/skeleton";
import type { Schemas } from "@/lib/api/client";
import { formatNumber, formatPercent } from "@/lib/formatting";
import { cn } from "@/lib/utils";

import { CategoryBarChart, CHART, toCategoryData } from "./chart-kit";
import { formatFraction, segmentLabel } from "./labels";

type Analytics = Schemas["JobSearchAnalyticsRead"];

interface Part {
  key: string;
  label: string;
  value: number;
  color: string;
}

/** A single proportion bar with a legend that carries the counts, so colour is never alone. */
function DistributionBar({ parts, label }: { parts: Part[]; label: string }) {
  const total = parts.reduce((sum, part) => sum + part.value, 0);
  if (total === 0) return <p className="text-xs text-text-3">Nothing recorded yet.</p>;
  return (
    <div>
      <div role="img" aria-label={label} className="flex h-2.5 w-full gap-[2px] overflow-hidden rounded-full bg-surface-2">
        {parts
          .filter((part) => part.value > 0)
          .map((part) => (
            <div
              key={part.key}
              title={`${part.label}: ${formatNumber(part.value)}`}
              className="h-full first:rounded-l-full last:rounded-r-full"
              style={{ width: `${(part.value / total) * 100}%`, minWidth: 3, background: part.color }}
            />
          ))}
      </div>
      <ul className="mt-3 space-y-1.5">
        {parts.map((part) => (
          <li key={part.key} className="flex items-center justify-between gap-3 text-xs">
            <span className="flex items-center gap-2 text-text-2">
              <span className="size-2.5 rounded-[3px]" style={{ background: part.color }} />
              {part.label}
            </span>
            <span className="tabular text-text-1">
              {formatNumber(part.value)}
              <span className="ml-1.5 text-text-3">{((part.value / total) * 100).toFixed(1)}%</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const shade = (percent: number) => `color-mix(in oklch, var(--violet) ${percent}%, var(--surface-3))`;

function Stat({ label, value, caption, tone }: { label: string; value: string; caption?: string; tone?: string }) {
  return (
    <div className="min-w-0">
      <p className="truncate text-[11.5px] text-text-3">{label}</p>
      <p className={cn("font-heading text-lg font-semibold tabular", tone ?? "text-text-1")}>{value}</p>
      {caption ? <p className="text-[11px] leading-snug text-text-3">{caption}</p> : null}
    </div>
  );
}

/** Day keys for the discovery window, oldest first, in UTC like the API's own keys. */
function windowDays(days: number): string[] {
  const today = new Date();
  return Array.from({ length: days }, (_, index) => {
    const day = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - (days - 1 - index)));
    return day.toISOString().slice(0, 10);
  });
}

const dayLabel = (key: string) =>
  new Date(`${key}T00:00:00Z`).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "UTC" });

export function DiscoveryPanels({ analytics, loading }: { analytics?: Analytics; loading: boolean }) {
  const discovery = analytics?.discovery;
  const quality = analytics?.quality;

  // A day the API does not list had no new listings, so the window is shown with zeros
  // rather than as a few bars that would read like a trend.
  const byDay = useMemo(() => {
    if (!discovery) return [];
    const counts = discovery.new_by_day ?? {};
    const keys = windowDays(discovery.window_days);
    const extra = Object.keys(counts).filter((key) => !keys.includes(key));
    return [...extra.sort(), ...keys].map((key) => ({ name: key, value: counts[key] ?? 0 }));
  }, [discovery]);
  const anyNew = byDay.some((day) => day.value > 0);

  if (loading || !discovery || !quality) {
    return (
      <div className="grid gap-4 lg:grid-cols-2">
        {Array.from({ length: 4 }, (_, index) => (
          <Skeleton key={index} className="h-64 rounded-xl" />
        ))}
      </div>
    );
  }

  const bands: Part[] = [
    { key: "high", label: "High match", value: quality.band_counts?.high ?? 0, color: "var(--success)" },
    { key: "review", label: "Review", value: quality.band_counts?.review ?? 0, color: CHART.violet },
    { key: "low", label: "Low", value: quality.band_counts?.low ?? 0, color: "var(--line-strong)" },
  ];
  const confidence: Part[] = [
    { key: "high", label: "High confidence", value: quality.confidence_counts?.high ?? 0, color: shade(100) },
    { key: "medium", label: "Medium", value: quality.confidence_counts?.medium ?? 0, color: shade(60) },
    { key: "low", label: "Low", value: quality.confidence_counts?.low ?? 0, color: shade(25) },
  ];
  const freshness: Part[] = [
    { key: "current", label: `Within ${quality.max_job_age_days} days`, value: quality.freshness?.current ?? 0, color: CHART.cyan },
    { key: "stale", label: "Older (stale)", value: quality.freshness?.stale ?? 0, color: "var(--line-strong)" },
    { key: "undated", label: "No posting date", value: quality.freshness?.undated ?? 0, color: "var(--warning)" },
  ];

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Surface className="p-5 lg:col-span-2">
        <SectionHeading
          title="New listings by day"
          description={`Listings first stored in the last ${discovery.window_days} days.`}
        />
        <div className="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="Stored listings" value={formatNumber(discovery.jobs_total)} />
          <Stat label="Scored" value={formatNumber(discovery.jobs_scored)} />
          <Stat
            label="Not scored yet"
            value={formatNumber(discovery.jobs_unscored)}
            tone={discovery.jobs_unscored ? "text-warning" : "text-text-3"}
          />
          <Stat
            label="Failed import runs"
            value={formatNumber(discovery.import_runs_failed)}
            tone={discovery.import_runs_failed ? "text-danger" : "text-text-3"}
          />
        </div>
        {anyNew ? (
          <CategoryBarChart
            data={byDay}
            seriesName="New listings"
            color={CHART.cyan}
            height={200}
            label={`New listings per day over the last ${discovery.window_days} days`}
            labelFormatter={dayLabel}
          />
        ) : (
          <EmptyState
            compact
            icon={Radar}
            title={`No new listings in the last ${discovery.window_days} days`}
            description="Run discovery or import a file from Sources to bring in fresh listings."
          />
        )}
      </Surface>

      <Surface className="p-5">
        <SectionHeading title="Listings by source" description="Where stored listings came from." />
        {Object.keys(discovery.jobs_by_source ?? {}).length ? (
          <CategoryBarChart
            data={toCategoryData(discovery.jobs_by_source)}
            layout="horizontal"
            seriesName="Listings"
            color={CHART.violet}
            label="Stored listings by source"
            labelFormatter={segmentLabel}
          />
        ) : (
          <p className="text-xs text-text-3">No listings stored yet.</p>
        )}
      </Surface>

      <div className="grid gap-4">
        <Surface className="p-5">
          <SectionHeading title="Match bands" description="How scored listings rank against your profile." />
          <DistributionBar parts={bands} label="Scored listings by match band" />
          <p className="mt-3 text-[11.5px] text-text-3">
            {formatNumber(quality.filtered_out)} listing(s) were filtered out by your preferences.
          </p>
        </Surface>
        <Surface className="p-5">
          <SectionHeading title="Score confidence" description="How much evidence each score rests on." />
          <DistributionBar parts={confidence} label="Scored listings by confidence" />
        </Surface>
      </div>

      <Surface className="p-5">
        <SectionHeading
          title="Freshness"
          description={`Measured against your maximum job age of ${quality.max_job_age_days} days.`}
        />
        <DistributionBar parts={freshness} label="Listings by posting age" />
        <div className="mt-4 grid grid-cols-2 gap-4 border-t border-line pt-4">
          <Stat label="Stale rate" value={formatPercent(quality.stale_rate, 1)} caption="of dated listings" />
          <Stat label="Undated rate" value={formatPercent(quality.undated_rate, 2)} caption="of all listings" />
        </div>
      </Surface>

      <Surface className="p-5">
        <SectionHeading title="Duplicates and precision" description="How clean the stored set is." />
        <div className="grid grid-cols-2 gap-4">
          <Stat
            label="Duplicate rate"
            value={formatFraction(quality.duplicate_rate, 2)}
            caption="sightings merged into an existing listing"
          />
          <Stat
            label="Cross-source rate"
            value={formatFraction(quality.cross_source_rate, 2)}
            caption="listings seen on more than one source"
          />
          <Stat
            label="Possible false merges"
            value={formatNumber(quality.false_merge_suspects)}
            tone={quality.false_merge_suspects ? "text-warning" : "text-text-3"}
            caption="see Logs → Duplicates"
          />
          <Stat
            label="Labelled precision"
            value={quality.labelled_precision === null || quality.labelled_precision === undefined ? "—" : formatPercent(quality.labelled_precision, 1)}
            tone={quality.labelled_precision === null || quality.labelled_precision === undefined ? "text-text-3" : undefined}
          />
        </div>
        {quality.labelled_precision_note ? (
          <p className="mt-3 text-[11.5px] leading-relaxed text-text-3">{quality.labelled_precision_note}</p>
        ) : null}
      </Surface>
    </div>
  );
}
