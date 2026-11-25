"use client";

import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { History } from "lucide-react";
import { useMemo, useState } from "react";

import { DataTable } from "@/components/shared/data-table";
import { EmptyState } from "@/components/shared/empty-state";
import { SectionHeading } from "@/components/shared/page-header";
import { ErrorState } from "@/components/shared/query-state";
import { StateBadge } from "@/components/shared/status-badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Schemas } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { formatDateTime, formatNumber, humanize } from "@/lib/formatting";

import { IMPORT_STATUS, toImportRunRow, type ImportRunRow } from "./import-status";

const ALL = "__all__";

const num = (key: keyof ImportRunRow, header: string): ColumnDef<ImportRunRow, unknown> => ({
  accessorKey: key,
  header,
  cell: ({ getValue }) => {
    const value = getValue() as number;
    return <span className={value ? "tabular text-text-1" : "tabular text-text-3"}>{formatNumber(value)}</span>;
  },
});

export function ImportHistory({ sources }: { sources: Schemas["SourceRead"][] }) {
  const [source, setSource] = useState<string>(ALL);
  const runs = useQuery({
    queryKey: ["sources", "import-runs", source],
    queryFn: () => api.importRuns({ source: source === ALL ? undefined : source, limit: 50 }),
  });
  const rows = useMemo(() => (runs.data?.items ?? []).map(toImportRunRow), [runs.data]);
  const nameOf = useMemo(() => {
    const names = new Map(sources.map((item) => [item.source as string, item.display_name]));
    return (key: string) => names.get(key) ?? key;
  }, [sources]);

  const columns = useMemo<ColumnDef<ImportRunRow, unknown>[]>(
    () => [
      {
        accessorKey: "started_at",
        header: "Started",
        cell: ({ row }) => <span className="whitespace-nowrap text-text-2">{formatDateTime(row.original.started_at)}</span>,
      },
      {
        accessorKey: "source",
        header: "Source",
        cell: ({ row }) => <span className="font-medium">{nameOf(row.original.source)}</span>,
      },
      {
        accessorKey: "trigger",
        header: "Trigger",
        cell: ({ row }) => <span className="text-text-2">{humanize(row.original.trigger)}</span>,
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <StateBadge value={row.original.status} map={IMPORT_STATUS} />,
      },
      num("jobs_created", "New"),
      num("jobs_updated", "Enriched"),
      num("duplicates_detected", "Duplicates"),
      num("records_invalid", "Invalid"),
      {
        accessorKey: "message",
        header: "Message",
        enableSorting: false,
        cell: ({ row }) => {
          const { message, errors } = row.original;
          if (!message && !errors.length) return <span className="text-text-3">—</span>;
          return (
            <Tooltip>
              <TooltipTrigger asChild>
                <span tabIndex={0} className="line-clamp-1 max-w-72 cursor-help text-xs text-text-2">
                  {message || errors[0]}
                </span>
              </TooltipTrigger>
              <TooltipContent className="max-w-80">
                <p>{message}</p>
                {errors.filter((error) => error !== message).map((error) => (
                  <p key={error} className="mt-1 opacity-80">
                    {error}
                  </p>
                ))}
              </TooltipContent>
            </Tooltip>
          );
        },
      },
    ],
    [nameOf],
  );

  return (
    <div>
      <SectionHeading
        title="Import history"
        description="The 50 most recent import and discovery runs."
        actions={
          <Select value={source} onValueChange={setSource}>
            <SelectTrigger size="sm" className="w-44" aria-label="Filter by source">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All sources</SelectItem>
              {sources.map((item) => (
                <SelectItem key={item.source} value={item.source}>
                  {item.display_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
      />
      {runs.isError ? (
        <ErrorState error={runs.error} onRetry={() => runs.refetch()} />
      ) : runs.isLoading ? (
        <Skeleton className="h-64 w-full rounded-xl" />
      ) : (
        <div className="overflow-x-auto">
          <DataTable
            columns={columns}
            data={rows}
            getRowId={(row) => String(row.id)}
            empty={
              <EmptyState
                compact
                icon={History}
                title="No runs yet"
                description={source === ALL ? "Import a file or run discovery to see it here." : "This source has never run."}
                className="m-4"
              />
            }
          />
        </div>
      )}
    </div>
  );
}
