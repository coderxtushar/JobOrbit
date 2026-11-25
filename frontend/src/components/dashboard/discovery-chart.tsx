"use client";

import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { EmptyState } from "@/components/shared/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import type { Schemas } from "@/lib/api/client";
import { formatNumber } from "@/lib/formatting";

/** New jobs per day over the backend's window, zero-filled only for days inside that window. */
export function DiscoveryChart({
  discovery,
  loading,
}: {
  discovery?: Schemas["DiscoveryAnalyticsRead"];
  loading: boolean;
}) {
  const window = discovery?.window_days ?? 14;
  const byDay = discovery?.new_by_day ?? {};
  const data = Array.from({ length: window }, (_, index) => {
    const date = new Date();
    date.setDate(date.getDate() - (window - 1 - index));
    const key = date.toISOString().slice(0, 10);
    return {
      key,
      label: date.toLocaleDateString("en-IN", { day: "numeric", month: "short" }),
      jobs: byDay[key] ?? 0,
    };
  });
  const total = data.reduce((sum, row) => sum + row.jobs, 0);
  const sources = Object.entries(discovery?.jobs_by_source ?? {}).slice(0, 5);
  const sourceTotal = Object.values(discovery?.jobs_by_source ?? {}).reduce((sum, value) => sum + value, 0);

  return (
    <div className="orbit-card p-5">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <div>
          <h2 className="font-heading text-[15px] font-semibold text-text-1">Discovery</h2>
          <p className="text-xs text-text-3">New jobs per day, last {window} days.</p>
        </div>
        <span className="font-heading text-sm font-semibold text-text-1 tabular">{formatNumber(total)}</span>
      </div>
      {loading ? (
        <Skeleton className="h-40 w-full" />
      ) : total === 0 ? (
        <EmptyState compact title="Nothing new in this window" description="Run discovery to fetch fresh listings." />
      ) : (
        <div className="h-40">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 6, right: 4, bottom: 0, left: -24 }}>
              <defs>
                <linearGradient id="discovery-fill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--violet)" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="var(--violet)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="var(--line)" vertical={false} />
              <XAxis dataKey="label" tick={{ fill: "var(--text-3)", fontSize: 11 }} tickLine={false} axisLine={false} interval="preserveStartEnd" minTickGap={24} />
              <YAxis tick={{ fill: "var(--text-3)", fontSize: 11 }} tickLine={false} axisLine={false} allowDecimals={false} />
              <Tooltip
                cursor={{ stroke: "var(--line-strong)" }}
                contentStyle={{
                  background: "var(--popover)",
                  border: "1px solid var(--line-strong)",
                  borderRadius: 10,
                  fontSize: 12,
                  color: "var(--text-1)",
                }}
                labelStyle={{ color: "var(--text-2)" }}
              />
              <Area type="monotone" dataKey="jobs" name="New jobs" stroke="var(--violet)" strokeWidth={2} fill="url(#discovery-fill)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
      {sources.length ? (
        <div className="mt-4 space-y-1.5">
          {sources.map(([source, count]) => (
            <div key={source} className="grid grid-cols-[6rem_1fr_3.5rem] items-center gap-2 text-xs">
              <span className="truncate capitalize text-text-2">{source}</span>
              <div className="h-1.5 overflow-hidden rounded-full bg-surface-2">
                <div className="h-full rounded-full bg-cyan/70" style={{ width: `${(count / Math.max(1, sourceTotal)) * 100}%` }} />
              </div>
              <span className="text-right text-text-3 tabular">{formatNumber(count)}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
