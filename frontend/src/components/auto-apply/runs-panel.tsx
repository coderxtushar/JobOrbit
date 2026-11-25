"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { ChevronDown, Download, FlaskConical, History, Pause, Play, Send, Square } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/shared/empty-state";
import { SectionHeading } from "@/components/shared/page-header";
import { ErrorState, errorMessage } from "@/components/shared/query-state";
import { StateBadge, StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { Schemas } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { ATTEMPT_STATE, RUN_STATUS } from "@/lib/constants/states";
import { formatDateTime, formatNumber, formatRelative, humanize } from "@/lib/formatting";
import { cn } from "@/lib/utils";

import { AttemptDetail, UNCLEAR_STATES } from "./attempt-detail";
import { ConfirmDialog } from "./confirm-dialog";

type Run = Schemas["AutoApplyRunRead"];
type Attempt = Schemas["SubmissionAttemptRead"];

const ACTIVE = new Set(["running", "pending", "cancelling"]);
const RESUMABLE = new Set(["paused", "interrupted", "cancelled"]);

/** Milestones of one attempt, in order (app/submission/states.py CHECKPOINTS). */
const CHECKPOINTS = [
  "queued",
  "capability_checked",
  "prepared",
  "form_inspected",
  "form_filled",
  "submit_requested",
  "submit_clicked",
  "outcome_read",
];
const SUBMIT_FROM = CHECKPOINTS.indexOf("submit_requested");

export function RunsPanel({ stopped }: { stopped: boolean }) {
  const query = useQuery({
    queryKey: ["autoapply", "runs"],
    queryFn: () => api.runs(10),
    // Poll while anything is in flight, so progress shows without a refresh.
    refetchInterval: (state) => (state.state.data?.items.some((run) => ACTIVE.has(run.status)) ? 3000 : false),
  });

  return (
    <section aria-label="Runs">
      <SectionHeading
        title="Runs"
        description="Prepared means ready, not sent. Only “Submitted · confirmed” reached an employer."
        actions={
          query.data?.items.some((run) => ACTIVE.has(run.status)) ? (
            <span className="flex items-center gap-1.5 text-xs text-cyan">
              <span className="size-1.5 animate-pulse-soft rounded-full bg-cyan" /> Live — updating every 3s
            </span>
          ) : null
        }
      />
      {query.isPending ? (
        <div className="space-y-3">
          {Array.from({ length: 2 }).map((_, index) => (
            <Skeleton key={index} className="h-40 w-full rounded-xl" />
          ))}
        </div>
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : query.data.items.length === 0 ? (
        <EmptyState
          icon={History}
          title="No runs yet"
          description="Build a preflight above and start a run. Leave Dry run on for the first one: it fills forms and sends nothing."
        />
      ) : (
        <div className="space-y-3">
          {query.data.items.map((run, index) => (
            <RunCard key={run.id} run={run} defaultOpen={index === 0} stopped={stopped} />
          ))}
          {query.data.total > query.data.items.length ? (
            <p className="text-center text-xs text-text-3">
              Showing the latest {query.data.items.length} of {formatNumber(query.data.total)} runs.
            </p>
          ) : null}
        </div>
      )}
    </section>
  );
}

function RunCard({ run, defaultOpen, stopped }: { run: Run; defaultOpen: boolean; stopped: boolean }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(defaultOpen);
  const [confirmResume, setConfirmResume] = useState(false);
  const active = ACTIVE.has(run.status);

  const act = useMutation({
    mutationFn: (action: "pause" | "resume" | "cancel") =>
      action === "pause" ? api.pauseRun(run.id) : action === "resume" ? api.resumeRun(run.id) : api.cancelRun(run.id),
    onSuccess: (_next, action) => {
      setConfirmResume(false);
      void queryClient.invalidateQueries({ queryKey: ["autoapply", "runs"] });
      void queryClient.invalidateQueries({ queryKey: ["autoapply", "control"] });
      toast.success(
        action === "pause" ? `Pausing run ${run.id}` : action === "resume" ? `Run ${run.id} resumed` : `Stopping run ${run.id}`,
        { description: action === "resume" ? undefined : "It stops at the next safe point, before any Submit." },
      );
    },
    onError: (error) => toast.error("That did not work", { description: errorMessage(error) }),
  });

  const attention = (run.attempts ?? []).filter((attempt) => UNCLEAR_STATES.has(attempt.state)).length;

  return (
    <article
      className={cn(
        "orbit-card overflow-hidden transition-shadow",
        active && "shadow-glow-cyan",
        !run.dry_run && "border-l-2 border-l-danger/60",
      )}
    >
      <div className="flex flex-wrap items-center gap-3 px-4 py-3">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          className="flex min-w-0 flex-1 items-center gap-3 text-left"
        >
          <ChevronDown className={cn("size-4 shrink-0 text-text-3 transition-transform duration-200", !open && "-rotate-90")} />
          <span className="font-heading text-sm font-semibold text-text-1">Run {run.id}</span>
          <StateBadge value={run.status} map={RUN_STATUS} />
          {run.dry_run ? (
            <StatusBadge tone="violet" dot={false}>
              <FlaskConical className="size-3" /> Dry run
            </StatusBadge>
          ) : (
            <StatusBadge tone="danger" dot={false}>
              <Send className="size-3" /> Live
            </StatusBadge>
          )}
          {run.pause_requested && run.status !== "paused" ? <StatusBadge tone="neutral">Pause requested</StatusBadge> : null}
          {attention ? <StatusBadge tone="warning">{attention} need checking</StatusBadge> : null}
          <span className="hidden truncate text-xs text-text-3 md:inline">
            started {formatRelative(run.started_at)}
            {run.finished_at ? ` · finished ${formatDateTime(run.finished_at)}` : ""}
          </span>
        </button>
        <div className="flex items-center gap-1.5">
          {active && run.status !== "cancelling" ? (
            <Button size="sm" variant="outline" disabled={act.isPending} onClick={() => act.mutate("pause")}>
              <Pause /> Pause
            </Button>
          ) : null}
          {RESUMABLE.has(run.status) ? (
            <Button
              size="sm"
              variant="outline"
              disabled={act.isPending || stopped}
              title={stopped ? "Clear the emergency stop first" : undefined}
              onClick={() => (run.dry_run ? act.mutate("resume") : setConfirmResume(true))}
            >
              <Play /> Resume
            </Button>
          ) : null}
          {active ? (
            <Button size="sm" variant="destructive" disabled={act.isPending || run.cancel_requested} onClick={() => act.mutate("cancel")}>
              <Square /> {run.cancel_requested ? "Stopping…" : "Stop"}
            </Button>
          ) : null}
          <Button asChild size="sm" variant="ghost">
            <a href={api.runReportUrl(run.id)} download={`autoapply-run-${run.id}.txt`}>
              <Download /> Report
            </a>
          </Button>
        </div>
      </div>

      <RunCounts run={run} />

      {run.message ? <p className="border-t border-line px-4 py-2.5 text-xs text-text-2">{run.message}</p> : null}

      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
          >
            <Attempts attempts={run.attempts ?? []} />
          </motion.div>
        ) : null}
      </AnimatePresence>

      <ConfirmDialog
        open={confirmResume}
        onOpenChange={setConfirmResume}
        tone="danger"
        icon={<Send className="size-4" />}
        title={`Resume live run ${run.id}?`}
        description="This run is live. Resuming continues submitting real applications to employers for the jobs it was approved for, within its original scope."
        confirmLabel="Resume and submit"
        pending={act.isPending}
        onConfirm={() => act.mutate("resume")}
      />
    </article>
  );
}

/**
 * The run's figures, each with what it actually means. Prepared and confirmed sit in
 * separate tiles with a divider and are never added together.
 */
function RunCounts({ run }: { run: Run }) {
  const tiles: { label: string; value: number; caption: string; tone?: string; strong?: boolean }[] = [
    { label: "Eligible", value: run.eligible_count, caption: "matched your scope" },
    { label: "Prepared", value: run.prepared_count, caption: "ready, not sent", tone: "text-violet" },
    {
      label: "Submitted · confirmed",
      value: run.confirmed_count,
      caption: "employer acknowledged",
      tone: "text-success",
      strong: true,
    },
    {
      label: "Needs an answer",
      value: run.blocked_count,
      caption: "waiting on you",
      tone: run.blocked_count ? "text-warning" : undefined,
    },
    {
      label: "Needs you to act",
      value: run.needs_user_count,
      caption: "captcha, sign-in…",
      tone: run.needs_user_count ? "text-warning" : undefined,
    },
    { label: "Platform permits none", value: run.unsupported_count, caption: "prepared for you to send" },
    {
      label: "Outcome unverified",
      value: run.unknown_count,
      caption: "check before resending",
      tone: run.unknown_count ? "text-warning" : undefined,
    },
    { label: "Failed", value: run.failed_count, caption: "did not submit", tone: run.failed_count ? "text-danger" : undefined },
  ];
  return (
    <dl className="grid grid-cols-2 border-t border-line sm:grid-cols-4 xl:grid-cols-8">
      {tiles.map((tile) => (
        <div
          key={tile.label}
          className={cn(
            "border-b border-r border-line px-3.5 py-2.5 last:border-r-0 xl:border-b-0",
            tile.strong && "bg-success-soft/60",
          )}
        >
          <dt className="truncate text-[10.5px] font-medium uppercase tracking-wider text-text-3">{tile.label}</dt>
          <dd className={cn("mt-0.5 font-heading text-lg font-semibold tabular text-text-1", tile.tone)}>{formatNumber(tile.value)}</dd>
          <dd className="truncate text-[11px] text-text-3">{tile.caption}</dd>
        </div>
      ))}
    </dl>
  );
}

const ATTEMPT_PAGE = 40;

function Attempts({ attempts }: { attempts: Attempt[] }) {
  const [visible, setVisible] = useState(ATTEMPT_PAGE);
  if (!attempts.length) {
    return <p className="border-t border-line px-4 py-4 text-xs text-text-3">No jobs were queued for this run.</p>;
  }
  return (
    <div className="border-t border-line">
      <ul className="divide-y divide-line">
        {attempts.slice(0, visible).map((attempt) => (
          <AttemptRow key={attempt.id} attempt={attempt} />
        ))}
      </ul>
      {attempts.length > visible ? (
        <div className="flex justify-center border-t border-line p-2.5">
          <Button size="sm" variant="ghost" onClick={() => setVisible((value) => value + ATTEMPT_PAGE)}>
            Show more ({attempts.length - visible} left)
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function AttemptRow({ attempt }: { attempt: Attempt }) {
  const [open, setOpen] = useState(false);
  const unclear = UNCLEAR_STATES.has(attempt.state);
  const detailId = `attempt-${attempt.id}`;
  return (
    <li className={cn(unclear && "bg-warning-soft/30")}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={detailId}
        onClick={() => setOpen((value) => !value)}
        className="grid w-full grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1.5 px-4 py-2.5 text-left transition-colors hover:bg-surface-2/50 md:grid-cols-[minmax(0,1.3fr)_9.5rem_minmax(0,1fr)_5rem_1rem]"
      >
        <span className="min-w-0">
          <span className="block truncate text-sm text-text-1">
            Job {attempt.job_id}
            <span className="text-text-3"> · {humanize(attempt.target_key)}</span>
          </span>
          <span className="block truncate text-[11px] text-text-3">
            {attempt.confirmation_id ? `confirmation ${attempt.confirmation_id}` : attempt.detail || "—"}
          </span>
        </span>
        <span className="justify-self-end md:justify-self-start">
          <StateBadge value={attempt.state} map={ATTEMPT_STATE} />
        </span>
        <span className="col-span-2 min-w-0 md:col-span-1">
          <CheckpointTrack checkpoint={attempt.checkpoint} />
          <span className="mt-1 block truncate text-[11px] text-text-3">
            {attempt.checkpoint ? `reached ${humanize(attempt.checkpoint).toLowerCase()}` : "no checkpoint"}
            {attempt.failure_category ? ` · ${humanize(attempt.failure_category).toLowerCase()}` : ""}
          </span>
        </span>
        <span className="hidden text-right text-xs text-text-2 tabular md:block">
          {attempt.duration_ms === null || attempt.duration_ms === undefined ? "—" : `${(attempt.duration_ms / 1000).toFixed(1)}s`}
        </span>
        <ChevronDown className={cn("hidden size-4 text-text-3 transition-transform duration-200 md:block", open && "rotate-180")} />
      </button>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            id={detailId}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
          >
            {attempt.application_id ? (
              <div className="px-4 pb-2 pt-0 text-xs">
                <Link href={`/applications/${attempt.application_id}`} className="text-violet hover:underline">
                  Open application {attempt.application_id}
                </Link>
              </div>
            ) : null}
            <AttemptDetail attemptId={attempt.id} />
          </motion.div>
        ) : null}
      </AnimatePresence>
    </li>
  );
}

/** Eight segments, one per checkpoint; segments past "submit requested" are amber. */
function CheckpointTrack({ checkpoint }: { checkpoint: string }) {
  const reached = CHECKPOINTS.indexOf(checkpoint);
  return (
    <span className="flex gap-0.5" aria-label={checkpoint ? `Checkpoint: ${humanize(checkpoint)}` : "No checkpoint reached"} role="img">
      {CHECKPOINTS.map((name, index) => (
        <span
          key={name}
          title={humanize(name)}
          className={cn(
            "h-1 flex-1 rounded-full",
            index > reached ? "bg-surface-3" : index >= SUBMIT_FROM ? "bg-warning" : "bg-violet",
          )}
        />
      ))}
    </span>
  );
}
