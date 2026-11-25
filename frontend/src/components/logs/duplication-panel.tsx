"use client";

import { useQuery } from "@tanstack/react-query";
import { CopyCheck, GitMerge, Split } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/shared/empty-state";
import { SectionHeading } from "@/components/shared/page-header";
import { ErrorState } from "@/components/shared/query-state";
import { StatusBadge } from "@/components/shared/status-badge";
import { Surface } from "@/components/shared/surface";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/endpoints";
import { formatNumber, humanize } from "@/lib/formatting";

const pct = (fraction: number) => `${(fraction * 100).toFixed(2)}%`;

function Figure({ label, value, caption }: { label: string; value: string; caption?: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface-2/40 p-3">
      <p className="text-[11.5px] text-text-3">{label}</p>
      <p className="mt-0.5 font-heading text-lg font-semibold text-text-1 tabular">{value}</p>
      {caption ? <p className="text-[11px] leading-snug text-text-3">{caption}</p> : null}
    </div>
  );
}

const JobLink = ({ id }: { id: number }) => (
  <Link href={`/jobs/${id}`} className="text-violet tabular hover:underline">
    #{id}
  </Link>
);

/** How duplicates were merged, and the merges the checker thinks may be wrong or missed. */
export function DuplicationPanel() {
  const report = useQuery({ queryKey: ["logs", "duplication"], queryFn: () => api.duplication(25) });
  const data = report.data;

  if (report.isError) return <ErrorState error={report.error} onRetry={() => report.refetch()} />;
  if (report.isLoading || !data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-28 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    );
  }

  const rules = Object.entries(data.sightings_by_rule).sort((a, b) => b[1] - a[1]);
  const overlaps = Object.entries(data.source_pair_overlaps);

  return (
    <div className="space-y-4">
      <Surface className="p-5">
        <SectionHeading
          title="Duplicate detection"
          description="A sighting is one time a listing was seen on a source; duplicates are merged into one stored listing."
          actions={
            <StatusBadge tone={data.is_healthy ? "success" : "warning"}>
              {data.is_healthy ? "No suspect merges" : "Merges to review"}
            </StatusBadge>
          }
        />
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          <Figure label="Stored listings" value={formatNumber(data.jobs_total)} />
          <Figure label="Sightings" value={formatNumber(data.sightings_total)} />
          <Figure label="Merged sightings" value={formatNumber(data.merged_sightings)} caption={`${pct(data.duplicate_rate)} of sightings`} />
          <Figure label="Exact / fuzzy" value={`${formatNumber(data.exact_duplicate_sightings)} / ${formatNumber(data.fuzzy_duplicate_sightings)}`} caption="same id or URL / same fingerprint" />
          <Figure label="Seen on 2+ sources" value={formatNumber(data.multi_source_jobs)} caption={`${pct(data.cross_source_duplicate_rate)} of listings`} />
          <Figure
            label="Applied, multi-source"
            value={`${formatNumber(data.multi_source_jobs_with_application)} / ${formatNumber(data.jobs_with_application)}`}
            caption="listings with an application"
          />
        </div>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-text-3">Sightings by rule</p>
            <ul className="space-y-1 text-xs">
              {rules.map(([rule, count]) => (
                <li key={rule} className="flex justify-between gap-2">
                  <span className="text-text-2">{humanize(rule)}</span>
                  <span className="text-text-1 tabular">{formatNumber(count)}</span>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-text-3">Source overlaps</p>
            {overlaps.length ? (
              <ul className="space-y-1 text-xs">
                {overlaps.map(([pair, count]) => (
                  <li key={pair} className="flex justify-between gap-2">
                    <span className="text-text-2">{pair.split("+").join(" + ")}</span>
                    <span className="text-text-1 tabular">{formatNumber(count)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-text-3">No listing has been seen on two sources.</p>
            )}
          </div>
        </div>
        {data.buckets_skipped.length ? (
          <p className="mt-4 text-[11.5px] leading-relaxed text-text-3">
            Too large to compare pair-by-pair, so not checked for missed merges: {data.buckets_skipped.join(", ")}.
          </p>
        ) : null}
      </Surface>

      <Surface className="p-5">
        <SectionHeading
          title="Possible false merges"
          description="Stored listings whose sightings disagree on title or company. Showing up to 25."
        />
        {data.false_merge_suspects.length ? (
          <ul className="divide-y divide-line rounded-lg border border-line">
            {data.false_merge_suspects.map((suspect) => (
              <li key={suspect.job_id} className="space-y-1 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm text-text-1">
                    <JobLink id={suspect.job_id} /> {suspect.stored_title}
                  </p>
                  <StatusBadge tone="warning" dot={false}>
                    {Math.round(suspect.title_overlap * 100)}% title overlap
                  </StatusBadge>
                </div>
                <p className="text-xs text-text-3">{suspect.reason}</p>
                <p className="text-xs text-text-2">
                  Seen as: {Array.from(new Set(suspect.observed_titles)).join(" · ")}
                  <span className="text-text-3"> — {Array.from(new Set(suspect.observed_companies)).join(", ")} on {suspect.sources.join(", ")}</span>
                </p>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState compact icon={Split} title="No suspect merges" description="Every merged listing's sightings agree." />
        )}
      </Surface>

      <Surface className="p-5">
        <SectionHeading
          title="Possible missed merges"
          description="Separate listings that look like the same job. Showing up to 25."
        />
        {data.missed_merge_suspects.length ? (
          <ul className="divide-y divide-line rounded-lg border border-line">
            {data.missed_merge_suspects.map((suspect) => (
              <li key={suspect.job_ids.join("-")} className="space-y-1 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm text-text-1">
                    {suspect.company}
                    <span className="ml-2 inline-flex gap-1.5 text-xs">
                      {suspect.job_ids.map((id) => (
                        <JobLink key={id} id={id} />
                      ))}
                    </span>
                  </p>
                  <span className="text-xs text-text-3">{suspect.sources.join(" + ")}</span>
                </div>
                <p className="text-xs text-text-2">{Array.from(new Set(suspect.titles)).join(" · ")}</p>
                <p className="text-xs text-text-3">{suspect.reason}</p>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState compact icon={GitMerge} title="No missed merges found" />
        )}
      </Surface>

      <Surface className="p-5">
        <SectionHeading
          title="Company-name collisions"
          description="Different raw company names that normalise to the same employer."
        />
        {data.normalization_collisions.length ? (
          <ul className="space-y-2 text-xs">
            {data.normalization_collisions.map((collision) => (
              <li key={collision.normalized_company} className="flex flex-wrap justify-between gap-2 rounded-lg border border-line p-3">
                <span className="text-text-1">
                  <span className="font-medium">{collision.normalized_company}</span>
                  <span className="text-text-3"> ← {collision.raw_companies.join(", ")}</span>
                </span>
                <span className="text-text-2 tabular">{formatNumber(collision.job_count)} listing(s)</span>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState compact icon={CopyCheck} title="No collisions" description="Each employer name maps to one company." />
        )}
      </Surface>
    </div>
  );
}
