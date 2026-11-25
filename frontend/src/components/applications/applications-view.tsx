"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { motion } from "motion/react";
import { ChevronLeft, ChevronRight, ClipboardCheck, Columns3, FolderKanban, MessageSquareWarning, Rows3, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo } from "react";

import { DataTable } from "@/components/shared/data-table";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { ErrorState } from "@/components/shared/query-state";
import { StateBadge, StatusBadge } from "@/components/shared/status-badge";
import { Surface } from "@/components/shared/surface";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api/endpoints";
import { APPLICATION_STATUS, OUTCOME } from "@/lib/constants/states";
import { formatDate, formatNumber, formatRelative, humanize } from "@/lib/formatting";
import { cn } from "@/lib/utils";

import { OUTCOMES, STATUSES, type Application, type ApplicationStatus, type Outcome } from "./shared";

const BOARD_LIMIT = 200;
const PAGE_SIZE = 25;

/** Board columns in pipeline order. Rare early states share the first column. */
const COLUMNS: { key: string; title: string; statuses: ApplicationStatus[]; accent: string }[] = [
  { key: "early", title: "Not prepared", statuses: ["DISCOVERED", "SCORED", "SHORTLISTED"], accent: "bg-text-3" },
  { key: "review", title: "Ready for review", statuses: ["READY_FOR_REVIEW"], accent: "bg-violet" },
  { key: "approved", title: "Approved", statuses: ["APPROVED"], accent: "bg-indigo" },
  { key: "submitted", title: "Submitted", statuses: ["SUBMITTED"], accent: "bg-cyan" },
  { key: "unknown", title: "Outcome unknown", statuses: ["SUBMISSION_UNKNOWN"], accent: "bg-warning" },
  { key: "confirmed", title: "Confirmed", statuses: ["CONFIRMED"], accent: "bg-success" },
  { key: "closed", title: "Skipped or failed", statuses: ["SKIPPED", "FAILED"], accent: "bg-danger" },
];

export function ApplicationsView() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const view = params.get("view") === "table" ? "table" : "board";
  const statusParam = params.get("status");
  const outcomeParam = params.get("outcome");
  const status = STATUSES.includes(statusParam as ApplicationStatus) ? (statusParam as ApplicationStatus) : undefined;
  const outcome = OUTCOMES.includes(outcomeParam as Outcome) ? (outcomeParam as Outcome) : undefined;
  const page = Math.max(0, Number(params.get("page") ?? 0) || 0);

  const setParams = (updates: Record<string, string | null>) => {
    const next = new URLSearchParams(params.toString());
    for (const [key, value] of Object.entries(updates)) {
      if (value === null || value === "") next.delete(key);
      else next.set(key, value);
    }
    const search = next.toString();
    router.replace(search ? `${pathname}?${search}` : pathname, { scroll: false });
  };

  const limit = view === "board" ? BOARD_LIMIT : PAGE_SIZE;
  const offset = view === "board" ? 0 : page * PAGE_SIZE;
  const query = useQuery({
    queryKey: ["applications", "list", { status, outcome, limit, offset }],
    queryFn: () => api.applications({ status, outcome, limit, offset }),
    placeholderData: keepPreviousData,
  });

  const filtered = Boolean(status || outcome);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Pipeline"
        title="Applications"
        description="Every application you have prepared, from review to outcome. Submitted means you or a permitted platform sent it; only Confirmed has evidence."
        actions={
          <Button asChild variant="outline">
            <Link href="/review-queue">
              <ClipboardCheck /> Review queue
            </Link>
          </Button>
        }
      />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <Tabs value={view} onValueChange={(next) => setParams({ view: next === "table" ? "table" : null, page: null })}>
          <TabsList>
            <TabsTrigger value="board" className="px-3">
              <Columns3 /> Board
            </TabsTrigger>
            <TabsTrigger value="table" className="px-3">
              <Rows3 /> Table
            </TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="flex flex-1 flex-wrap items-center gap-2 sm:justify-end">
          <Select value={status ?? "all"} onValueChange={(next) => setParams({ status: next === "all" ? null : next, page: null })}>
            <SelectTrigger className="w-44" aria-label="Filter by status">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              {STATUSES.map((value) => (
                <SelectItem key={value} value={value}>
                  {APPLICATION_STATUS[value]?.label ?? humanize(value)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={outcome ?? "all"} onValueChange={(next) => setParams({ outcome: next === "all" ? null : next, page: null })}>
            <SelectTrigger className="w-40" aria-label="Filter by outcome">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All outcomes</SelectItem>
              {OUTCOMES.map((value) => (
                <SelectItem key={value} value={value}>
                  {OUTCOME[value]?.label ?? humanize(value)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {filtered ? (
            <Button variant="ghost" size="sm" onClick={() => setParams({ status: null, outcome: null, page: null })}>
              <X /> Clear
            </Button>
          ) : null}
          <span className="text-xs text-text-3 tabular">
            {query.data ? `${formatNumber(query.data.total)} application(s)` : " "}
          </span>
        </div>
      </div>

      {query.isPending ? (
        view === "board" ? (
          <div className="flex gap-3 overflow-hidden">
            {Array.from({ length: 5 }).map((_, index) => (
              <Skeleton key={index} className="h-80 w-72 shrink-0 rounded-xl" />
            ))}
          </div>
        ) : (
          <Skeleton className="h-96 w-full rounded-xl" />
        )
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : query.data.total === 0 ? (
        <EmptyState
          icon={FolderKanban}
          title={filtered ? "Nothing matches these filters" : "No applications yet"}
          description={
            filtered
              ? "Clear the filters to see every application."
              : "Prepare an application from Job discovery, or run auto-apply, and it appears here."
          }
          action={
            filtered ? (
              <Button size="sm" variant="outline" onClick={() => setParams({ status: null, outcome: null })}>
                Clear filters
              </Button>
            ) : (
              <Button asChild size="sm">
                <Link href="/jobs">Find jobs</Link>
              </Button>
            )
          }
        />
      ) : view === "board" ? (
        <Board items={query.data.items} total={query.data.total} />
      ) : (
        <TableView
          items={query.data.items}
          total={query.data.total}
          page={page}
          fetching={query.isFetching}
          onPage={(next) => setParams({ page: next ? String(next) : null })}
        />
      )}
    </div>
  );
}

function Board({ items, total }: { items: Application[]; total: number }) {
  const grouped = useMemo(
    () =>
      COLUMNS.map((column) => ({
        ...column,
        items: items.filter((item) => column.statuses.includes(item.status)),
      })),
    [items],
  );
  return (
    <div className="space-y-2">
      {total > items.length ? (
        <p className="text-xs text-text-3">
          The board shows {formatNumber(items.length)} of {formatNumber(total)} applications. Use the table view to page through all of them.
        </p>
      ) : null}
      <div className="-mx-[var(--space-page-x)] overflow-x-auto px-[var(--space-page-x)] pb-2">
        <div className="flex min-w-max gap-3">
          {grouped.map((column, columnIndex) => (
            <section
              key={column.key}
              aria-label={column.title}
              className="flex w-72 shrink-0 flex-col rounded-xl border border-line bg-surface-2/30"
            >
              <header className="flex items-center gap-2 px-3 py-2.5">
                <span className={cn("size-2 rounded-full", column.accent)} />
                <h2 className="flex-1 text-xs font-semibold text-text-1">{column.title}</h2>
                <span className="rounded-full bg-surface-3 px-1.5 text-[11px] font-medium text-text-2 tabular">{column.items.length}</span>
              </header>
              <div className="flex max-h-[68vh] flex-col gap-2 overflow-y-auto px-2 pb-2">
                {column.items.length === 0 ? (
                  <p className="rounded-lg border border-dashed border-line px-3 py-6 text-center text-[11px] text-text-3">Empty</p>
                ) : (
                  column.items.map((item, index) => (
                    <motion.div
                      key={item.id}
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.25, delay: Math.min(0.3, columnIndex * 0.03 + index * 0.02) }}
                    >
                      <BoardCard item={item} showStatus={column.statuses.length > 1} />
                    </motion.div>
                  ))
                )}
              </div>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}

function BoardCard({ item, showStatus }: { item: Application; showStatus: boolean }) {
  const blocking = item.blocking_questions?.length ?? 0;
  return (
    <Link href={`/applications/${item.id}`} className="block rounded-xl focus-visible:outline-offset-2">
      <Surface interactive className="space-y-2 rounded-lg p-3">
        <div className="min-w-0">
          <p className="truncate text-[11px] font-medium uppercase tracking-wide text-text-3">{item.job_company || "—"}</p>
          <p className="line-clamp-2 text-sm font-medium leading-snug text-text-1">{item.job_title || `Job ${item.job_id}`}</p>
        </div>
        <div className="flex flex-wrap gap-1">
          {showStatus ? <StateBadge value={item.status} map={APPLICATION_STATUS} /> : null}
          {item.outcome !== "pending" ? <StateBadge value={item.outcome} map={OUTCOME} /> : null}
          {blocking ? (
            <StatusBadge tone="warning" dot={false}>
              <MessageSquareWarning className="size-3" /> {blocking} to answer
            </StatusBadge>
          ) : null}
        </div>
        {item.next_action ? <p className="line-clamp-2 text-[11.5px] leading-snug text-text-3">{item.next_action}</p> : null}
        <div className="flex items-center justify-between text-[11px] text-text-3">
          <span>{humanize(item.platform)}</span>
          <span>{formatRelative(item.updated_at)}</span>
        </div>
      </Surface>
    </Link>
  );
}

function TableView({
  items,
  total,
  page,
  fetching,
  onPage,
}: {
  items: Application[];
  total: number;
  page: number;
  fetching: boolean;
  onPage: (page: number) => void;
}) {
  const router = useRouter();
  const columns = useMemo<ColumnDef<Application, unknown>[]>(
    () => [
      {
        id: "job",
        header: "Job",
        accessorFn: (row) => `${row.job_company} ${row.job_title}`,
        cell: ({ row }) => (
          <div className="min-w-0 max-w-[22rem]">
            <Link
              href={`/applications/${row.original.id}`}
              onClick={(event) => event.stopPropagation()}
              className="block truncate font-medium text-text-1 hover:text-violet"
            >
              {row.original.job_title || `Job ${row.original.job_id}`}
            </Link>
            <p className="truncate text-xs text-text-3">{row.original.job_company || "—"}</p>
          </div>
        ),
      },
      {
        id: "status",
        header: "Status",
        accessorKey: "status",
        cell: ({ row }) => <StateBadge value={row.original.status} map={APPLICATION_STATUS} />,
      },
      {
        id: "outcome",
        header: "Outcome",
        accessorKey: "outcome",
        cell: ({ row }) => <StateBadge value={row.original.outcome} map={OUTCOME} />,
      },
      {
        id: "blocking",
        header: "To answer",
        accessorFn: (row) => row.blocking_questions?.length ?? 0,
        cell: ({ getValue }) => {
          const count = getValue() as number;
          return count ? <span className="text-warning tabular">{count}</span> : <span className="text-text-3">—</span>;
        },
      },
      {
        id: "platform",
        header: "Platform",
        accessorKey: "platform",
        cell: ({ row }) => <span className="text-text-2">{humanize(row.original.platform)}</span>,
      },
      {
        id: "follow_up",
        header: "Follow up",
        accessorKey: "follow_up_date",
        cell: ({ row }) => <span className="text-text-2 tabular">{formatDate(row.original.follow_up_date)}</span>,
      },
      {
        id: "updated",
        header: "Updated",
        accessorKey: "updated_at",
        cell: ({ row }) => <span className="text-text-3">{formatRelative(row.original.updated_at)}</span>,
      },
    ],
    [],
  );
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  return (
    <div className={cn("space-y-3 transition-opacity", fetching && "opacity-70")}>
      <DataTable
        columns={columns}
        data={items}
        getRowId={(row) => String(row.id)}
        onRowClick={(row) => router.push(`/applications/${row.id}`)}
      />
      <div className="flex items-center justify-between text-xs text-text-3">
        <span className="tabular">
          {formatNumber(page * PAGE_SIZE + (items.length ? 1 : 0))}–{formatNumber(page * PAGE_SIZE + items.length)} of {formatNumber(total)}
        </span>
        <div className="flex items-center gap-1.5">
          <Button size="sm" variant="outline" disabled={page === 0} onClick={() => onPage(page - 1)} aria-label="Previous page">
            <ChevronLeft />
          </Button>
          <span className="tabular">
            Page {page + 1} of {pages}
          </span>
          <Button size="sm" variant="outline" disabled={page + 1 >= pages} onClick={() => onPage(page + 1)} aria-label="Next page">
            <ChevronRight />
          </Button>
        </div>
      </div>
    </div>
  );
}
