"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Ban, FlaskConical, History, Inbox, ListChecks, Play, RotateCw } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState, errorMessage } from "@/components/shared/query-state";
import { StateBadge, StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/endpoints";
import { RUN_STATUS } from "@/lib/constants/states";
import { formatDateTime, formatNumber, formatRelative, humanize } from "@/lib/formatting";
import { cn } from "@/lib/utils";

import {
  ACTIVE_STATUSES,
  ITEM_ORDER,
  ITEM_STATUS,
  finishedCount,
  type BatchDetail,
  type BatchItem,
  type BatchItemStatus,
  type BatchRun,
} from "./batch-utils";

/* ---------------- progress bar ---------------- */

const SEGMENTS: { key: "prepared" | "needs" | "skipped" | "failed"; className: string; label: string }[] = [
  { key: "prepared", className: "bg-success", label: "prepared" },
  { key: "needs", className: "bg-warning", label: "need action" },
  { key: "skipped", className: "bg-text-3", label: "skipped" },
  { key: "failed", className: "bg-danger", label: "failed" },
];

function RunBar({ run, className }: { run: BatchRun; className?: string }) {
  const total = Math.max(run.total_items, 1);
  const values = {
    prepared: run.prepared_count,
    needs: run.needs_action_count,
    skipped: run.skipped_count,
    failed: run.failed_count,
  };
  return (
    <div
      className={cn("flex h-1.5 overflow-hidden rounded-full bg-surface-3", className)}
      role="img"
      aria-label={SEGMENTS.map((segment) => `${values[segment.key]} ${segment.label}`).join(", ") + ` of ${run.total_items}`}
    >
      {SEGMENTS.map((segment) =>
        values[segment.key] ? (
          <div
            key={segment.key}
            className={cn("h-full transition-[width] duration-500", segment.className)}
            style={{ width: `${(values[segment.key] / total) * 100}%` }}
          />
        ) : null,
      )}
    </div>
  );
}

/* ---------------- run list ---------------- */

export function BatchRunList({
  activeId,
  onSelect,
}: {
  activeId: number | null;
  onSelect: (id: number) => void;
}) {
  const runs = useQuery({
    queryKey: ["batches"],
    queryFn: () => api.batches(20, 0),
    refetchInterval: (query) => (query.state.data?.items.some((run) => ACTIVE_STATUSES.has(run.status)) ? 3000 : false),
  });

  if (runs.isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 3 }, (_, index) => (
          <Skeleton key={index} className="h-16 w-full rounded-lg" />
        ))}
      </div>
    );
  }
  if (runs.isError) return <ErrorState error={runs.error} onRetry={() => runs.refetch()} />;
  const items = runs.data?.items ?? [];
  if (!items.length) {
    return <EmptyState compact icon={History} title="No runs yet" description="Runs you start appear here with their results." />;
  }
  return (
    <ul className="space-y-1.5" aria-label="Batch runs">
      {items.map((run) => (
        <li key={run.id}>
          <button
            type="button"
            onClick={() => onSelect(run.id)}
            aria-current={run.id === activeId ? "true" : undefined}
            className={cn(
              "w-full space-y-2 rounded-lg border px-3 py-2.5 text-left transition-colors",
              run.id === activeId
                ? "border-violet/40 bg-violet-soft"
                : "border-line bg-surface-1 hover:border-line-strong hover:bg-surface-2",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 text-[13px] font-medium text-text-1">
                Run #{run.id}
                {run.dry_run ? <FlaskConical className="size-3.5 text-cyan" aria-label="Dry run" /> : null}
              </span>
              <StateBadge value={run.status} map={RUN_STATUS} />
            </div>
            <RunBar run={run} />
            <p className="text-[11px] text-text-3 tabular">
              {formatNumber(run.total_items)} job{run.total_items === 1 ? "" : "s"} · {formatRelative(run.started_at)}
            </p>
          </button>
        </li>
      ))}
    </ul>
  );
}

/* ---------------- run detail ---------------- */

function CountTile({
  label,
  value,
  tone,
  href,
  hrefLabel,
}: {
  label: string;
  value: number;
  tone: string;
  href?: string;
  hrefLabel?: string;
}) {
  return (
    <div className="rounded-lg border border-line bg-surface-2/50 p-3">
      <p className="flex items-center gap-1.5 text-[11px] text-text-3">
        <span aria-hidden className={cn("size-1.5 rounded-full", tone)} />
        {label}
      </p>
      <p className="mt-1 font-heading text-xl font-semibold text-text-1 tabular">{formatNumber(value)}</p>
      {href && value > 0 ? (
        <Link href={href} className="mt-0.5 inline-flex items-center gap-0.5 text-[11px] text-violet hover:underline">
          {hrefLabel} <ArrowUpRight className="size-3" aria-hidden />
        </Link>
      ) : null}
    </div>
  );
}

function SelectionSummary({ selection }: { selection: unknown }) {
  if (!selection || typeof selection !== "object") return null;
  const entries = Object.entries(selection as Record<string, unknown>).filter(([, value]) => {
    if (value === null || value === undefined || value === false || value === "") return false;
    if (Array.isArray(value)) return value.length > 0;
    return true;
  });
  if (!entries.length) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {entries.map(([key, value]) => (
        <span key={key} className="rounded-md border border-line bg-surface-2 px-1.5 py-0.5 text-[11px] text-text-2">
          {humanize(key)}: <span className="text-text-1">{Array.isArray(value) ? value.join(", ") : String(value === true ? "yes" : value)}</span>
        </span>
      ))}
    </div>
  );
}

function ItemRow({ item, index }: { item: BatchItem; index: number }) {
  const reduced = useReducedMotion();
  const link =
    item.status === "needs_action"
      ? { href: "/action-inbox", label: "Answer in action inbox" }
      : item.status === "prepared"
        ? { href: "/review-queue", label: "Review" }
        : null;
  return (
    <motion.li
      initial={reduced ? false : { opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, delay: reduced ? 0 : Math.min(index, 15) * 0.015 }}
      className="flex flex-col gap-2 px-3 py-2.5 sm:flex-row sm:items-center"
    >
      <div className="min-w-0 flex-1">
        <Link
          href={`/jobs/${item.job_id}`}
          className="block truncate text-[13px] font-medium text-text-1 hover:text-violet"
        >
          {item.job_title || `Job #${item.job_id}`}
        </Link>
        <p className="truncate text-[11.5px] text-text-3">
          {item.job_company || "Unknown company"}
          {item.detail ? ` · ${item.detail}` : ""}
          {item.attempts > 1 ? ` · ${item.attempts} attempts` : ""}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <StateBadge value={item.status} map={ITEM_STATUS} />
        {link ? (
          <Button size="xs" variant="ghost" asChild>
            <Link href={link.href}>
              {link.label} <ArrowUpRight />
            </Link>
          </Button>
        ) : null}
      </div>
    </motion.li>
  );
}

export function BatchRunDetailView({ runId }: { runId: number }) {
  const client = useQueryClient();
  const [filter, setFilter] = useState<BatchItemStatus | "all">("all");
  const run = useQuery({
    queryKey: ["batch", runId],
    queryFn: () => api.batch(runId),
    refetchInterval: (query) => (query.state.data && ACTIVE_STATUSES.has(query.state.data.status) ? 2000 : false),
  });

  const onDone = (detail: BatchDetail) => {
    client.setQueryData(["batch", runId], detail);
    void client.invalidateQueries({ queryKey: ["batches"] });
    void client.invalidateQueries({ queryKey: ["jobs"] });
  };
  const cancel = useMutation({
    mutationFn: () => api.cancelBatch(runId),
    onSuccess: (detail) => {
      onDone(detail);
      toast.success(`Stopping run #${runId}`, { description: "Items already prepared stay prepared." });
    },
    onError: (error) => toast.error("Could not cancel", { description: errorMessage(error) }),
  });
  const resume = useMutation({
    mutationFn: () => api.resumeBatch(runId),
    onSuccess: (detail) => {
      onDone(detail);
      toast.success(`Resumed run #${runId}`, { description: "Only unfinished items are picked up." });
    },
    onError: (error) => toast.error("Could not resume", { description: errorMessage(error) }),
  });

  if (run.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-2 w-full" />
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {Array.from({ length: 4 }, (_, index) => (
            <Skeleton key={index} className="h-20 rounded-lg" />
          ))}
        </div>
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }
  if (run.isError || !run.data) return <ErrorState error={run.error} onRetry={() => run.refetch()} />;

  const detail = run.data;
  const counts = detail.status_counts ?? {};
  const active = ACTIVE_STATUSES.has(detail.status);
  const done = finishedCount(detail);
  const percent = detail.total_items ? Math.round((done / detail.total_items) * 100) : 100;
  const items = (detail.items ?? []).filter((item) => filter === "all" || item.status === filter);
  // The backend resumes every item not yet prepared, needing action or skipped.
  const unfinished =
    (counts.queued ?? 0) + (counts.in_progress ?? 0) + (counts.cancelled ?? 0) + (counts.failed ?? 0);
  const onlyFailed = unfinished > 0 && unfinished === (counts.failed ?? 0);
  const present = ITEM_ORDER.filter((status) => (counts[status] ?? 0) > 0);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h3 className="flex flex-wrap items-center gap-2 font-heading text-lg font-semibold text-text-1">
            Run #{detail.id}
            <StateBadge value={detail.status} map={RUN_STATUS} />
            {detail.dry_run ? (
              <StatusBadge tone="cyan" dot={false}>
                <FlaskConical className="size-3" aria-hidden /> Dry run · nothing written
              </StatusBadge>
            ) : null}
          </h3>
          <p className="text-xs text-text-3">
            Started {formatDateTime(detail.started_at)}
            {detail.finished_at ? ` · finished ${formatDateTime(detail.finished_at)}` : ""} · concurrency{" "}
            {detail.concurrency} · up to {detail.max_attempts} attempts
          </p>
        </div>
        <div className="flex gap-2">
          {active ? (
            <Button
              size="sm"
              variant="destructive"
              onClick={() => cancel.mutate()}
              disabled={cancel.isPending || detail.cancel_requested || detail.status === "cancelling"}
            >
              <Ban /> {detail.cancel_requested || detail.status === "cancelling" ? "Stopping…" : "Cancel run"}
            </Button>
          ) : null}
          {!active && unfinished > 0 ? (
            <Button
              size="sm"
              variant="outline"
              onClick={() => resume.mutate()}
              disabled={resume.isPending}
              title="Picks up queued, cancelled and failed items. Finished items are never redone."
            >
              <Play /> {resume.isPending ? "Resuming…" : onlyFailed ? `Retry ${unfinished} failed` : `Resume ${unfinished} unfinished`}
            </Button>
          ) : null}
          <Button size="icon-sm" variant="ghost" onClick={() => run.refetch()} aria-label="Refresh run">
            <RotateCw className={cn(run.isFetching && "animate-spin")} />
          </Button>
        </div>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs">
          <span className="text-text-2">
            {active ? "Preparing…" : "Processed"}{" "}
            <span className="font-medium text-text-1 tabular">
              {formatNumber(done)} of {formatNumber(detail.total_items)}
            </span>
          </span>
          <span className="text-text-3 tabular">{percent}%</span>
        </div>
        <div className="relative">
          <RunBar run={detail} className="h-2" />
          {active ? (
            <div
              aria-hidden
              className="pointer-events-none absolute inset-0 animate-shimmer rounded-full bg-[linear-gradient(90deg,transparent,color-mix(in_oklch,var(--violet)_35%,transparent),transparent)] bg-[length:200%_100%]"
            />
          ) : null}
        </div>
        {detail.message ? <p className="text-[11.5px] text-text-3">{detail.message}</p> : null}
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        <CountTile label="Prepared" value={counts.prepared ?? detail.prepared_count} tone="bg-success" href="/review-queue" hrefLabel="Review queue" />
        <CountTile label="Needs action" value={counts.needs_action ?? detail.needs_action_count} tone="bg-warning" href="/action-inbox" hrefLabel="Action inbox" />
        <CountTile label="Skipped · duplicate" value={counts.skipped_duplicate ?? 0} tone="bg-text-3" />
        <CountTile label="Skipped · ineligible" value={counts.skipped_ineligible ?? 0} tone="bg-text-3" />
        <CountTile label="Failed" value={counts.failed ?? detail.failed_count} tone="bg-danger" />
      </div>

      <SelectionSummary selection={detail.selection} />

      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Filter items by status">
          <Button
            size="xs"
            variant={filter === "all" ? "secondary" : "ghost"}
            aria-pressed={filter === "all"}
            onClick={() => setFilter("all")}
          >
            All <span className="tabular text-text-3">{detail.items?.length ?? 0}</span>
          </Button>
          {present.map((status) => (
            <Button
              key={status}
              size="xs"
              variant={filter === status ? "secondary" : "ghost"}
              aria-pressed={filter === status}
              onClick={() => setFilter(status)}
            >
              {ITEM_STATUS[status].label} <span className="tabular text-text-3">{counts[status]}</span>
            </Button>
          ))}
        </div>
        {items.length ? (
          <ul className="max-h-[32rem] divide-y divide-line overflow-y-auto rounded-lg border border-line">
            {items.map((item, index) => (
              <ItemRow key={item.id} item={item} index={index} />
            ))}
          </ul>
        ) : (
          <EmptyState compact icon={filter === "all" ? Inbox : ListChecks} title="No items" description={filter === "all" ? "This run covered no jobs." : "No item has this status."} />
        )}
      </div>
    </div>
  );
}
