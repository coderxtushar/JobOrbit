"use client";

import { Activity, Bot, Clock4, Database, Globe, Lock, Server, Sparkles } from "lucide-react";

import { ErrorState } from "@/components/shared/query-state";
import { StatusBadge } from "@/components/shared/status-badge";
import { Surface } from "@/components/shared/surface";
import { Skeleton } from "@/components/ui/skeleton";
import { useHealth } from "@/hooks/use-health";
import type { Schemas } from "@/lib/api/client";
import type { Tone } from "@/lib/constants/states";
import { formatRelative } from "@/lib/formatting";

interface Fact {
  icon: typeof Activity;
  label: string;
  value: string;
  tone: Tone;
  detail?: string;
}

/** The API's own health and configuration, from /health and /api/diagnostics. */
export function HealthPanel({ diagnostics }: { diagnostics?: Schemas["Diagnostics"] }) {
  const health = useHealth();
  const data = health.data;

  if (health.isError) return <ErrorState error={health.error} onRetry={() => health.refetch()} />;

  const facts: Fact[] = data
    ? [
        {
          icon: Activity,
          label: "API",
          value: data.status === "ok" ? "Healthy" : data.status,
          tone: data.status === "ok" ? "success" : "danger",
          detail: `version ${data.version}`,
        },
        {
          icon: Database,
          label: "Database",
          value: data.database === "ok" ? "Connected" : data.database,
          tone: data.database === "ok" ? "success" : "danger",
          detail: data.database_dialect,
        },
        {
          icon: Sparkles,
          label: "Language model",
          value: data.llm_enabled ? data.llm_provider : "Off",
          tone: data.llm_enabled ? "violet" : "neutral",
          detail: data.llm_enabled ? "drafts use the model" : "rule-based generation",
        },
        {
          icon: Clock4,
          label: "Scheduler",
          value: data.scheduler_enabled ? "On" : "Off",
          tone: data.scheduler_enabled ? "cyan" : "neutral",
          detail: data.scheduler_enabled ? "runs discovery on a timer" : "nothing runs in the background",
        },
        {
          icon: Lock,
          label: "Network",
          value: data.loopback_only ? "Loopback only" : "Exposed",
          tone: data.loopback_only ? "success" : "warning",
          detail: data.loopback_only ? "reachable from this computer only" : "reachable from the network",
        },
        {
          icon: Bot,
          label: "Sources",
          value: diagnostics
            ? `${diagnostics.entries.filter((entry) => entry.healthy).length} of ${diagnostics.entries.length} healthy`
            : "—",
          tone: diagnostics
            ? diagnostics.entries.every((entry) => entry.healthy)
              ? "success"
              : "warning"
            : "neutral",
          detail: "details in Diagnostics below",
        },
        {
          icon: Server,
          label: "Deployment",
          value: data.demo_mode ? "Demo" : "Personal",
          tone: data.demo_mode ? "warning" : "neutral",
          detail: data.demo_mode ? "writes are restricted" : "your own data",
        },
        {
          icon: Globe,
          label: "Display timezone",
          value: diagnostics?.display_timezone ?? "—",
          tone: "neutral",
          detail: "timestamps are stored in UTC",
        },
      ]
    : [];

  return (
    <Surface className="p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 className="font-heading text-[15px] font-semibold text-text-1">System health</h2>
          <p className="text-xs text-text-3">
            {health.dataUpdatedAt ? `Checked ${formatRelative(new Date(health.dataUpdatedAt).toISOString())} · refreshes every 30s` : "Checking…"}
          </p>
        </div>
        {data ? (
          <StatusBadge tone={data.status === "ok" && data.database === "ok" ? "success" : "danger"}>
            {data.status === "ok" && data.database === "ok" ? "All systems normal" : "Degraded"}
          </StatusBadge>
        ) : null}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {health.isLoading
          ? Array.from({ length: 8 }, (_, index) => <Skeleton key={index} className="h-[74px] rounded-lg" />)
          : facts.map((fact) => (
              <div key={fact.label} className="flex items-start gap-3 rounded-lg border border-line bg-surface-2/40 p-3">
                <fact.icon className="mt-0.5 size-4 shrink-0 text-text-3" />
                <div className="min-w-0">
                  <p className="text-[11.5px] text-text-3">{fact.label}</p>
                  <div className="mt-0.5">
                    <StatusBadge tone={fact.tone}>{fact.value}</StatusBadge>
                  </div>
                  {fact.detail ? <p className="mt-1 truncate text-[11px] text-text-3">{fact.detail}</p> : null}
                </div>
              </div>
            ))}
      </div>
    </Surface>
  );
}
