"use client";

import { Gauge, Radar, Telescope } from "lucide-react";
import { useSearchParams } from "next/navigation";

import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import type { Schemas } from "@/lib/api/client";
import { formatNumber, humanize } from "@/lib/formatting";
import { cn } from "@/lib/utils";

import { JobBrowser } from "./job-browser";
import { JobCardSkeleton } from "./job-card";
import { sourceLabel } from "./job-utils";
import { useDiscoverJobs, useScoreJobs } from "./use-job-actions";
import { useUrlFilters } from "./use-url-filters";

function DiscoverDialog({
  open,
  onOpenChange,
  discover,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  discover: ReturnType<typeof useDiscoverJobs>;
}) {
  const results = discover.data;
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && discover.isPending) return; // keep the dialog while the run is in flight
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Radar className="size-4 text-violet" /> Run discovery
          </DialogTitle>
          <DialogDescription>
            Asks every enabled source for new listings through its authorized interface. Sources without one are
            recorded as skipped, never scraped. This can take a while.
          </DialogDescription>
        </DialogHeader>

        {discover.isPending ? (
          <div className="space-y-2" aria-live="polite">
            <p className="text-xs text-text-2">Checking sources…</p>
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-4/5" />
          </div>
        ) : results ? (
          <div className="space-y-2">
            <p className="text-xs text-text-2">
              <span className="font-medium text-text-1">
                {formatNumber(results.reduce((sum, item) => sum + item.jobs_created, 0))} new
              </span>{" "}
              · {formatNumber(results.reduce((sum, item) => sum + item.jobs_updated, 0))} updated ·{" "}
              {formatNumber(results.reduce((sum, item) => sum + item.duplicates_detected, 0))} duplicates across{" "}
              {results.length} source{results.length === 1 ? "" : "s"}
            </p>
            {results.length ? (
              <DiscoveryResults results={results} />
            ) : (
              <p className="text-xs text-text-3">No source is enabled, so nothing was asked.</p>
            )}
          </div>
        ) : discover.isError ? (
          <p className="rounded-lg border border-danger/25 bg-danger-soft p-3 text-xs text-text-1">
            {(discover.error as Error).message}
          </p>
        ) : null}

        <DialogFooter>
          {results ? (
            <Button onClick={() => onOpenChange(false)}>Done</Button>
          ) : (
            <>
              <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={discover.isPending}>
                Cancel
              </Button>
              <Button onClick={() => discover.mutate()} disabled={discover.isPending}>
                <Radar /> {discover.isPending ? "Running…" : discover.isError ? "Try again" : "Run discovery"}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** /jobs: discovery, scoring and the job browser. `?discover=1` opens the discovery confirm. */
export function JobsView() {
  const { setParam } = useUrlFilters();
  const searchParams = useSearchParams();
  const discoverOpen = searchParams.get("discover") === "1";
  const discover = useDiscoverJobs();
  const score = useScoreJobs();

  const setDiscoverOpen = (open: boolean) => {
    if (!open) discover.reset();
    setParam("discover", open ? "1" : null);
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Discover"
        title="Jobs"
        description="Every listing JobOrbit has found, scored against your profile. Open one to see exactly why it matches, and what it is missing."
        actions={
          <>
            <Button
              variant="outline"
              onClick={() => score.mutate({ rescore_all: false, offset: 0 })}
              disabled={score.isPending}
            >
              <Gauge /> {score.isPending ? "Scoring…" : "Score jobs"}
            </Button>
            <Button onClick={() => setDiscoverOpen(true)}>
              <Radar /> Run discovery
            </Button>
          </>
        }
      />
      <JobBrowser
        emptyState={
          <EmptyState
            icon={Telescope}
            title="No jobs yet"
            description="Run discovery to pull listings from your enabled sources, then score them against your profile."
            action={
              <Button size="sm" onClick={() => setDiscoverOpen(true)}>
                <Radar /> Run discovery
              </Button>
            }
          />
        }
      />
      <DiscoverDialog open={discoverOpen} onOpenChange={setDiscoverOpen} discover={discover} />
    </div>
  );
}

export function JobsViewSkeleton() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-4 w-96 max-w-full" />
      </div>
      <Skeleton className="h-10 w-full rounded-xl" />
      <div className="grid gap-5 lg:grid-cols-[15rem_minmax(0,1fr)]">
        <Skeleton className="hidden h-96 rounded-xl lg:block" />
        <div className="space-y-2.5">
          {Array.from({ length: 5 }, (_, index) => (
            <JobCardSkeleton key={index} />
          ))}
        </div>
      </div>
    </div>
  );
}


type DiscoveryResult = Schemas["ImportSummary"];

/**
 * Per-source results, sources that ran first. Sources skipped because they are not
 * configured or not permitted are folded away with their reason, each shown once: the
 * backend repeats the skip reason in `errors`, which previously printed it twice.
 */
function DiscoveryResults({ results }: { results: DiscoveryResult[] }) {
  const skipped = results.filter((item) => item.status.toLowerCase().includes("skip"));
  const ran = results.filter((item) => !item.status.toLowerCase().includes("skip"));
  const row = (item: DiscoveryResult) => {
    const extraErrors = (item.errors ?? []).filter((error) => error !== item.message);
    return (
      <li key={item.import_run_id} className="space-y-0.5 px-3 py-2 text-xs">
        <div className="flex items-center justify-between gap-2">
          <span className="font-medium text-text-1">{sourceLabel(item.source)}</span>
          <span
            className={cn(
              "text-[11px]",
              extraErrors.length ? "text-danger" : item.status.toLowerCase().includes("skip") ? "text-text-3" : "text-success",
            )}
          >
            {humanize(item.status)}
          </span>
        </div>
        {item.status.toLowerCase().includes("skip") ? null : (
          <p className="tabular text-text-3">
            {item.records_received} received · {item.jobs_created} new · {item.jobs_updated} updated
            {item.duplicates_detected ? ` · ${item.duplicates_detected} already stored` : ""}
            {item.records_invalid ? ` · ${item.records_invalid} invalid` : ""}
          </p>
        )}
        {item.message ? <p className="text-text-2">{item.message}</p> : null}
        {extraErrors.slice(0, 2).map((error) => (
          <p key={error} className="text-danger">
            {error}
          </p>
        ))}
      </li>
    );
  };
  return (
    <div className="space-y-2">
      {ran.length ? (
        <div className="max-h-72 overflow-y-auto rounded-lg border border-line">
          <ul className="divide-y divide-line">{ran.map(row)}</ul>
        </div>
      ) : (
        <p className="text-xs text-text-3">No source could be fetched. The skipped sources below say why.</p>
      )}
      {skipped.length ? (
        <details className="group rounded-lg border border-line">
          <summary className="cursor-pointer list-none px-3 py-2 text-xs text-text-3 hover:text-text-1">
            {skipped.length} source{skipped.length === 1 ? " was" : "s were"} skipped (not configured, switched
            off, or not permitted) · show why
          </summary>
          <ul className="max-h-60 divide-y divide-line overflow-y-auto border-t border-line">{skipped.map(row)}</ul>
        </details>
      ) : null}
    </div>
  );
}
