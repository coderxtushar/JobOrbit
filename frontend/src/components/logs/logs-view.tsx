"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCw } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

import { PageHeader } from "@/components/shared/page-header";
import { ErrorState } from "@/components/shared/query-state";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api/endpoints";

import { AuditLogTable } from "./audit-log-table";
import { DiagnosticsPanel } from "./diagnostics-panel";
import { DuplicationPanel } from "./duplication-panel";
import { HealthPanel } from "./health-panel";

const TABS = ["diagnostics", "audit", "duplicates"] as const;
type Tab = (typeof TABS)[number];

export function LogsView() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const queryClient = useQueryClient();

  const tabParam = params.get("tab");
  const tab: Tab = (TABS as readonly string[]).includes(tabParam ?? "") ? (tabParam as Tab) : "diagnostics";
  const action = params.get("action");
  const page = Math.max(0, Number.parseInt(params.get("page") ?? "1", 10) - 1 || 0);

  const diagnostics = useQuery({ queryKey: ["logs", "diagnostics"], queryFn: api.diagnostics });

  /** Keep the tab, filter and page in the URL so a view can be linked and survives reload. */
  const setParams = useCallback(
    (changes: Record<string, string | null>) => {
      const next = new URLSearchParams(params.toString());
      for (const [key, value] of Object.entries(changes)) {
        if (value === null || value === "") next.delete(key);
        else next.set(key, value);
      }
      const query = next.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [params, pathname, router],
  );

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["logs"] });
    void queryClient.invalidateQueries({ queryKey: ["health"] });
  };

  return (
    <div className="space-y-[var(--space-section)]">
      <PageHeader
        eyebrow="System"
        title="Logs and diagnostics"
        description="Health of the API and every source, the audit trail of what changed, and how duplicates were handled."
        actions={
          <Button variant="outline" size="sm" onClick={refresh}>
            <RotateCw /> Refresh
          </Button>
        }
      />

      <HealthPanel diagnostics={diagnostics.data} />

      <Tabs value={tab} onValueChange={(value) => setParams({ tab: value === "diagnostics" ? null : value })}>
        <TabsList>
          <TabsTrigger value="diagnostics">Source diagnostics</TabsTrigger>
          <TabsTrigger value="audit">Audit log</TabsTrigger>
          <TabsTrigger value="duplicates">Duplicates</TabsTrigger>
        </TabsList>
        <TabsContent value="diagnostics" className="mt-3">
          {diagnostics.isError ? (
            <ErrorState error={diagnostics.error} onRetry={() => diagnostics.refetch()} />
          ) : (
            <DiagnosticsPanel diagnostics={diagnostics.data} loading={diagnostics.isLoading} />
          )}
        </TabsContent>
        <TabsContent value="audit" className="mt-3">
          <AuditLogTable
            action={action}
            page={page}
            onActionChange={(next) => setParams({ action: next, page: null })}
            onPageChange={(next) => setParams({ page: next === 0 ? null : String(next + 1) })}
          />
        </TabsContent>
        <TabsContent value="duplicates" className="mt-3">
          <DuplicationPanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export function LogsSkeleton() {
  return (
    <div className="space-y-[var(--space-section)]">
      <div className="space-y-2">
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-4 w-96 max-w-full" />
      </div>
      <Skeleton className="h-52 w-full rounded-xl" />
      <Skeleton className="h-8 w-80" />
      <Skeleton className="h-96 w-full rounded-xl" />
    </div>
  );
}
