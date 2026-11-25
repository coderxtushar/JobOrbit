"use client";

import { useQuery } from "@tanstack/react-query";
import { BadgeCheck, Briefcase, FilePen, MessagesSquare, Sparkles, Target } from "lucide-react";
import { motion } from "motion/react";

import { KpiCard } from "@/components/shared/kpi-card";
import { ErrorState } from "@/components/shared/query-state";
import { api } from "@/lib/api/endpoints";

import { ActionCenter } from "./action-center";
import { ApplicationPipeline } from "./application-pipeline";
import { DiscoveryChart } from "./discovery-chart";
import { DashboardHero } from "./hero";
import { PipelineFunnel } from "./pipeline-funnel";
import { RecentActivity } from "./recent-activity";
import { TopMatches } from "./top-matches";

const rise = {
  hidden: { opacity: 0, y: 10 },
  show: (index: number) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 0.45, delay: index * 0.05, ease: [0.22, 1, 0.36, 1] as const },
  }),
};

export function DashboardView() {
  const outcomes = useQuery({ queryKey: ["analytics", "outcomes"], queryFn: api.outcomes });
  const analytics = useQuery({ queryKey: ["analytics", "summary"], queryFn: api.analytics });

  const f = outcomes.data?.funnel;
  const bands = analytics.data?.quality.band_counts;
  const relevant = bands ? (bands.high ?? 0) + (bands.review ?? 0) : undefined;
  const interviewRate = outcomes.data?.rates.interview_rate;
  const loading = outcomes.isLoading || analytics.isLoading;

  return (
    <div className="space-y-6">
      <DashboardHero outcomes={outcomes.data} loading={outcomes.isLoading} />

      {outcomes.isError ? <ErrorState error={outcomes.error} onRetry={() => outcomes.refetch()} /> : null}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {[
          { label: "Jobs discovered", value: f?.jobs_discovered, caption: "all sources, all time", icon: Briefcase, accent: "neutral" as const },
          { label: "Relevant jobs", value: relevant, caption: "strong match or worth a look", icon: Sparkles, accent: "violet" as const },
          { label: "Eligible", value: f?.eligible_jobs, caption: "pass every hard filter", icon: Target, accent: "cyan" as const },
          { label: "Prepared", value: f?.applications_prepared, caption: "ready, not sent", icon: FilePen, accent: "violet" as const },
          { label: "Confirmed", value: f?.applications_confirmed, caption: "employer acknowledged", icon: BadgeCheck, accent: "success" as const },
          {
            label: "Interview responses",
            value: f?.interviews,
            caption:
              interviewRate?.value !== null && interviewRate?.value !== undefined
                ? `${interviewRate.value}% of ${interviewRate.denominator} sent`
                : "rate shown from 5 sent applications",
            icon: MessagesSquare,
            accent: "warning" as const,
          },
        ].map((card, index) => (
          <motion.div key={card.label} custom={index} variants={rise} initial="hidden" animate="show">
            <KpiCard {...card} loading={loading} />
          </motion.div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <PipelineFunnel outcomes={outcomes.data} loading={outcomes.isLoading} />
        <ActionCenter analytics={analytics.data} />
      </div>

      <ApplicationPipeline outcomes={analytics.data?.outcomes} loading={analytics.isLoading} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
        <TopMatches />
        <DiscoveryChart discovery={analytics.data?.discovery} loading={analytics.isLoading} />
        <RecentActivity />
      </div>
    </div>
  );
}
