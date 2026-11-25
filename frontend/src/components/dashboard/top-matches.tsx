"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Compass } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/query-state";
import { ScoreRing } from "@/components/shared/score-ring";
import { StateBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/endpoints";
import { BAND } from "@/lib/constants/states";
import { formatRelative } from "@/lib/formatting";

/** The best-scored open jobs that passed every filter. */
export function TopMatches() {
  const jobs = useQuery({
    queryKey: ["jobs", "top-matches"],
    // A wide pool, because the highest raw scores are often filtered out by a hard
    // constraint; only jobs that pass every filter are shown.
    queryFn: () => api.jobs({ sort_by: "score", descending: true, limit: 60, min_score: 50 }),
  });
  const items = (jobs.data?.items ?? []).filter((job) => !job.match?.filtered_out).slice(0, 5);

  return (
    <div className="orbit-card p-5">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h2 className="font-heading text-[15px] font-semibold text-text-1">Best matches</h2>
          <p className="text-xs text-text-3">Highest scores that pass your filters.</p>
        </div>
        <Button asChild size="sm" variant="ghost" className="text-text-2">
          <Link href="/jobs?sort_by=score">
            All jobs <ArrowUpRight className="size-3.5" />
          </Link>
        </Button>
      </div>
      {jobs.isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-14 w-full" />
          ))}
        </div>
      ) : jobs.isError ? (
        <ErrorState error={jobs.error} onRetry={() => jobs.refetch()} />
      ) : items.length === 0 ? (
        <EmptyState
          compact
          icon={Compass}
          title="No strong matches yet"
          description="Discover and score jobs to see your best matches here."
          action={
            <Button asChild size="sm">
              <Link href="/jobs?discover=1">Discover jobs</Link>
            </Button>
          }
        />
      ) : (
        <ul className="-mx-2 space-y-0.5">
          {items.map((job) => (
            <li key={job.id}>
              <Link
                href={`/jobs/${job.id}`}
                className="group flex items-center gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-surface-2"
              >
                <ScoreRing score={job.match?.total_score} band={job.match?.band} size={40} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-medium text-text-1 group-hover:text-violet">
                    {job.title}
                  </span>
                  <span className="block truncate text-xs text-text-3">
                    {job.company} · {job.location || "Location not stated"}
                    {job.posted_at ? ` · ${formatRelative(job.posted_at)}` : ""}
                  </span>
                </span>
                <StateBadge value={job.match?.band} map={BAND} className="hidden sm:inline-flex" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
