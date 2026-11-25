"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { useMemo, useState } from "react";

import { DataTable } from "@/components/shared/data-table";
import { SectionHeading } from "@/components/shared/page-header";
import { Surface } from "@/components/shared/surface";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { OutcomeReport, Segment } from "@/lib/api/types";
import { formatNumber } from "@/lib/formatting";

import { CategoryBarChart, CHART } from "./chart-kit";
import { segmentLabel } from "./labels";

type SegmentKey = "by_source" | "by_job_family" | "by_score_band" | "by_employer";

const TABS: { key: SegmentKey; label: string; note: string }[] = [
  { key: "by_source", label: "Source", note: "Where each listing was first seen." },
  { key: "by_job_family", label: "Job family", note: "Inferred from the title and required skills." },
  { key: "by_score_band", label: "Score band", note: "Your match band for the listing." },
  { key: "by_employer", label: "Employer", note: "Top 20 employers by sent, then discovered." },
];

interface Row extends Segment {
  key: string;
}

const count = (accessor: keyof Segment, header: string): ColumnDef<Row, unknown> => ({
  accessorKey: accessor,
  header,
  cell: ({ getValue }) => {
    const value = getValue() as number;
    return <span className={value ? "tabular text-text-1" : "tabular text-text-3"}>{formatNumber(value)}</span>;
  },
});

export function SegmentBreakdown({ report, loading }: { report?: OutcomeReport; loading: boolean }) {
  const [tab, setTab] = useState<SegmentKey>("by_source");
  const current = TABS.find((item) => item.key === tab)!;

  const rows: Row[] = useMemo(
    () => Object.entries(report?.[tab] ?? {}).map(([key, segment]) => ({ key, ...segment })),
    [report, tab],
  );

  const columns = useMemo<ColumnDef<Row, unknown>[]>(
    () => [
      {
        accessorKey: "key",
        header: current.label,
        cell: ({ getValue }) => (
          <span className="font-medium text-text-1">{tab === "by_employer" ? String(getValue()) : segmentLabel(String(getValue()))}</span>
        ),
      },
      count("discovered", "Discovered"),
      count("sent", "Sent"),
      count("interviews", "Interviews"),
      count("rejections", "Rejections"),
      count("offers", "Offers"),
      {
        accessorKey: "interview_rate",
        header: "Interview rate",
        sortUndefined: "last",
        cell: ({ row }) =>
          row.original.interview_rate === null ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <span tabIndex={0} className="cursor-help text-text-3 underline decoration-dotted underline-offset-4">
                  —
                </span>
              </TooltipTrigger>
              <TooltipContent className="max-w-60">{row.original.interview_rate_note}</TooltipContent>
            </Tooltip>
          ) : (
            <span className="tabular text-text-1">{row.original.interview_rate.toFixed(1)}%</span>
          ),
      },
    ],
    [current.label, tab],
  );

  const chartData = useMemo(
    () =>
      [...rows]
        .sort((a, b) => b.discovered - a.discovered)
        .slice(0, 12)
        .map((row) => ({ name: row.key, value: row.discovered })),
    [rows],
  );

  return (
    <Surface className="p-5">
      <SectionHeading
        title="Segments"
        description={`${current.note} Interview rate needs ${report?.min_denominator ?? 5}+ sent in the segment.`}
        actions={
          <Tabs value={tab} onValueChange={(value) => setTab(value as SegmentKey)}>
            <TabsList>
              {TABS.map((item) => (
                <TabsTrigger key={item.key} value={item.key} className="text-xs">
                  {item.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        }
      />
      {loading ? (
        <Skeleton className="h-64 w-full rounded-xl" />
      ) : (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,5fr)_minmax(0,3fr)]">
          <div className="min-w-0 overflow-x-auto">
            <DataTable
              columns={columns}
              data={rows}
              getRowId={(row) => row.key}
              empty={<p className="py-10 text-center text-sm text-text-3">No listings in this view yet.</p>}
            />
          </div>
          <div className="min-w-0">
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-text-3">
              Discovered by {current.label.toLowerCase()}
              {rows.length > 12 ? " · top 12" : ""}
            </p>
            {chartData.length ? (
              <CategoryBarChart
                data={chartData}
                layout="horizontal"
                seriesName="Discovered"
                color={CHART.violet}
                label={`Listings discovered by ${current.label.toLowerCase()}`}
                labelFormatter={tab === "by_employer" ? undefined : segmentLabel}
              />
            ) : (
              <p className="py-8 text-center text-xs text-text-3">Nothing to chart.</p>
            )}
          </div>
        </div>
      )}
    </Surface>
  );
}
