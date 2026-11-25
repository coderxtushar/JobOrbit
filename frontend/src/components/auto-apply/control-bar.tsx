"use client";

import { useMutation, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { motion } from "motion/react";
import { Archive, Globe, OctagonX, RotateCcw, ShieldCheck, ShieldOff, Zap } from "lucide-react";
import { useState, useSyncExternalStore } from "react";
import { toast } from "sonner";

import { ErrorState, errorMessage } from "@/components/shared/query-state";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import type { Schemas } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { formatDateTime, formatNumber, formatRelative } from "@/lib/formatting";
import { cn } from "@/lib/utils";

import { ConfirmDialog } from "./confirm-dialog";

type Control = Schemas["ControlStatusRead"];

/**
 * Safety controls: the emergency stop, open circuit breakers, and the installation's
 * limits. Shown first on the page because it overrides everything below it.
 */
export function ControlBar({ query }: { query: UseQueryResult<Control> }) {
  const queryClient = useQueryClient();
  const [stopOpen, setStopOpen] = useState(false);
  const [reason, setReason] = useState("");

  const apply = (next: Control) => {
    queryClient.setQueryData(["autoapply", "control"], next);
    void queryClient.invalidateQueries({ queryKey: ["autoapply", "runs"] });
  };

  const stop = useMutation({
    mutationFn: () => api.emergencyStop(reason.trim() || "pressed on the Auto-apply page"),
    onSuccess: (next) => {
      apply(next);
      setStopOpen(false);
      setReason("");
      toast.success("Emergency stop is on", { description: "Every run stops before its next Submit." });
    },
    onError: (error) => toast.error("Emergency stop failed", { description: errorMessage(error) }),
  });
  const clear = useMutation({
    mutationFn: api.clearEmergencyStop,
    onSuccess: (next) => {
      apply(next);
      toast.success("Emergency stop cleared", { description: "Runs can start again." });
    },
    onError: (error) => toast.error("Could not clear the stop", { description: errorMessage(error) }),
  });
  const reset = useMutation({
    mutationFn: (target: string) => api.resetCircuit(target),
    onSuccess: (next, target) => {
      apply(next);
      toast.success(`${target} breaker reset`);
    },
    onError: (error) => toast.error("Reset failed", { description: errorMessage(error) }),
  });

  // The topbar's notification bell reads the same query from outside this page's Suspense
  // boundary, so its data can land before this subtree hydrates. Render the server's
  // skeleton for the hydration pass either way, then the real state.
  const hydrated = useSyncExternalStore(subscribeNothing, () => true, () => false);

  if (!hydrated || query.isPending) return <Skeleton className="h-[92px] w-full rounded-xl" />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;

  const control = query.data;
  const stopped = control.emergency_stop;
  const openBreakers = (control.breakers ?? []).filter((breaker) => breaker.open);
  const cap = control.daily_cap ?? null;
  const used = cap ? Math.min(100, (control.dispatched_today / cap) * 100) : 0;

  return (
    <section aria-label="Safety controls" className="space-y-2">
      <motion.div
        layout
        className={cn(
          "orbit-card relative overflow-hidden",
          stopped && "border-danger/40 bg-danger-soft shadow-[0_0_0_1px_var(--danger-soft),0_12px_40px_-16px_var(--danger)]",
        )}
      >
        <div className="flex flex-col gap-4 p-4 lg:flex-row lg:items-center">
          <div className="flex min-w-0 flex-1 items-start gap-3">
            <span
              className={cn(
                "relative grid size-10 shrink-0 place-items-center rounded-xl ring-1 ring-inset",
                stopped ? "bg-danger-soft text-danger ring-danger/30" : "bg-success-soft text-success ring-success/25",
              )}
            >
              {stopped ? <ShieldOff className="size-5" /> : <ShieldCheck className="size-5" />}
              {stopped ? (
                <span className="absolute -right-0.5 -top-0.5 size-2.5 animate-pulse-soft rounded-full bg-danger" />
              ) : null}
            </span>
            <div className="min-w-0">
              <p className="font-heading text-sm font-semibold text-text-1">
                {stopped ? "Emergency stop is on" : "Emergency stop is off"}
              </p>
              <p className="mt-0.5 text-xs leading-relaxed text-text-2">
                {stopped ? (
                  <>
                    No run will start or continue until you clear it.
                    {control.emergency_stop_reason ? <> Reason: “{control.emergency_stop_reason}”.</> : null}
                    {control.emergency_stop_at ? (
                      <span className="text-text-3"> Engaged {formatDateTime(control.emergency_stop_at)}.</span>
                    ) : null}
                  </>
                ) : (
                  "Runs may start. Pressing Stop halts every active run before its next Submit."
                )}
              </p>
            </div>
          </div>

          <dl className="grid grid-cols-3 gap-2 text-xs lg:w-[30rem] lg:shrink-0">
            <Stat icon={Globe} label="Browser submission">
              <StatusBadge tone={control.browser_submission_enabled ? "cyan" : "neutral"}>
                {control.browser_submission_enabled ? "On" : "Off"}
              </StatusBadge>
            </Stat>
            <Stat
              icon={Zap}
              label="Dispatched today"
              title="Submissions started today on browser platforms, including ones whose outcome is not yet confirmed."
            >
              <span className="tabular font-heading text-sm font-semibold text-text-1">
                {formatNumber(control.dispatched_today)}
                <span className="font-normal text-text-3"> / {cap ? formatNumber(cap) : "no cap"}</span>
              </span>
              {cap ? (
                <span className="mt-1 block h-1 overflow-hidden rounded-full bg-surface-3">
                  <span
                    className={cn("block h-full rounded-full", used >= 100 ? "bg-warning" : "bg-cyan")}
                    style={{ width: `${used}%` }}
                  />
                </span>
              ) : null}
            </Stat>
            <Stat icon={Archive} label="Evidence kept">
              <span className="tabular font-heading text-sm font-semibold text-text-1">
                {control.evidence_retention_days}
                <span className="font-normal text-text-3"> days</span>
              </span>
            </Stat>
          </dl>

          <div className="flex shrink-0 items-center gap-2">
            {stopped ? (
              <Button variant="outline" onClick={() => clear.mutate()} disabled={clear.isPending}>
                <RotateCcw /> Clear stop
              </Button>
            ) : (
              <Button
                onClick={() => setStopOpen(true)}
                className="bg-danger text-white hover:bg-danger/90 dark:bg-danger dark:text-white"
              >
                <OctagonX /> Emergency stop
              </Button>
            )}
          </div>
        </div>
      </motion.div>

      {openBreakers.map((breaker) => (
        <div
          key={breaker.target}
          role="status"
          className="flex flex-col gap-2 rounded-xl border border-warning/30 bg-warning-soft px-4 py-3 sm:flex-row sm:items-center"
        >
          <p className="min-w-0 flex-1 text-xs leading-relaxed text-text-1">
            <span className="font-semibold capitalize">{breaker.target}</span> is paused after{" "}
            {breaker.consecutive_failures} consecutive failure(s)
            {breaker.reason ? <>: {breaker.reason}</> : null}
            {breaker.opened_at ? <span className="text-text-3"> · opened {formatRelative(breaker.opened_at)}</span> : null}
          </p>
          <Button
            size="sm"
            variant="outline"
            disabled={reset.isPending && reset.variables === breaker.target}
            onClick={() => reset.mutate(breaker.target)}
          >
            <RotateCcw /> Reset breaker
          </Button>
        </div>
      ))}

      <ConfirmDialog
        open={stopOpen}
        onOpenChange={setStopOpen}
        tone="danger"
        icon={<OctagonX className="size-4" />}
        title="Stop every run now?"
        description="Every active run stops before its next Submit. A run already past Submit records an unknown outcome rather than a guess. New runs are refused until you clear the stop."
        confirmLabel="Engage emergency stop"
        pending={stop.isPending}
        onConfirm={() => stop.mutate()}
      >
        <div className="space-y-1.5">
          <Label htmlFor="stop-reason" className="text-xs text-text-2">
            Reason (optional)
          </Label>
          <Textarea
            id="stop-reason"
            value={reason}
            maxLength={300}
            onChange={(event) => setReason(event.target.value)}
            placeholder="e.g. a form looked wrong"
            className="min-h-14"
          />
        </div>
      </ConfirmDialog>
    </section>
  );
}

const subscribeNothing = () => () => {};

function Stat({
  icon: Icon,
  label,
  children,
  title,
}: {
  icon: typeof Globe;
  label: string;
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <div className="rounded-lg border border-line bg-surface-2/40 px-2.5 py-2" title={title}>
      <dt className="flex items-center gap-1 text-[10.5px] font-medium uppercase tracking-wider text-text-3">
        <Icon className="size-3" /> {label}
      </dt>
      <dd className="mt-1">{children}</dd>
    </div>
  );
}
