"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";

import { formatNumber } from "@/lib/formatting";
import { cn } from "@/lib/utils";

/**
 * Themed pieces for recharts. Every colour is a CSS variable from globals.css, so charts
 * follow the dark/light theme without re-rendering: the browser resolves `var(--violet)`
 * inside the SVG at paint time.
 */
export const CHART = {
  violet: "var(--violet)",
  cyan: "var(--cyan)",
  neutral: "var(--text-2)",
  muted: "var(--text-3)",
  grid: "var(--line)",
} as const;

export const axisProps = {
  stroke: CHART.muted,
  tick: { fill: CHART.muted, fontSize: 11 },
  tickLine: false,
  axisLine: { stroke: CHART.grid },
} as const;

/** A fixed-height box for a chart; recharts needs explicit dimensions to measure. */
export function ChartFrame({
  height = 220,
  label,
  className,
  children,
}: {
  height?: number;
  /** Accessible summary of what the chart shows. */
  label: string;
  className?: string;
  children: React.ReactElement;
}) {
  return (
    <div role="img" aria-label={label} className={cn("w-full", className)} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        {children}
      </ResponsiveContainer>
    </div>
  );
}

/** Tooltip body in Orbit surfaces: label on top, one row per series with its swatch. */
export function ChartTooltip({
  active,
  payload,
  label,
  formatLabel,
  formatValue = (value: number) => formatNumber(value),
}: Pick<Partial<TooltipContentProps>, "active" | "payload" | "label"> & {
  formatLabel?: (label: string) => string;
  formatValue?: (value: number) => string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const title = label === undefined ? "" : formatLabel ? formatLabel(String(label)) : String(label);
  return (
    <div className="orbit-glass min-w-36 rounded-lg px-3 py-2 text-xs shadow-raised">
      {title ? <p className="mb-1.5 font-medium text-text-1">{title}</p> : null}
      <ul className="space-y-1">
        {payload.map((entry) => (
          <li key={String(entry.dataKey ?? entry.name)} className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-1.5 text-text-2">
              <span
                className="size-2 rounded-[3px]"
                style={{ background: (entry.color as string | undefined) ?? CHART.violet }}
              />
              {String(entry.name ?? entry.dataKey)}
            </span>
            <span className="font-medium text-text-1 tabular">
              {typeof entry.value === "number" ? formatValue(entry.value) : String(entry.value ?? "—")}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** A small legend row; series identity never relies on colour alone, the name sits beside it. */
export function ChartLegend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-2">
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-[3px]" style={{ background: item.color }} />
          {item.label}
        </li>
      ))}
    </ul>
  );
}

export interface CategoryDatum {
  name: string;
  value: number;
}

/**
 * One series as bars: vertical for time (dates on the x axis), horizontal for categories
 * with long names (sources, employers).
 */
export function CategoryBarChart({
  data,
  label,
  seriesName,
  color = CHART.violet,
  layout = "vertical",
  height,
  labelFormatter,
  valueFormatter,
}: {
  data: CategoryDatum[];
  label: string;
  seriesName: string;
  color?: string;
  /** "horizontal" draws category bars left to right (names on the y axis). */
  layout?: "vertical" | "horizontal";
  height?: number;
  labelFormatter?: (label: string) => string;
  valueFormatter?: (value: number) => string;
}) {
  const horizontal = layout === "horizontal";
  const computedHeight = height ?? (horizontal ? Math.max(120, data.length * 30 + 24) : 220);
  const longest = Math.max(0, ...data.map((item) => (labelFormatter ? labelFormatter(item.name) : item.name).length));
  return (
    <ChartFrame height={computedHeight} label={label}>
      <BarChart
        data={data}
        layout={horizontal ? "vertical" : "horizontal"}
        margin={{ top: 4, right: 12, bottom: 0, left: horizontal ? 4 : -12 }}
        barCategoryGap={horizontal ? 6 : "18%"}
      >
        <CartesianGrid stroke={CHART.grid} vertical={horizontal} horizontal={!horizontal} strokeDasharray="3 3" />
        {horizontal ? (
          <>
            <XAxis type="number" allowDecimals={false} {...axisProps} />
            <YAxis
              type="category"
              dataKey="name"
              width={Math.min(150, Math.max(60, longest * 6.5))}
              tickFormatter={labelFormatter}
              {...axisProps}
              axisLine={false}
            />
          </>
        ) : (
          <>
            <XAxis dataKey="name" tickFormatter={labelFormatter} minTickGap={12} {...axisProps} />
            <YAxis allowDecimals={false} width={44} {...axisProps} axisLine={false} />
          </>
        )}
        <Tooltip
          cursor={{ fill: "var(--violet-soft)" }}
          content={(props) => (
            <ChartTooltip
              active={props.active}
              payload={props.payload}
              label={props.label}
              formatLabel={labelFormatter}
              formatValue={valueFormatter}
            />
          )}
        />
        <Bar
          dataKey="value"
          name={seriesName}
          fill={color}
          radius={horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]}
          maxBarSize={horizontal ? 18 : 36}
        />
      </BarChart>
    </ChartFrame>
  );
}

/** Record<string, number> → chart rows, optionally sorted by value. */
export function toCategoryData(
  record: Record<string, number> | undefined | null,
  { sort = true, limit }: { sort?: boolean; limit?: number } = {},
): CategoryDatum[] {
  const rows = Object.entries(record ?? {}).map(([name, value]) => ({ name, value }));
  if (sort) rows.sort((a, b) => b.value - a.value);
  return limit ? rows.slice(0, limit) : rows;
}
