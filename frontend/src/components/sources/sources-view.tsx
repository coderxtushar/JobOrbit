"use client";

import { useQuery } from "@tanstack/react-query";
import { Plug } from "lucide-react";
import { useMemo, useState } from "react";

import { EmptyState } from "@/components/shared/empty-state";
import { KpiCard } from "@/components/shared/kpi-card";
import { PageHeader, SectionHeading } from "@/components/shared/page-header";
import { ErrorState } from "@/components/shared/query-state";
import { Surface } from "@/components/shared/surface";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useHealth } from "@/hooks/use-health";
import { api } from "@/lib/api/endpoints";

import { CaptureExtension } from "./capture-extension";
import { DiscoveryRunner } from "./discovery-runner";
import { ImportHistory } from "./import-history";
import { ImportPanel } from "./import-panel";
import { PlatformsPanel } from "./platforms-panel";
import { canDiscover, SourceList } from "./source-list";

type Filter = "all" | "discovery" | "import" | "attention";

export function SourcesView() {
  const sources = useQuery({ queryKey: ["sources"], queryFn: api.sources });
  const health = useHealth();
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<string[] | null>(null);

  const list = useMemo(() => sources.data ?? [], [sources.data]);
  // Until the user changes it, every source that can run discovery is ticked.
  const effectiveSelected = selected ?? list.filter(canDiscover).map((item) => item.source);
  const needsAttention = (item: (typeof list)[number]) =>
    item.consecutive_failures > 0 || Boolean(item.last_error) || item.status_detail.startsWith("Not usable");

  const filtered = list.filter((item) => {
    if (filter === "discovery") return item.capabilities.authorized_discovery_enabled;
    if (filter === "import") return !item.capabilities.authorized_discovery_enabled;
    if (filter === "attention") return needsAttention(item);
    return true;
  });

  const counts = {
    on: list.filter((item) => item.enabled).length,
    discovery: list.filter(canDiscover).length,
    attention: list.filter(needsAttention).length,
  };

  return (
    <div className="space-y-[var(--space-section)]">
      <PageHeader
        eyebrow="Discovery"
        title="Sources"
        description="Where listings come from, what each platform permits, and how to bring jobs in. Nothing is scraped; sources without a published interface are import-only."
      />

      {health.data?.demo_mode ? (
        <p className="rounded-xl border border-warning/25 bg-warning-soft px-4 py-3 text-xs leading-relaxed text-text-1">
          This is a demo deployment. Changing sources, running discovery and importing files are refused here; the API
          explains why when you try.
        </p>
      ) : null}

      <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard label="Sources" value={sources.data ? list.length : null} loading={sources.isLoading} accent="neutral" />
        <KpiCard label="Turned on" value={sources.data ? counts.on : null} loading={sources.isLoading} accent="violet" />
        <KpiCard
          label="Ready for discovery"
          value={sources.data ? counts.discovery : null}
          loading={sources.isLoading}
          accent="cyan"
          caption="on, with a published interface"
        />
        <KpiCard
          label="Need attention"
          value={sources.data ? counts.attention : null}
          loading={sources.isLoading}
          accent={counts.attention ? "warning" : "neutral"}
          caption="failing or not usable"
        />
      </section>

      <section>
        <SectionHeading
          title="Platform assistants"
          description="What each platform allows JobOrbit to do. Open one for the details."
        />
        <PlatformsPanel />
      </section>

      <section>
        <SectionHeading
          title="Sources and discovery"
          description="Turn sources on or off, narrow what each may do, and run discovery for the ones you tick."
          actions={
            <Tabs value={filter} onValueChange={(value) => setFilter(value as Filter)}>
              <TabsList>
                <TabsTrigger value="all" className="text-xs">
                  All
                </TabsTrigger>
                <TabsTrigger value="discovery" className="text-xs">
                  Discovery
                </TabsTrigger>
                <TabsTrigger value="import" className="text-xs">
                  Import only
                </TabsTrigger>
                <TabsTrigger value="attention" className="text-xs">
                  Attention{counts.attention ? ` · ${counts.attention}` : ""}
                </TabsTrigger>
              </TabsList>
            </Tabs>
          }
        />
        {sources.isError ? (
          <ErrorState error={sources.error} onRetry={() => sources.refetch()} />
        ) : (
          <div className="space-y-3">
            {sources.data ? (
              <DiscoveryRunner sources={list} selected={effectiveSelected} onSelectedChange={setSelected} />
            ) : null}
            <Surface className="overflow-hidden">
              {sources.isLoading ? (
                <div className="space-y-px">
                  {Array.from({ length: 6 }, (_, index) => (
                    <div key={index} className="flex items-center gap-3 px-4 py-4">
                      <Skeleton className="size-4" />
                      <div className="flex-1 space-y-1.5">
                        <Skeleton className="h-4 w-40" />
                        <Skeleton className="h-3 w-72" />
                      </div>
                      <Skeleton className="h-5 w-9 rounded-full" />
                    </div>
                  ))}
                </div>
              ) : filtered.length ? (
                <SourceList sources={filtered} selected={effectiveSelected} onSelectedChange={setSelected} />
              ) : (
                <EmptyState
                  compact
                  icon={Plug}
                  title={filter === "attention" ? "Every source is healthy" : "No sources in this view"}
                  className="m-4"
                />
              )}
            </Surface>
            <p className="px-1 text-[11.5px] text-text-3">
              A capability can only be narrowed here, never widened past what the platform permits. Feed and board
              settings (company boards, feed switches) live in <code className="text-[11px]">.env</code>; see Settings.
            </p>
          </div>
        )}
      </section>

      <section>
        <ImportPanel sources={list} />
      </section>

      <section>
        <ImportHistory sources={list} />
      </section>

      <section>
        <CaptureExtension />
      </section>
    </div>
  );
}
