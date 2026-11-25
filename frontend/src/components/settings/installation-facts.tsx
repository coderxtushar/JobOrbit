"use client";

import { SectionHeading } from "@/components/shared/page-header";
import { ErrorState } from "@/components/shared/query-state";
import { StatusBadge } from "@/components/shared/status-badge";
import { Surface } from "@/components/shared/surface";
import { Skeleton } from "@/components/ui/skeleton";
import type { UseQueryResult } from "@tanstack/react-query";
import type { Schemas } from "@/lib/api/client";
import type { Health } from "@/lib/api/types";
import type { Tone } from "@/lib/constants/states";

interface Row {
  label: string;
  value: React.ReactNode;
  hint: string;
  envKey?: string;
}

const badge = (tone: Tone, text: string) => <StatusBadge tone={tone}>{text}</StatusBadge>;

/** What this installation is running with, read from /health and /api/diagnostics. */
export function InstallationFacts({
  health,
  diagnostics,
}: {
  health: UseQueryResult<Health>;
  diagnostics?: Schemas["Diagnostics"];
}) {
  const data = health.data;
  const rows: Row[] = data
    ? [
        { label: "Version", value: <span className="font-mono text-xs">{data.version}</span>, hint: "JobOrbit API" },
        {
          label: "Database",
          value: badge(data.database === "ok" ? "success" : "danger", data.database === "ok" ? `Connected · ${data.database_dialect}` : data.database),
          hint: "SQLite by default; PostgreSQL works unchanged",
          envKey: "JA_DATABASE_URL",
        },
        {
          label: "Language model",
          value: badge(data.llm_enabled ? "violet" : "neutral", data.llm_enabled ? data.llm_provider : "None · rule-based"),
          hint: "Optional; everything works without one",
          envKey: "JA_LLM_PROVIDER",
        },
        {
          label: "Scheduler",
          value: badge(data.scheduler_enabled ? "cyan" : "neutral", data.scheduler_enabled ? "On" : "Off"),
          hint: data.scheduler_enabled ? "Runs discovery on an interval" : "No background activity",
          envKey: "JA_SCHEDULER_ENABLED",
        },
        {
          label: "Network exposure",
          value: badge(data.loopback_only ? "success" : "warning", data.loopback_only ? "Loopback only" : "Reachable on the network"),
          hint: data.loopback_only ? "Only this computer can reach the API" : "Requires JA_API_TOKEN",
          envKey: "JA_API_HOST",
        },
        {
          label: "Demo mode",
          value: badge(data.demo_mode ? "warning" : "neutral", data.demo_mode ? "On" : "Off"),
          hint: data.demo_mode ? "Sample data; uploads and source changes are refused" : "Your own data",
          envKey: "JA_DEMO_MODE",
        },
        {
          label: "Display timezone",
          value: <span className="text-sm text-text-1">{diagnostics?.display_timezone ?? "—"}</span>,
          hint: "Timestamps are stored in UTC",
          envKey: "JA_DISPLAY_TIMEZONE",
        },
      ]
    : [];

  return (
    <Surface className="p-5">
      <SectionHeading title="Installation" description="Read from the running API. Change these in .env and restart it." />
      {health.isError ? (
        <ErrorState error={health.error} onRetry={() => health.refetch()} />
      ) : health.isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }, (_, index) => (
            <Skeleton key={index} className="h-10 w-full" />
          ))}
        </div>
      ) : (
        <dl className="divide-y divide-line">
          {rows.map((row) => (
            <div key={row.label} className="grid grid-cols-1 gap-1 py-2.5 sm:grid-cols-[10rem_1fr_auto] sm:items-center sm:gap-4">
              <dt className="text-sm text-text-2">{row.label}</dt>
              <dd className="min-w-0">
                <div>{row.value}</div>
                <p className="mt-0.5 text-[11px] text-text-3">{row.hint}</p>
              </dd>
              {row.envKey ? (
                <code className="hidden font-mono text-[10.5px] text-text-3 sm:block">{row.envKey}</code>
              ) : (
                <span />
              )}
            </div>
          ))}
        </dl>
      )}
    </Surface>
  );
}
