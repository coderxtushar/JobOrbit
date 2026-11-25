"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Bookmark,
  Bot,
  CircleDot,
  Download,
  FilePen,
  GitCommitHorizontal,
  Mail,
  MessageSquareText,
  Send,
  SkipForward,
  type LucideIcon,
} from "lucide-react";

import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/query-state";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/endpoints";
import type { LooseRecord } from "@/lib/api/types";
import { formatRelative, humanize } from "@/lib/formatting";

/** Turn one audit-log row into a readable line. Unknown actions fall back to their name. */
function describe(row: LooseRecord): { icon: LucideIcon; text: string } {
  const action = String(row.action ?? "");
  const detail = (row.detail ?? {}) as Record<string, unknown>;
  const str = (key: string) => (detail[key] === undefined || detail[key] === null ? "" : String(detail[key]));
  switch (action) {
    case "jobs.import":
      return {
        icon: Download,
        text: `Imported ${str("created") || 0} new job(s) from ${humanize(str("source"))}`,
      };
    case "job.shortlisted":
      return { icon: Bookmark, text: `Saved “${str("title")}”` };
    case "job.skipped":
      return { icon: SkipForward, text: `Skipped “${str("title") || `job ${row.entity_id}`}”` };
    case "jobs.captured":
      return { icon: Download, text: "Captured a job from the browser extension" };
    case "application.prepared":
      return { icon: FilePen, text: `Prepared application ${row.entity_id} (${str("questions")} questions)` };
    case "application.status_changed":
      return {
        icon: GitCommitHorizontal,
        text: `Application ${row.entity_id}: ${humanize(str("from"))} → ${humanize(str("to"))}`,
      };
    case "autoapply_run_created":
      return {
        icon: Bot,
        text: `Auto-apply run ${row.entity_id} started (${detail.dry_run ? "dry run" : "live"})`,
      };
    case "answer.saved":
    case "answer_bank.saved":
      return { icon: MessageSquareText, text: "Saved an answer to the answer bank" };
    default:
      if (action.startsWith("email")) return { icon: Mail, text: humanize(action) };
      if (action.includes("submit")) return { icon: Send, text: humanize(action) };
      return { icon: CircleDot, text: humanize(action.replace(/\./g, " ")) };
  }
}

export function RecentActivity() {
  const logs = useQuery({ queryKey: ["logs", "recent"], queryFn: () => api.auditLogs({ limit: 10 }) });

  return (
    <div className="orbit-card p-5">
      <div className="mb-3">
        <h2 className="font-heading text-[15px] font-semibold text-text-1">Recent activity</h2>
        <p className="text-xs text-text-3">From the audit trail.</p>
      </div>
      {logs.isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, index) => (
            <Skeleton key={index} className="h-8 w-full" />
          ))}
        </div>
      ) : logs.isError ? (
        <ErrorState error={logs.error} onRetry={() => logs.refetch()} />
      ) : !logs.data?.items.length ? (
        <EmptyState compact title="No activity yet" description="Imports, preparations and submissions appear here." />
      ) : (
        <ol className="relative space-y-3 before:absolute before:bottom-2 before:left-[13px] before:top-2 before:w-px before:bg-line">
          {logs.data.items.map((row) => {
            const { icon: Icon, text } = describe(row);
            return (
              <li key={String(row.id)} className="relative flex gap-3">
                <span className="relative z-10 grid size-7 shrink-0 place-items-center rounded-full bg-surface-2 ring-1 ring-line-strong">
                  <Icon className="size-3.5 text-text-2" />
                </span>
                <div className="min-w-0 pt-0.5">
                  <p className="truncate text-[13px] text-text-1">{text}</p>
                  <p className="text-[11px] text-text-3">
                    {formatRelative(String(row.created_at ?? ""))} · {String(row.actor ?? "")}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
