"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Braces, ChevronLeft, ChevronRight, ScrollText } from "lucide-react";
import { useMemo } from "react";

import { DataTable } from "@/components/shared/data-table";
import { EmptyState } from "@/components/shared/empty-state";
import { SectionHeading } from "@/components/shared/page-header";
import { ErrorState } from "@/components/shared/query-state";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/endpoints";
import type { LooseRecord } from "@/lib/api/types";
import type { Tone } from "@/lib/constants/states";
import { formatDateTime, formatNumber, formatRelative, humanize } from "@/lib/formatting";

export const PAGE_SIZE = 25;
const ALL = "__all__";

/**
 * Actions the backend records (from its AuditRepository.record calls). The filter is an
 * exact match on the server, so the list is offered rather than free text; actions seen in
 * the loaded page are merged in so a new one is never unreachable.
 */
const KNOWN_ACTIONS = [
  "answer_bank.deleted",
  "answer_bank.resolved",
  "answer_bank.saved",
  "application.outcome_changed",
  "application.page_opened",
  "application.prepared",
  "application.status_changed",
  "application.updated",
  "autoapply_run_created",
  "batch.cancel_requested",
  "batch.created",
  "batch.finished",
  "email.data_deleted",
  "email.linked",
  "email.processed",
  "email.suggestion_accepted",
  "email.suggestion_dismissed",
  "job.shortlisted",
  "job.skipped",
  "jobs.captured",
  "jobs.import",
  "jobs.scored",
  "profile.onboarding_completed",
  "profile.updated",
  "resume.uploaded",
  "resume_variant.created",
  "source.updated",
];

interface AuditRow {
  id: number;
  action: string;
  entity_type: string;
  entity_id: number | string | null;
  actor: string;
  detail: unknown;
  created_at: string;
}

function toRow(record: LooseRecord): AuditRow {
  return {
    id: typeof record.id === "number" ? record.id : 0,
    action: String(record.action ?? ""),
    entity_type: String(record.entity_type ?? ""),
    entity_id: (record.entity_id as number | string | null | undefined) ?? null,
    actor: String(record.actor ?? ""),
    detail: record.detail ?? null,
    created_at: String(record.created_at ?? ""),
  };
}

function actionTone(action: string): Tone {
  if (/delete|fail|cancel/.test(action)) return "danger";
  if (/import|captured|scored|discover/.test(action)) return "cyan";
  if (/application|autoapply|batch/.test(action)) return "violet";
  if (/source|profile|resume|answer/.test(action)) return "neutral";
  return "neutral";
}

function preview(detail: unknown): string {
  if (detail === null || detail === undefined) return "";
  if (typeof detail !== "object") return String(detail);
  return Object.entries(detail as Record<string, unknown>)
    .slice(0, 4)
    .map(([key, value]) => {
      if (Array.isArray(value) && value.every((item) => typeof item !== "object")) return `${key}: ${value.join(", ")}`;
      return `${key}: ${typeof value === "object" && value !== null ? "…" : String(value)}`;
    })
    .join(" · ");
}

function DetailCell({ detail }: { detail: unknown }) {
  const text = preview(detail);
  if (!text) return <span className="text-text-3">—</span>;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="group flex max-w-[22rem] items-center gap-1.5 rounded text-left text-xs text-text-2 hover:text-text-1"
        >
          <Braces className="size-3 shrink-0 text-text-3 group-hover:text-violet" />
          <span className="truncate">{text}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-96 max-w-[90vw] p-0">
        <pre className="max-h-80 overflow-auto p-3 font-mono text-[11px] leading-relaxed text-text-2">
          {JSON.stringify(detail, null, 2)}
        </pre>
      </PopoverContent>
    </Popover>
  );
}

export function AuditLogTable({
  action,
  page,
  onActionChange,
  onPageChange,
}: {
  action: string | null;
  page: number;
  onActionChange: (action: string | null) => void;
  onPageChange: (page: number) => void;
}) {
  const offset = page * PAGE_SIZE;
  const logs = useQuery({
    queryKey: ["logs", "audit", action ?? "", offset],
    queryFn: () => api.auditLogs({ action: action ?? undefined, limit: PAGE_SIZE, offset }),
    placeholderData: keepPreviousData,
  });

  const rows = useMemo(() => (logs.data?.items ?? []).map(toRow), [logs.data]);
  const actions = useMemo(
    () => Array.from(new Set([...KNOWN_ACTIONS, ...rows.map((row) => row.action), ...(action ? [action] : [])])).sort(),
    [rows, action],
  );
  const total = logs.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const columns = useMemo<ColumnDef<AuditRow, unknown>[]>(
    () => [
      {
        accessorKey: "created_at",
        header: "When",
        cell: ({ row }) => (
          <span className="whitespace-nowrap text-text-2" title={formatDateTime(row.original.created_at)}>
            {formatRelative(row.original.created_at)}
          </span>
        ),
      },
      {
        accessorKey: "action",
        header: "Action",
        cell: ({ row }) => (
          <button
            type="button"
            title="Show only this action"
            onClick={() => onActionChange(row.original.action)}
            className="rounded-full outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <StatusBadge tone={actionTone(row.original.action)} className="font-mono text-[11px]">
              {row.original.action}
            </StatusBadge>
          </button>
        ),
      },
      {
        accessorKey: "entity_type",
        header: "Entity",
        cell: ({ row }) =>
          row.original.entity_type ? (
            <span className="whitespace-nowrap text-text-2">
              {humanize(row.original.entity_type)}
              {row.original.entity_id !== null ? <span className="text-text-3 tabular"> #{row.original.entity_id}</span> : null}
            </span>
          ) : (
            <span className="text-text-3">—</span>
          ),
      },
      {
        accessorKey: "actor",
        header: "Actor",
        cell: ({ row }) => <span className="text-text-2">{row.original.actor || "—"}</span>,
      },
      {
        accessorKey: "detail",
        header: "Detail",
        enableSorting: false,
        cell: ({ row }) => <DetailCell detail={row.original.detail} />,
      },
    ],
    [onActionChange],
  );

  return (
    <div>
      <SectionHeading
        title="Audit log"
        description="Every recorded change, newest first. Click an action to filter by it; click a detail to see all of it."
        actions={
          <Select value={action ?? ALL} onValueChange={(value) => onActionChange(value === ALL ? null : value)}>
            <SelectTrigger size="sm" className="w-56" aria-label="Filter by action">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="max-h-80">
              <SelectItem value={ALL}>All actions</SelectItem>
              {actions.map((item) => (
                <SelectItem key={item} value={item} className="font-mono text-xs">
                  {item}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
      />
      {logs.isError ? (
        <ErrorState error={logs.error} onRetry={() => logs.refetch()} />
      ) : logs.isLoading ? (
        <Skeleton className="h-96 w-full rounded-xl" />
      ) : (
        <>
          <div className={logs.isPlaceholderData ? "overflow-x-auto opacity-60 transition-opacity" : "overflow-x-auto transition-opacity"}>
            <DataTable
              columns={columns}
              data={rows}
              getRowId={(row) => String(row.id)}
              empty={
                <EmptyState
                  compact
                  icon={ScrollText}
                  title={action ? `No “${action}” entries` : "The audit log is empty"}
                  description={action ? "Try another action, or show all." : "Changes you make are recorded here."}
                  action={
                    action ? (
                      <Button size="sm" variant="outline" onClick={() => onActionChange(null)}>
                        Show all actions
                      </Button>
                    ) : undefined
                  }
                  className="m-4"
                />
              }
            />
          </div>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-text-3">
            <p className="tabular">
              {total
                ? `${formatNumber(offset + 1)}–${formatNumber(Math.min(offset + PAGE_SIZE, total))} of ${formatNumber(total)}`
                : "0 entries"}
            </p>
            <div className="flex items-center gap-1.5">
              <Button
                variant="outline"
                size="sm"
                disabled={page === 0 || logs.isFetching}
                onClick={() => onPageChange(page - 1)}
              >
                <ChevronLeft /> Newer
              </Button>
              <span className="px-1 tabular">
                Page {page + 1} of {pages}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={page + 1 >= pages || logs.isFetching}
                onClick={() => onPageChange(page + 1)}
              >
                Older <ChevronRight />
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
