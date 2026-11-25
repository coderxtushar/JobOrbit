"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "motion/react";
import { AlertTriangle, CheckCircle2, Circle, FlaskConical, Loader2, Rocket, Send } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";

import { PageHeader } from "@/components/shared/page-header";
import { errorMessage } from "@/components/shared/query-state";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import type { Schemas } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { formatNumber } from "@/lib/formatting";
import { cn } from "@/lib/utils";

import { CapabilitiesPanel } from "./capabilities-panel";
import { ConfirmDialog } from "./confirm-dialog";
import { ControlBar } from "./control-bar";
import { PreflightPanel } from "./preflight-panel";
import { RunsPanel } from "./runs-panel";
import { ScopeForm, StepDot } from "./scope-form";
import {
  fromPreferences,
  parseJobIds,
  scopeKey,
  scopeSchema,
  toTargets,
  type ScopeValues,
  type TargetsIn,
} from "./scope";

type Preflight = Schemas["PreflightRead"];

export function AutoApplyView() {
  const searchParams = useSearchParams();
  const jobsParam = searchParams.get("jobs");
  const urlJobIds = useMemo(() => parseJobIds(jobsParam), [jobsParam]);

  const control = useQuery({ queryKey: ["autoapply", "control"], queryFn: api.control, refetchInterval: 15_000 });
  const prefs = useQuery({ queryKey: ["autoapply", "preferences"], queryFn: api.autoapplyPreferences, staleTime: Infinity });
  const capabilities = useQuery({ queryKey: ["autoapply", "capabilities"], queryFn: api.capabilities, staleTime: 5 * 60_000 });
  const stopped = control.data?.emergency_stop ?? false;

  const platformOptions = useMemo(() => {
    const keys = new Map<string, string>();
    for (const platform of capabilities.data?.platforms ?? []) {
      if (platform.key !== "unknown") keys.set(platform.key, platform.display_name);
    }
    for (const key of prefs.data?.platforms ?? []) if (!keys.has(key)) keys.set(key, key);
    return Array.from(keys, ([value, label]) => ({ value, label }));
  }, [capabilities.data, prefs.data]);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Automation"
        title="Auto-apply"
        description="Set the scope, inspect the itemised preflight, tick the jobs you approve, then run. Dry run is on by default and sends nothing."
      />
      <ControlBar query={control} />
      <CapabilitiesPanel />
      {prefs.isPending ? (
        <div className="space-y-3">
          <Skeleton className="h-[540px] w-full rounded-xl" />
        </div>
      ) : (
        <>
          {prefs.isError ? (
            <p role="alert" className="flex items-center gap-2 rounded-lg border border-warning/25 bg-warning-soft px-3 py-2 text-xs text-text-1">
              <AlertTriangle className="size-3.5 text-warning" />
              Your saved scope could not be loaded ({errorMessage(prefs.error)}), so the defaults are shown.
            </p>
          ) : null}
          <Workspace
            key={urlJobIds.join(",")}
            saved={prefs.data}
            urlJobIds={urlJobIds}
            stopped={stopped}
            controlKnown={control.isSuccess}
            platformOptions={platformOptions}
          />
        </>
      )}
      <RunsPanel stopped={stopped} />
    </div>
  );
}

interface PlanState {
  key: string;
  targets: TargetsIn;
  data: Preflight;
}

function Workspace({
  saved,
  urlJobIds,
  stopped,
  controlKnown,
  platformOptions,
}: {
  saved: TargetsIn | undefined;
  urlJobIds: number[];
  stopped: boolean;
  controlKnown: boolean;
  platformOptions: { value: string; label: string }[];
}) {
  const queryClient = useQueryClient();
  const form = useForm<ScopeValues>({
    resolver: zodResolver(scopeSchema),
    defaultValues: fromPreferences(saved),
    mode: "onChange",
  });
  const values = useWatch({ control: form.control }) as ScopeValues;
  const currentKey = scopeKey(toTargets(values, saved, urlJobIds));

  const [plan, setPlan] = useState<PlanState | null>(null);
  const [excluded, setExcluded] = useState<Set<number>>(() => new Set());
  const [confirmLive, setConfirmLive] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);

  const preflight = useMutation({
    mutationFn: (targets: TargetsIn) => api.preflight(targets),
    onSuccess: (data, targets) => {
      setPlan({ key: scopeKey(targets), targets, data });
      setExcluded(new Set());
    },
    onError: (error) => toast.error("Preflight failed", { description: errorMessage(error) }),
  });

  const planState: "none" | "current" | "stale" = !plan ? "none" : plan.key === currentKey ? "current" : "stale";
  const planCurrent = planState === "current" && plan !== null;
  const dryRun = values.dry_run;
  const approvedIds = plan ? plan.data.queue_job_ids.filter((id) => !excluded.has(id)) : [];
  const shownIds = new Set(plan?.data.jobs.map((job) => job.job_id) ?? []);
  const tickedPlanned = plan ? plan.data.jobs.filter((job) => job.planned && !excluded.has(job.job_id)).length : 0;
  const hiddenQueued = plan ? plan.data.queue_job_ids.filter((id) => !shownIds.has(id)).length : 0;
  const capRemaining = plan?.data.counts.daily_cap_remaining ?? null;
  const willSubmitAtMost = capRemaining === null ? tickedPlanned : Math.min(tickedPlanned, capRemaining);

  const start = useMutation({
    mutationFn: ({ targets, background }: { targets: TargetsIn; background: boolean }) => api.startRun(targets, background),
    onMutate: ({ background }) => {
      // A dry run runs inside the request; let the runs list pick it up while it works.
      if (!background) setTimeout(() => void queryClient.invalidateQueries({ queryKey: ["autoapply", "runs"] }), 1500);
    },
    onSuccess: (run, { targets, background }) => {
      setConfirmLive(false);
      setAcknowledged(false);
      setPlan(null);
      setExcluded(new Set());
      void queryClient.invalidateQueries({ queryKey: ["autoapply"] });
      void queryClient.invalidateQueries({ queryKey: ["applications"] });
      void queryClient.invalidateQueries({ queryKey: ["nav"] });
      if (background) {
        toast.success(`Live run ${run.id} started`, {
          description: `It works through ${targets.approved_job_ids?.length ?? 0} approved job(s) one at a time. Follow it under Runs.`,
        });
      } else {
        toast.success(`Dry run ${run.id} finished`, { description: run.message || "Nothing was sent." });
      }
    },
    onError: (error) => toast.error("The run did not start", { description: errorMessage(error) }),
  });

  // What stands between the user and the Start button, in plain words.
  const blockers: string[] = [];
  if (stopped) blockers.push("The emergency stop is on. Clear it to start a run.");
  if (!dryRun) {
    if (!controlKnown) blockers.push("The safety controls have not loaded yet.");
    if (!plan) blockers.push("A live run needs a preflight. Build one first.");
    else if (!planCurrent) blockers.push("The scope changed since the preflight. Rebuild it.");
  }
  if (planCurrent && approvedIds.length === 0) blockers.push("No job is ticked in the preflight.");
  const canStart = blockers.length === 0 && !start.isPending;

  const startNow = () => {
    if (planCurrent && plan) {
      const targets = { ...plan.targets, approved_job_ids: approvedIds };
      if (dryRun) start.mutate({ targets, background: false });
      else {
        setAcknowledged(false);
        setConfirmLive(true);
      }
      return;
    }
    if (!dryRun) return;
    void form.handleSubmit((valid) => start.mutate({ targets: toTargets(valid, saved, urlJobIds), background: false }))();
  };

  const checks = dryRun
    ? [
        { ok: !stopped, label: "Emergency stop is off" },
        { ok: true, label: "Dry run: nothing will be sent" },
        {
          ok: planCurrent ? approvedIds.length > 0 : true,
          label: planCurrent
            ? `${approvedIds.length} ticked job(s) from the preflight`
            : urlJobIds.length
              ? `${urlJobIds.length} job(s) from Job discovery, checked against the scope`
              : "Everything in scope (no current preflight)",
        },
      ]
    : [
        { ok: controlKnown && !stopped, label: "Emergency stop is off" },
        { ok: planCurrent, label: "Preflight is current for this scope" },
        { ok: planCurrent && approvedIds.length > 0, label: `${planCurrent ? approvedIds.length : 0} job(s) ticked` },
      ];

  return (
    <div className="space-y-6">
      <ScopeForm
        form={form}
        platformOptions={platformOptions}
        onBuild={() => void form.handleSubmit((valid) => preflight.mutate(toTargets(valid, saved, urlJobIds)))()}
        building={preflight.isPending}
        urlJobIds={urlJobIds}
        planState={planState}
      />

      {preflight.isPending && !plan ? <Skeleton className="h-72 w-full rounded-xl" /> : null}
      {plan ? (
        <PreflightPanel plan={plan.data} current={planCurrent} excluded={excluded} onExcludedChange={setExcluded} />
      ) : null}

      {/* Launch */}
      <motion.section
        layout
        aria-label="Start run"
        className={cn(
          "orbit-card overflow-hidden",
          !dryRun && "border-danger/35 shadow-[0_0_0_1px_var(--danger-soft),0_16px_48px_-20px_var(--danger)]",
        )}
      >
        <div className="flex flex-col gap-4 p-5 lg:flex-row lg:items-center">
          <div className="flex min-w-0 flex-1 items-start gap-3">
            <StepDot n={3} />
            <div className="min-w-0 space-y-2">
              <div>
                <h2 className="flex items-center gap-2 font-heading text-[15px] font-semibold text-text-1">
                  {dryRun ? <FlaskConical className="size-4 text-violet" /> : <Send className="size-4 text-danger" />}
                  {dryRun ? "Start a dry run" : "Start a live run"}
                </h2>
                <p className="text-xs text-text-2">
                  {dryRun
                    ? "Fills each form and takes a screenshot, then stops before Submit. Runs while you wait."
                    : "Submits real applications to employers for the ticked jobs on platforms that permit it. Runs in the background."}
                </p>
              </div>
              <ul className="flex flex-wrap gap-x-4 gap-y-1">
                {checks.map((check) => (
                  <li key={check.label} className={cn("flex items-center gap-1.5 text-xs", check.ok ? "text-text-2" : "text-warning")}>
                    {check.ok ? <CheckCircle2 className="size-3.5 text-success" /> : <Circle className="size-3.5" />}
                    {check.label}
                  </li>
                ))}
              </ul>
              {blockers.length ? (
                <p role="status" className="text-xs text-warning">
                  {blockers[0]}
                </p>
              ) : null}
              {start.isError ? (
                <p role="alert" className="text-xs text-danger">
                  {errorMessage(start.error)}
                </p>
              ) : null}
            </div>
          </div>
          <Button
            size="lg"
            disabled={!canStart}
            onClick={startNow}
            className={cn(
              "min-w-44",
              dryRun ? "shadow-glow" : "bg-danger text-white hover:bg-danger/90 dark:bg-danger dark:text-white",
            )}
          >
            {start.isPending ? <Loader2 className="animate-spin" /> : dryRun ? <Rocket /> : <Send />}
            {start.isPending ? (dryRun ? "Dry run in progress…" : "Starting…") : dryRun ? "Start dry run" : "Start live run"}
          </Button>
        </div>
      </motion.section>

      <ConfirmDialog
        open={confirmLive}
        onOpenChange={setConfirmLive}
        tone="danger"
        icon={<Send className="size-4" />}
        title="Submit real applications to employers?"
        description="This is a live run. JobOrbit will fill and submit application forms to real employers on your behalf. A submitted application cannot be withdrawn from here."
        confirmLabel="Start live run"
        pending={start.isPending}
        confirmDisabled={!acknowledged}
        onConfirm={() => {
          if (!plan || !planCurrent) return;
          start.mutate({ targets: { ...plan.targets, approved_job_ids: approvedIds }, background: true });
        }}
      >
        <dl className="grid grid-cols-2 gap-2 text-xs">
          <SummaryItem label="Jobs ticked" value={formatNumber(approvedIds.length)} />
          <SummaryItem
            label="Can be submitted"
            value={hiddenQueued ? `${formatNumber(tickedPlanned)}+` : formatNumber(tickedPlanned)}
            hint="permitted platform, all answers on file"
          />
          <SummaryItem
            label="At most today"
            value={hiddenQueued ? "—" : formatNumber(willSubmitAtMost)}
            hint={capRemaining === null ? "no daily cap set" : `daily cap leaves ${formatNumber(capRemaining)}`}
          />
          <SummaryItem label="Cover letter" value={values.include_cover_letter ? "Included" : "None"} />
        </dl>
        {tickedPlanned === 0 && !hiddenQueued ? (
          <p className="rounded-lg bg-warning-soft px-3 py-2 text-xs text-text-1">
            None of the ticked jobs is on a platform that permits submission with every answer on file, so this run
            will prepare applications and send nothing.
          </p>
        ) : null}
        <label className="flex cursor-pointer items-start gap-2.5 text-xs text-text-1">
          <Checkbox checked={acknowledged} onCheckedChange={(next) => setAcknowledged(next === true)} className="mt-0.5" />
          I reviewed the preflight and want these applications submitted to employers.
        </label>
      </ConfirmDialog>
    </div>
  );
}

function SummaryItem({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface-2/50 px-3 py-2">
      <dt className="text-[10.5px] font-medium uppercase tracking-wider text-text-3">{label}</dt>
      <dd className="font-heading text-base font-semibold text-text-1 tabular">{value}</dd>
      {hint ? <dd className="text-[11px] text-text-3">{hint}</dd> : null}
    </div>
  );
}
