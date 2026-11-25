"use client";

import { useMutation, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { Loader2, ShieldAlert, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { SectionHeading } from "@/components/shared/page-header";
import { ErrorState, errorMessage } from "@/components/shared/query-state";
import { StatusBadge } from "@/components/shared/status-badge";
import { Surface } from "@/components/shared/surface";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import type { Schemas } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { formatNumber, humanize } from "@/lib/formatting";

/**
 * Auto-apply safety settings, read-only: the API has no endpoint to change them, they come
 * from .env. The one action here is the evidence cleanup the API does expose.
 */
export function SafetySettings({ control }: { control: UseQueryResult<Schemas["ControlStatusRead"]> }) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const data = control.data;

  const cleanup = useMutation({
    mutationFn: api.cleanupEvidence,
    onSuccess: (report) => {
      setConfirming(false);
      const total = Object.values(report).reduce((sum, value) => sum + value, 0);
      toast.success(total ? "Old evidence deleted" : "Nothing was old enough to delete", {
        description: Object.entries(report)
          .map(([key, value]) => `${humanize(key)}: ${formatNumber(value)}`)
          .join(" · "),
      });
      void queryClient.invalidateQueries({ queryKey: ["autoapply"] });
    },
    onError: (error) => toast.error("Evidence was not deleted", { description: errorMessage(error) }),
  });

  return (
    <Surface className="p-5">
      <SectionHeading
        title="Auto-apply safety"
        description="Read-only here. These limits come from .env; the emergency stop and circuit breakers are on the Auto-apply page."
        actions={
          <Button asChild variant="ghost" size="sm">
            <Link href="/auto-apply">Auto-apply</Link>
          </Button>
        }
      />
      {control.isError ? (
        <ErrorState error={control.error} onRetry={() => control.refetch()} />
      ) : control.isLoading || !data ? (
        <div className="grid gap-3 sm:grid-cols-3">
          {Array.from({ length: 3 }, (_, index) => (
            <Skeleton key={index} className="h-24 rounded-lg" />
          ))}
        </div>
      ) : (
        <>
          {data.emergency_stop ? (
            <p className="mb-3 flex items-start gap-2 rounded-lg border border-danger/25 bg-danger-soft p-3 text-xs text-text-1">
              <ShieldAlert className="mt-0.5 size-4 shrink-0 text-danger" />
              The emergency stop is on{data.emergency_stop_reason ? `: ${data.emergency_stop_reason}` : ""}. Nothing will be
              submitted until it is cleared on the Auto-apply page.
            </p>
          ) : null}
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-line bg-surface-2/40 p-3">
              <p className="text-[11.5px] text-text-3">Browser submission</p>
              <div className="mt-1.5">
                <StatusBadge tone={data.browser_submission_enabled ? "violet" : "neutral"}>
                  {data.browser_submission_enabled ? "On" : "Off"}
                </StatusBadge>
              </div>
              <p className="mt-1.5 text-[11px] leading-snug text-text-3">
                {data.browser_submission_enabled
                  ? "Live runs may press Submit on supported hosted forms."
                  : "Runs prepare and preview only; nothing is submitted."}
              </p>
              <code className="mt-1 block font-mono text-[10.5px] text-text-3">JA_BROWSER_SUBMISSION_ENABLED</code>
            </div>
            <div className="rounded-lg border border-line bg-surface-2/40 p-3">
              <p className="text-[11.5px] text-text-3">Daily submission cap</p>
              <p className="mt-1 font-heading text-xl font-semibold text-text-1 tabular">
                {data.daily_cap === null || data.daily_cap === undefined ? (
                  <span className="text-text-3">—</span>
                ) : (
                  <>
                    {formatNumber(data.dispatched_today)}
                    <span className="text-sm text-text-3"> / {formatNumber(data.daily_cap)} today</span>
                  </>
                )}
              </p>
              <p className="mt-1 text-[11px] leading-snug text-text-3">
                {data.daily_cap === null || data.daily_cap === undefined
                  ? "No cap applies while browser submission is off."
                  : "Submissions stop for the day at the cap."}
              </p>
              <code className="mt-1 block font-mono text-[10.5px] text-text-3">JA_BROWSER_DAILY_SUBMISSION_CAP</code>
            </div>
            <div className="rounded-lg border border-line bg-surface-2/40 p-3">
              <p className="text-[11.5px] text-text-3">Evidence retention</p>
              <p className="mt-1 font-heading text-xl font-semibold text-text-1 tabular">
                {formatNumber(data.evidence_retention_days)}
                <span className="text-sm text-text-3"> days</span>
              </p>
              <p className="mt-1 text-[11px] leading-snug text-text-3">
                Screenshots may show your answers; they are owner-only and deleted after this.
              </p>
              <code className="mt-1 block font-mono text-[10.5px] text-text-3">JA_EVIDENCE_RETENTION_DAYS</code>
            </div>
          </div>
          <div className="mt-4 flex flex-col gap-3 rounded-lg border border-line p-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-medium text-text-1">Delete old evidence now</p>
              <p className="text-xs text-text-3">
                Removes screenshots, staged resume copies and event logs older than {data.evidence_retention_days} days.
                Attempt outcomes are kept.
              </p>
            </div>
            <Button variant="destructive" size="sm" onClick={() => setConfirming(true)} className="shrink-0">
              <Trash2 /> Delete old evidence
            </Button>
          </div>
        </>
      )}

      <Dialog open={confirming} onOpenChange={(open) => (cleanup.isPending ? null : setConfirming(open))}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete evidence older than {data?.evidence_retention_days ?? 30} days?</DialogTitle>
            <DialogDescription>
              Screenshots, staged uploads and submission event logs past the retention period are deleted permanently.
              The record of each attempt and its outcome stays. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline" disabled={cleanup.isPending}>
                Cancel
              </Button>
            </DialogClose>
            <Button variant="destructive" onClick={() => cleanup.mutate()} disabled={cleanup.isPending}>
              {cleanup.isPending ? <Loader2 className="animate-spin" /> : <Trash2 />}
              Delete old evidence
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Surface>
  );
}
