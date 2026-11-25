"use client";

import { useQuery } from "@tanstack/react-query";
import { Info, RotateCw } from "lucide-react";

import { PageHeader, SectionHeading } from "@/components/shared/page-header";
import { ErrorState } from "@/components/shared/query-state";
import { KpiCard } from "@/components/shared/kpi-card";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/endpoints";

import { DiscoveryPanels } from "./discovery-quality";
import { FailureReasons, OutcomeSeries, SendFreshness } from "./outcome-series";
import { RateCards, TimeSavedCard } from "./rate-cards";
import { SegmentBreakdown } from "./segment-breakdown";
import { SubmissionFunnel } from "./submission-funnel";

export function AnalyticsView() {
  const outcomes = useQuery({ queryKey: ["analytics", "outcomes"], queryFn: api.outcomes });
  const analytics = useQuery({ queryKey: ["analytics", "search"], queryFn: api.analytics });
  const metrics = useQuery({ queryKey: ["analytics", "metrics"], queryFn: api.metrics });
  const estimated = useQuery({ queryKey: ["analytics", "estimated"], queryFn: api.estimatedMetrics });

  const refreshing = outcomes.isFetching || analytics.isFetching || metrics.isFetching || estimated.isFetching;
  const refetchAll = () => {
    void outcomes.refetch();
    void analytics.refetch();
    void metrics.refetch();
    void estimated.refetch();
  };

  const report = outcomes.data;
  const m = metrics.data;

  return (
    <div className="space-y-[var(--space-section)]">
      <PageHeader
        eyebrow="Insights"
        title="Analytics"
        description="What your search has produced, computed only from recorded data. Missing figures show as “—”, never as zero."
        actions={
          <>
            {analytics.data?.demo_mode ? <StatusBadge tone="warning">Demo data</StatusBadge> : null}
            <Button variant="outline" size="sm" onClick={refetchAll} disabled={refreshing}>
              <RotateCw className={refreshing ? "animate-spin" : undefined} /> Refresh
            </Button>
          </>
        }
      />

      <section className="space-y-4">
        {outcomes.isError ? <ErrorState error={outcomes.error} onRetry={() => outcomes.refetch()} /> : null}
        <div className="grid gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <SubmissionFunnel report={report} loading={outcomes.isLoading} />
          <div className="flex flex-col gap-4">
            <TimeSavedCard
              report={report}
              estimated={estimated.data}
              loading={outcomes.isLoading || estimated.isLoading}
            />
            <SendFreshness report={report} loading={outcomes.isLoading} />
          </div>
        </div>
      </section>

      <section>
        <SectionHeading
          title="Conversion rates"
          description={`A rate needs at least ${report?.min_denominator ?? 5} applications behind it; below that it is not computed.`}
        />
        <RateCards report={report} loading={outcomes.isLoading} />
        {report?.notes.length ? (
          <ul className="mt-3 space-y-1">
            {report.notes.map((note) => (
              <li key={note} className="flex items-start gap-2 text-xs text-text-3">
                <Info className="mt-0.5 size-3.5 shrink-0" />
                {note}
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <section className="space-y-4">
        <OutcomeSeries report={report} loading={outcomes.isLoading} />
        <SegmentBreakdown report={report} loading={outcomes.isLoading} />
        <FailureReasons report={report} loading={outcomes.isLoading} />
      </section>

      <section>
        <SectionHeading
          title="Discovery and data quality"
          description="What was found, from where, and how trustworthy it is."
        />
        {analytics.isError ? (
          <ErrorState error={analytics.error} onRetry={() => analytics.refetch()} />
        ) : (
          <DiscoveryPanels analytics={analytics.data} loading={analytics.isLoading} />
        )}
      </section>

      <section>
        <SectionHeading title="Operational counters" description="Running totals since this installation started." />
        {metrics.isError ? (
          <ErrorState error={metrics.error} onRetry={() => metrics.refetch()} />
        ) : (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <KpiCard label="Listings imported" value={m?.jobs_imported} loading={metrics.isLoading} accent="violet" />
            <KpiCard label="Invalid records" value={m?.records_invalid} loading={metrics.isLoading} caption="rejected at import" accent="neutral" />
            <KpiCard label="Duplicates detected" value={m?.duplicates_detected} loading={metrics.isLoading} caption="sightings matched at import" accent="neutral" />
            <KpiCard label="Review queue" value={m?.review_queue_size} loading={metrics.isLoading} caption="prepared, awaiting you" accent="cyan" />
            <KpiCard label="Import failures" value={m?.import_failures} loading={metrics.isLoading} accent={m?.import_failures ? "danger" : "neutral"} />
            <KpiCard label="Audit entries" value={m?.audit_entries} loading={metrics.isLoading} accent="neutral" />
          </div>
        )}
        {analytics.data?.outcomes.oldest_waiting_days !== null && analytics.data?.outcomes.oldest_waiting_days !== undefined ? (
          <p className="mt-3 text-xs text-text-3">
            The oldest application waiting for your review was prepared{" "}
            <span className="text-text-2 tabular">{analytics.data.outcomes.oldest_waiting_days.toFixed(1)} days</span> ago.
          </p>
        ) : null}
      </section>
    </div>
  );
}
