"use client";

import { CheckCircle2, CircleAlert } from "lucide-react";
import { useState } from "react";

import { SectionHeading } from "@/components/shared/page-header";
import { Surface } from "@/components/shared/surface";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import type { Schemas } from "@/lib/api/client";
import { formatDateTime, formatNumber, formatRelative } from "@/lib/formatting";
import { cn } from "@/lib/utils";

const ISO = /\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{2}:\d{2})?/g;

/** The API's detail text with its ISO timestamps shown in local time. */
const readable = (text: string) => text.replace(ISO, (match) => formatDateTime(match));

/** Per-source health: why each source is or is not returning jobs, in the API's words. */
export function DiagnosticsPanel({
  diagnostics,
  loading,
}: {
  diagnostics?: Schemas["Diagnostics"];
  loading: boolean;
}) {
  const [problemsOnly, setProblemsOnly] = useState(false);
  const entries = diagnostics?.entries ?? [];
  const unhealthy = entries.filter((entry) => !entry.healthy).length;
  const visible = [...entries]
    .filter((entry) => !problemsOnly || !entry.healthy)
    .sort((a, b) => Number(a.healthy) - Number(b.healthy));

  return (
    <Surface className="p-5">
      <SectionHeading
        title="Source diagnostics"
        description={
          diagnostics
            ? `${entries.length - unhealthy} healthy · ${unhealthy} not returning jobs. Problems are listed first.`
            : "Why each source is or is not returning jobs."
        }
        actions={
          <div className="flex items-center gap-2">
            <Switch id="diag-problems" size="sm" checked={problemsOnly} onCheckedChange={setProblemsOnly} />
            <Label htmlFor="diag-problems" className="text-xs text-text-2">
              Problems only
            </Label>
          </div>
        }
      />
      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }, (_, index) => (
            <Skeleton key={index} className="h-16 w-full rounded-lg" />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <p className="py-8 text-center text-sm text-text-3">
          {problemsOnly ? "Every source is healthy." : "No sources are configured."}
        </p>
      ) : (
        <ul className="divide-y divide-line rounded-lg border border-line">
          {visible.map((entry) => (
            <li key={entry.source} className="flex items-start gap-3 p-3 transition-colors hover:bg-surface-2/40">
              {entry.healthy ? (
                <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" aria-label="Healthy" />
              ) : (
                <CircleAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-label="Not returning jobs" />
              )}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                  <p className="text-sm font-medium text-text-1">{entry.display_name}</p>
                  <p className="text-[11px] text-text-3">
                    {entry.jobs_last_run === null || entry.jobs_last_run === undefined
                      ? "no runs recorded"
                      : `${formatNumber(entry.jobs_last_run)} new on last run`}
                    {entry.last_run_at ? ` · ${formatRelative(entry.last_run_at)}` : ""}
                  </p>
                </div>
                <p className={cn("mt-0.5 text-xs leading-relaxed", entry.healthy ? "text-text-3" : "text-text-2")}>
                  {entry.reason}
                </p>
                {entry.detail ? <p className="mt-0.5 text-[11px] text-text-3">{readable(entry.detail)}</p> : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Surface>
  );
}
