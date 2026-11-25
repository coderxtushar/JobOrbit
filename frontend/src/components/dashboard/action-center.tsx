"use client";

import { useQuery } from "@tanstack/react-query";
import {
  CircleAlert,
  ClipboardCheck,
  Clock4,
  Inbox,
  Mail,
  Octagon,
  ShieldAlert,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { ChevronRight } from "lucide-react";

import { EmptyState } from "@/components/shared/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useNavCounts } from "@/hooks/use-nav-counts";
import { api } from "@/lib/api/endpoints";
import type { Schemas } from "@/lib/api/client";
import { formatNumber } from "@/lib/formatting";
import { cn } from "@/lib/utils";

interface Action {
  key: string;
  icon: LucideIcon;
  title: string;
  detail: string;
  href: string;
  tone: "danger" | "warning" | "violet" | "cyan" | "neutral";
}

const TONE: Record<Action["tone"], string> = {
  danger: "text-danger bg-danger-soft ring-danger/20",
  warning: "text-warning bg-warning-soft ring-warning/20",
  violet: "text-violet bg-violet-soft ring-violet/20",
  cyan: "text-cyan bg-cyan-soft ring-cyan/20",
  neutral: "text-text-2 bg-surface-3 ring-line-strong",
};

/** Everything that is waiting on the user, from live data, most urgent first. */
export function ActionCenter({ analytics }: { analytics?: Schemas["JobSearchAnalyticsRead"] }) {
  const counts = useNavCounts();
  const control = useQuery({ queryKey: ["autoapply", "control"], queryFn: api.control });
  const failed = useQuery({
    queryKey: ["applications", "count", "FAILED"],
    queryFn: () => api.applications({ status: "FAILED", limit: 1 }),
  });
  const suggestions = useQuery({
    queryKey: ["email", "suggestions", "pending"],
    queryFn: () => api.suggestions("pending", 100),
    retry: false,
  });

  const actions: Action[] = [];
  if (control.data?.emergency_stop) {
    actions.push({
      key: "stop",
      icon: Octagon,
      title: "Emergency stop is on",
      detail: control.data.emergency_stop_reason || "No run starts until you clear it.",
      href: "/auto-apply",
      tone: "danger",
    });
  }
  for (const breaker of control.data?.breakers ?? []) {
    if (breaker.open) {
      actions.push({
        key: `breaker-${breaker.target}`,
        icon: ShieldAlert,
        title: `${breaker.target} paused by its circuit breaker`,
        detail: breaker.reason,
        href: "/auto-apply",
        tone: "warning",
      });
    }
  }
  if (counts.unknown) {
    actions.push({
      key: "unknown",
      icon: CircleAlert,
      title: `${counts.unknown} submission outcome(s) unknown`,
      detail: "Never retried automatically. Check, then record what happened.",
      href: "/auto-apply",
      tone: "warning",
    });
  }
  if (counts.inbox) {
    actions.push({
      key: "inbox",
      icon: Inbox,
      title: `${counts.inbox} question(s) need your answer`,
      detail: "Applications waiting on them are blocked until you answer.",
      href: "/action-inbox",
      tone: "violet",
    });
  }
  if (counts.review) {
    const oldest = analytics?.outcomes.oldest_waiting_days;
    actions.push({
      key: "review",
      icon: ClipboardCheck,
      title: `${counts.review} application(s) ready for review`,
      detail: oldest ? `The oldest has waited ${Math.round(oldest)} days.` : "Prepared and waiting for you.",
      href: "/review-queue",
      tone: "violet",
    });
  }
  if (failed.data?.total) {
    actions.push({
      key: "failed",
      icon: XCircle,
      title: `${failed.data.total} application(s) failed`,
      detail: "Open each to see the reason and decide what to do.",
      href: "/applications?status=FAILED",
      tone: "danger",
    });
  }
  if (suggestions.data?.length) {
    actions.push({
      key: "email",
      icon: Mail,
      title: `${suggestions.data.length} status change(s) suggested by email`,
      detail: "Accept or dismiss; nothing is applied automatically.",
      href: "/email",
      tone: "cyan",
    });
  }
  const stale = analytics?.quality.freshness?.stale;
  if (stale) {
    actions.push({
      key: "stale",
      icon: Clock4,
      title: `${formatNumber(stale)} stale listing(s)`,
      detail: `Older than your ${analytics?.quality.max_job_age_days}-day limit; they are kept out of runs.`,
      href: "/jobs?sort_by=posted_at",
      tone: "neutral",
    });
  }

  const loading = control.isLoading && counts.inbox === undefined;
  return (
    <div className="orbit-card flex flex-col p-5">
      <div className="mb-3">
        <h2 className="font-heading text-[15px] font-semibold text-text-1">Action center</h2>
        <p className="text-xs text-text-3">What is waiting on you, most urgent first.</p>
      </div>
      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-12 w-full" />
          ))}
        </div>
      ) : actions.length === 0 ? (
        <EmptyState compact title="All clear" description="Nothing is waiting on you right now." />
      ) : (
        <ul className="-mx-2 space-y-0.5">
          {actions.map((action) => (
            <li key={action.key}>
              <Link
                href={action.href}
                className="group flex items-center gap-3 rounded-lg px-2 py-2.5 transition-colors hover:bg-surface-2"
              >
                <span className={cn("grid size-8 shrink-0 place-items-center rounded-lg ring-1 ring-inset", TONE[action.tone])}>
                  <action.icon className="size-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-medium text-text-1">{action.title}</span>
                  <span className="block truncate text-xs text-text-3">{action.detail}</span>
                </span>
                <ChevronRight className="size-4 text-text-3 transition-transform group-hover:translate-x-0.5" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
