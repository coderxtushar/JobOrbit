"use client";

import { useQueries } from "@tanstack/react-query";
import { AlertCircle, Layers, Play, ScanSearch } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/shared/empty-state";
import { ScoreRing } from "@/components/shared/score-ring";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/endpoints";
import type { Schemas } from "@/lib/api/client";
import { formatNumber } from "@/lib/formatting";

const SHOWN = 8;

/** Step 2: the backend's own count of what a run would cover, and the first few jobs. */
export function BatchPreviewPanel({
  preview,
  stale,
  error,
  limit,
  dryRun,
  onStart,
  starting,
}: {
  preview: Schemas["BatchPreview"] | null;
  stale: boolean;
  error: unknown;
  limit: number;
  dryRun: boolean;
  onStart: () => void;
  starting: boolean;
}) {
  const ids = preview?.job_ids.slice(0, SHOWN) ?? [];
  const jobs = useQueries({
    queries: ids.map((id) => ({ queryKey: ["job", id], queryFn: () => api.job(id), staleTime: 60_000 })),
  });

  if (error) {
    return (
      <div role="alert" className="flex gap-2 rounded-lg border border-danger/25 bg-danger-soft p-3 text-xs text-text-1">
        <AlertCircle className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden />
        {(error as Error).message}
      </div>
    );
  }

  if (!preview) {
    return (
      <EmptyState
        compact
        icon={ScanSearch}
        title="Preview the selection first"
        description="The backend counts exactly which jobs a run would cover. Nothing is prepared until you start."
      />
    );
  }

  const capped = preview.total >= limit;
  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-3">
        <div>
          <p className="font-heading text-4xl font-semibold leading-none tracking-tight text-text-1 tabular">
            {formatNumber(preview.total)}
          </p>
          <p className="mt-1.5 text-xs text-text-2">
            job{preview.total === 1 ? "" : "s"} would be prepared
            {capped ? <span className="text-text-3"> · capped at your limit of {formatNumber(limit)}</span> : null}
          </p>
        </div>
        <Layers className="size-8 text-violet/40" aria-hidden />
      </div>

      {stale ? (
        <p className="rounded-lg border border-warning/25 bg-warning-soft px-3 py-2 text-xs text-text-1">
          The selection changed since this preview. Preview again before starting.
        </p>
      ) : null}

      {preview.total > 0 ? (
        <ul className="divide-y divide-line rounded-lg border border-line" aria-label="Jobs this run would cover">
          {ids.map((id, index) => {
            const query = jobs[index];
            const job = query?.data;
            return (
              <li key={id} className="flex items-center gap-3 px-3 py-2">
                {job ? (
                  <>
                    <ScoreRing score={job.match?.total_score} band={job.match?.band} size={32} />
                    <div className="min-w-0 flex-1">
                      <Link
                        href={`/jobs/${id}`}
                        className="block truncate text-[13px] font-medium text-text-1 hover:text-violet"
                      >
                        {job.title}
                      </Link>
                      <p className="truncate text-[11.5px] text-text-3">
                        {job.company} · {job.location || "location not stated"}
                      </p>
                    </div>
                  </>
                ) : query?.isError ? (
                  <p className="text-xs text-text-3">Job #{id} could not be loaded</p>
                ) : (
                  <>
                    <Skeleton className="size-8 rounded-full" />
                    <div className="flex-1 space-y-1.5">
                      <Skeleton className="h-3.5 w-3/5" />
                      <Skeleton className="h-3 w-2/5" />
                    </div>
                  </>
                )}
              </li>
            );
          })}
          {preview.total > SHOWN ? (
            <li className="px-3 py-2 text-[11.5px] text-text-3">
              and {formatNumber(preview.total - SHOWN)} more, in score order
            </li>
          ) : null}
        </ul>
      ) : (
        <p className="text-xs text-text-3">
          No job matches this selection. Jobs that are skipped, expired, duplicates or already applied to are never
          included.
        </p>
      )}

      <div className="space-y-2">
        <Button className="w-full" onClick={onStart} disabled={stale || preview.total === 0 || starting}>
          <Play /> {starting ? "Starting…" : dryRun ? `Start dry run (${formatNumber(preview.total)})` : `Prepare ${formatNumber(preview.total)} application${preview.total === 1 ? "" : "s"}`}
        </Button>
        <p className="text-center text-[11px] text-text-3">
          Runs in the background. Only one batch can run at a time.
        </p>
      </div>
    </div>
  );
}
