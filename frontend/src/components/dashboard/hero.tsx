"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Layers, Radar, Target } from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";

import { OrbitBackdrop } from "@/components/brand/orbit-backdrop";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/endpoints";
import type { OutcomeReport } from "@/lib/api/types";
import { formatNumber } from "@/lib/formatting";

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

/** One honest sentence about where the search stands, built only from recorded figures. */
function summary(outcomes: OutcomeReport | undefined): string {
  if (!outcomes) return "";
  const f = outcomes.funnel;
  if (f.jobs_discovered === 0) return "No jobs yet. Start by discovering jobs from your sources.";
  const parts = [
    `${formatNumber(f.jobs_discovered)} jobs discovered`,
    `${formatNumber(f.eligible_jobs)} pass your filters`,
    `${formatNumber(f.applications_prepared)} applications prepared`,
  ];
  // Applications recorded as submitted or confirmed, which already include auto-applied ones.
  const sent = f.applications_marked_submitted;
  parts.push(sent ? `${formatNumber(sent)} sent` : "none sent yet");
  return `${parts.join(" · ")}.`;
}

export function DashboardHero({ outcomes, loading }: { outcomes?: OutcomeReport; loading: boolean }) {
  const profile = useQuery({ queryKey: ["profile"], queryFn: api.profile });
  const firstName = profile.data?.full_name?.trim().split(/\s+/)[0];

  return (
    <section className="orbit-card relative isolate overflow-hidden px-6 py-7 sm:px-8 sm:py-9">
      <OrbitBackdrop className="-z-10" />
      <div className="absolute inset-0 -z-20 bg-[radial-gradient(40rem_18rem_at_0%_0%,var(--violet-soft),transparent_70%)]" />
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
        className="max-w-2xl"
      >
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-violet">
          Discover · Match · Prepare · Apply · Track
        </p>
        <h1 className="mt-3 font-heading text-[28px] font-semibold leading-tight tracking-tight text-text-1 sm:text-[34px]">
          {greeting()}
          {firstName ? `, ${firstName}` : ""}. <span className="orbit-gradient-text">Your search is in orbit.</span>
        </h1>
        <div className="mt-3 min-h-5 text-sm text-text-2">
          {loading ? <Skeleton className="h-4 w-96 max-w-full" /> : summary(outcomes)}
        </div>
        <div className="mt-6 flex flex-wrap gap-2.5">
          <Button asChild className="shadow-glow">
            <Link href="/jobs?discover=1">
              <Radar /> Discover jobs
            </Link>
          </Button>
          <Button asChild variant="outline" className="bg-surface-1/60 backdrop-blur">
            <Link href="/bulk">
              <Layers /> Prepare applications
            </Link>
          </Button>
          <Button asChild variant="ghost" className="text-text-2 hover:text-text-1">
            <Link href="/auto-apply">
              <Target /> Open auto-apply preflight <ArrowRight className="size-3.5" />
            </Link>
          </Button>
        </div>
      </motion.div>
    </section>
  );
}
