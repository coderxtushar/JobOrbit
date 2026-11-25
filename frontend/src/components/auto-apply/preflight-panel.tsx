"use client";

import { AnimatePresence, motion } from "motion/react";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  Copy,
  ExternalLink,
  FileText,
  History,
  Info,
  Lock,
  MessageSquareWarning,
  Radar,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { EmptyState } from "@/components/shared/empty-state";
import { ScoreRing } from "@/components/shared/score-ring";
import { StateBadge, StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Schemas } from "@/lib/api/client";
import { PLAN_STATUS } from "@/lib/constants/states";
import { formatDateTime, formatNumber, formatRelative, humanize } from "@/lib/formatting";
import { cn } from "@/lib/utils";

import { StepDot } from "./scope-form";

type Preflight = Schemas["PreflightRead"];
type Counts = Schemas["PreflightCountsRead"];
type JobPlan = Schemas["JobPlanRead"];

const PAGE = 40;

export function PreflightPanel({
  plan,
  current,
  excluded,
  onExcludedChange,
}: {
  plan: Preflight;
  current: boolean;
  excluded: Set<number>;
  onExcludedChange: (next: Set<number>) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const [visible, setVisible] = useState(PAGE);
  const queued = plan.queue_job_ids;
  const ticked = queued.filter((id) => !excluded.has(id)).length;
  const jobs = useMemo(() => (showAll ? plan.jobs : plan.jobs.filter((job) => job.queued)), [plan.jobs, showAll]);

  return (
    <section
      aria-label="Preflight"
      className={cn("orbit-card overflow-hidden transition-opacity duration-300", !current && "opacity-70")}
    >
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3.5">
        <StepDot n={2} />
        <div className="min-w-0 flex-1">
          <h2 className="font-heading text-[15px] font-semibold text-text-1">Preflight</h2>
          <p className="text-xs text-text-3">
            Itemised plan built {formatRelative(plan.generated_at)} ({formatDateTime(plan.generated_at)}). Nothing was sent.
          </p>
        </div>
        {!current ? <StatusBadge tone="warning">Out of date</StatusBadge> : <StatusBadge tone="success">Current</StatusBadge>}
      </div>

      <div className="space-y-5 p-5">
        <Funnel counts={plan.counts} />

        {plan.notes?.length ? (
          <ul className="space-y-1.5">
            {plan.notes.map((note) => (
              <li key={note} className="flex items-start gap-2 rounded-lg bg-surface-2/60 px-3 py-2 text-xs text-text-2">
                <Info className="mt-0.5 size-3.5 shrink-0 text-cyan" />
                <span className="first-letter:uppercase">{note}</span>
              </li>
            ))}
          </ul>
        ) : null}

        <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-text-1">Jobs in this plan</h3>
            <p className="text-xs text-text-3">
              <span className="tabular font-medium text-text-1">{ticked}</span> of {queued.length} queued job(s) ticked.
              Only ticked jobs are included when you start the run.
            </p>
          </div>
          {queued.length ? (
            <div className="flex gap-1.5">
              <Button size="sm" variant="ghost" onClick={() => onExcludedChange(new Set())}>
                Tick all
              </Button>
              <Button size="sm" variant="ghost" onClick={() => onExcludedChange(new Set(queued))}>
                Untick all
              </Button>
            </div>
          ) : null}
          <label className="flex cursor-pointer items-center gap-2 text-xs text-text-2">
            <Switch
              size="sm"
              checked={showAll}
              onCheckedChange={(next) => {
                setShowAll(next);
                setVisible(PAGE);
              }}
            />
            Show jobs not in this run
          </label>
        </div>

        {jobs.length === 0 ? (
          <EmptyState
            compact
            icon={Radar}
            title={showAll ? "No jobs in the plan" : "No job qualifies for this run"}
            description={
              showAll
                ? "The scope matched nothing at all."
                : "Turn on “Show jobs not in this run” to see which constraint removed each one, then loosen the scope."
            }
          />
        ) : (
          <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line">
            {jobs.slice(0, visible).map((job) => (
              <PlanRow
                key={job.job_id}
                job={job}
                ticked={job.queued && !excluded.has(job.job_id)}
                onTick={(on) => {
                  const next = new Set(excluded);
                  if (on) next.delete(job.job_id);
                  else next.add(job.job_id);
                  onExcludedChange(next);
                }}
              />
            ))}
          </ul>
        )}
        {jobs.length > visible ? (
          <div className="flex justify-center">
            <Button variant="outline" size="sm" onClick={() => setVisible((value) => value + PAGE)}>
              Show {Math.min(PAGE, jobs.length - visible)} more of {jobs.length - visible}
            </Button>
          </div>
        ) : null}
      </div>
    </section>
  );
}

// -------------------------------------------------------------------------------------
// Funnel
// -------------------------------------------------------------------------------------

function Funnel({ counts }: { counts: Counts }) {
  const stages = [
    { key: "discovered", label: "Discovered", value: counts.total_discovered, hint: `${formatNumber(counts.new_jobs)} new`, color: "var(--text-3)" },
    { key: "queued", label: "In this run", value: counts.queued, hint: "passed every constraint", color: "var(--indigo)" },
    { key: "ready", label: "Ready", value: counts.ready, hint: "all answers on file", color: "var(--violet)" },
    {
      key: "planned",
      label: "Planned submissions",
      value: counts.planned_attempts,
      hint: "after platform, limits and cap",
      color: "var(--cyan)",
    },
  ];
  const max = Math.max(1, ...stages.map((stage) => stage.value));
  const width = (value: number) => (value <= 0 ? 0 : Math.max(2.5, (Math.log10(value + 1) / Math.log10(max + 1)) * 100));

  const held = [
    { label: "Need answers", value: counts.missing_answers, icon: MessageSquareWarning, tone: "text-warning" },
    { label: "Duplicates", value: counts.duplicates, icon: Copy, tone: "text-text-3" },
    { label: "Already applied", value: counts.previously_applied, icon: History, tone: "text-text-3" },
    { label: "Expired or stale", value: counts.expired_or_stale, icon: History, tone: "text-text-3" },
    { label: "Blocked: eligibility", value: counts.blocked_by_eligibility, icon: Ban, tone: "text-danger" },
    { label: "Blocked: constraints", value: counts.blocked_by_constraints, icon: Ban, tone: "text-danger" },
    { label: "Platform permits none", value: counts.unsupported_platform, icon: Lock, tone: "text-text-3" },
  ];

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
      <div>
        <ol className="space-y-2">
          {stages.map((stage, index) => (
            <li key={stage.key} className="grid grid-cols-[8.5rem_1fr_4.5rem] items-center gap-3">
              <span className="truncate text-xs font-medium text-text-2">{stage.label}</span>
              <div className="relative h-7 overflow-hidden rounded-md bg-surface-2">
                <motion.div
                  className="h-full rounded-md"
                  style={{ background: `linear-gradient(90deg, color-mix(in oklch, ${stage.color} 30%, transparent), ${stage.color})` }}
                  initial={{ width: 0 }}
                  animate={{ width: `${width(stage.value)}%` }}
                  transition={{ duration: 0.7, delay: index * 0.07, ease: [0.22, 1, 0.36, 1] }}
                />
                <span className="absolute inset-y-0 left-2.5 flex items-center text-[11px] text-text-1/85">{stage.hint}</span>
              </div>
              <span className="text-right font-heading text-sm font-semibold text-text-1 tabular">{formatNumber(stage.value)}</span>
            </li>
          ))}
        </ol>
        <p className="mt-2.5 text-[11px] leading-relaxed text-text-3">
          Bars use a log scale. Scored {formatNumber(counts.scored)} · meeting score {formatNumber(counts.meeting_score)} ·
          confidence {formatNumber(counts.meeting_confidence)} · experience fit {formatNumber(counts.meeting_experience)} ·
          location fit {formatNumber(counts.meeting_location)}.
        </p>
      </div>

      <div className="space-y-3">
        <dl className="grid grid-cols-2 gap-1.5">
          {held.map((item) => (
            <div key={item.label} className="flex items-center gap-2 rounded-lg border border-line bg-surface-2/40 px-2.5 py-1.5">
              <item.icon className={cn("size-3.5 shrink-0", item.tone)} />
              <dt className="min-w-0 flex-1 truncate text-[11.5px] text-text-2">{item.label}</dt>
              <dd className="font-heading text-[13px] font-semibold text-text-1 tabular">{formatNumber(item.value)}</dd>
            </div>
          ))}
        </dl>
        <div className="flex items-center justify-between rounded-lg border border-cyan/25 bg-cyan-soft px-3 py-2 text-xs">
          <span className="text-text-2">Daily cap remaining</span>
          <span className="font-heading text-sm font-semibold text-text-1 tabular">
            {counts.daily_cap_remaining === null || counts.daily_cap_remaining === undefined ? (
              <span className="font-normal text-text-3">no cap set</span>
            ) : (
              <>
                {formatNumber(counts.daily_cap_remaining)}
                <span className="font-normal text-text-3">
                  {" "}
                  of {formatNumber(counts.daily_cap)} · {formatNumber(counts.dispatched_today)} today
                </span>
              </>
            )}
          </span>
        </div>
      </div>
    </div>
  );
}

// -------------------------------------------------------------------------------------
// One job in the plan
// -------------------------------------------------------------------------------------

function PlanRow({ job, ticked, onTick }: { job: JobPlan; ticked: boolean; onTick: (on: boolean) => void }) {
  const [open, setOpen] = useState(false);
  const detailId = `plan-${job.job_id}`;
  const issues = (job.blocking_reasons?.length ?? 0) + (job.unresolved_questions?.length ?? 0);

  return (
    <li className={cn("bg-surface-1 transition-colors", open && "bg-surface-2/30")}>
      <div className="flex items-center gap-3 px-3 py-2.5">
        <div className="grid w-5 shrink-0 place-items-center">
          {job.queued ? (
            <Checkbox
              checked={ticked}
              onCheckedChange={(next) => onTick(next === true)}
              aria-label={`Include ${job.title} at ${job.employer} in this run`}
            />
          ) : (
            <span className="size-1.5 rounded-full bg-line-strong" aria-hidden />
          )}
        </div>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={detailId}
          onClick={() => setOpen((value) => !value)}
          className="group flex min-w-0 flex-1 items-center gap-3 rounded-md text-left"
        >
          <ScoreRing score={job.score} band={job.band} size={36} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium text-text-1 group-hover:text-violet">{job.title}</span>
            <span className="block truncate text-xs text-text-3">
              {job.employer} · {job.platform_name || job.platform}
              {job.posted_at ? ` · posted ${formatRelative(job.posted_at)}` : ""}
            </span>
          </span>
          <span className="hidden items-center gap-1.5 sm:flex">
            <FitDot label="Location" fit={job.location_fit} />
            <FitDot label="Experience" fit={job.experience_fit} />
            {issues ? (
              <span className="text-[11px] text-warning tabular">{issues} issue(s)</span>
            ) : null}
          </span>
          <StateBadge value={job.status} map={PLAN_STATUS} />
          <ChevronDown className={cn("size-4 shrink-0 text-text-3 transition-transform duration-200", open && "rotate-180")} />
        </button>
      </div>
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
            <PlanDetail job={job} />
          </motion.div>
        ) : null}
      </AnimatePresence>
    </li>
  );
}

function FitDot({ label, fit }: { label: string; fit: Schemas["FitRead"] }) {
  const Icon = fit.status === "ok" ? CheckCircle2 : fit.status === "fail" ? XCircle : CircleHelp;
  return (
    <span
      title={`${label}: ${fit.status}${fit.detail ? ` — ${fit.detail}` : ""}`}
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10.5px]",
        fit.status === "ok" && "text-success",
        fit.status === "fail" && "text-danger",
        fit.status !== "ok" && fit.status !== "fail" && "text-text-3",
      )}
    >
      <Icon className="size-3" />
      {label}
    </span>
  );
}

const PROVENANCE: Record<string, string> = {
  profile_verified: "From profile",
  resume_extracted: "From resume",
  ai_draft: "AI draft",
  user_entered: "You entered",
  needs_user_input: "Needs you",
};

function PlanDetail({ job }: { job: JobPlan }) {
  const coverage = job.evidence_coverage;
  const letter = job.cover_letter_preview?.trim() ?? "";
  const letterIsText = letter && letter !== "none" && letter !== "drafted at preparation";

  return (
    <div className="space-y-4 border-t border-line px-4 pb-4 pt-3.5 sm:pl-11">
      {job.blocking_reasons?.length ? (
        <Callout tone="danger" icon={Ban} title="Why it is not in this run">
          <ul className="list-disc space-y-0.5 pl-4">
            {job.blocking_reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </Callout>
      ) : null}
      {job.unresolved_questions?.length ? (
        <Callout tone="warning" icon={MessageSquareWarning} title="Questions still open">
          <ul className="list-disc space-y-0.5 pl-4">
            {job.unresolved_questions.map((question) => (
              <li key={question}>{question}</li>
            ))}
          </ul>
          <Link href="/action-inbox" className="mt-1.5 inline-block text-violet hover:underline">
            Answer them in the Action inbox
          </Link>
        </Callout>
      ) : null}
      {job.warnings?.length ? (
        <Callout tone="warning" icon={AlertTriangle} title="Warnings">
          <ul className="list-disc space-y-0.5 pl-4">
            {job.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </Callout>
      ) : null}

      <dl className="grid gap-x-6 gap-y-3 text-xs sm:grid-cols-2 lg:grid-cols-3">
        <Fact label="Score">
          {job.score === null || job.score === undefined ? "—" : Math.round(job.score)}
          {job.band ? <span className="text-text-3"> · {humanize(job.band)} band</span> : null}
        </Fact>
        <Fact label="Confidence">
          {job.confidence ? humanize(job.confidence) : "—"}
          <span className="text-text-3">
            {" "}
            · evidence coverage {coverage === null || coverage === undefined ? "—" : `${Math.round(coverage * 100)}%`}
          </span>
        </Fact>
        <Fact label="Role family">{job.role_family ? humanize(job.role_family) : "—"}</Fact>
        <Fact label="Location fit">
          <FitText fit={job.location_fit} />
        </Fact>
        <Fact label="Experience fit">
          <FitText fit={job.experience_fit} />
        </Fact>
        <Fact label="Sources">{job.sources.length ? job.sources.map(humanize).join(", ") : "—"}</Fact>
        <Fact label="Platform" className="sm:col-span-2 lg:col-span-3">
          <span className="font-medium">{job.platform_name || job.platform}</span>{" "}
          <StatusBadge tone={job.submission_supported ? "success" : "neutral"} className="ml-1 align-middle">
            {job.submission_supported ? "Submission permitted" : "No submission"}
          </StatusBadge>
          {job.capability_reason ? <p className="mt-1 text-text-3">{job.capability_reason}</p> : null}
        </Fact>
        <Fact label="Resume" className="sm:col-span-2 lg:col-span-3">
          <span className="inline-flex items-center gap-1.5">
            <FileText className="size-3.5 text-text-3" /> {job.resume_artifact || "—"}
          </span>
        </Fact>
      </dl>

      {job.screening_answers?.length ? (
        <div>
          <h4 className="mb-1.5 text-xs font-semibold text-text-1">Answers that would be sent</h4>
          <div className="overflow-hidden rounded-lg border border-line">
            <Table>
              <TableHeader>
                <TableRow className="border-line hover:bg-transparent">
                  <TableHead className="h-8 bg-surface-2/50 text-[11px] text-text-3">Question</TableHead>
                  <TableHead className="h-8 bg-surface-2/50 text-[11px] text-text-3">Answer</TableHead>
                  <TableHead className="h-8 bg-surface-2/50 text-[11px] text-text-3">From</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {job.screening_answers.map((answer) => (
                  <TableRow key={answer.question_key} className="border-line">
                    <TableCell className="max-w-[18rem] whitespace-normal py-1.5 text-xs text-text-2">{answer.question}</TableCell>
                    <TableCell className="max-w-[18rem] whitespace-normal py-1.5 text-xs text-text-1">
                      {answer.sensitive ? (
                        <span className="inline-flex items-center gap-1.5" title="Sensitive answer, masked in the preview">
                          <Lock className="size-3 text-text-3" /> {answer.answer || "—"}
                        </span>
                      ) : (
                        answer.answer || <span className="text-text-3">—</span>
                      )}
                    </TableCell>
                    <TableCell className="py-1.5 text-[11px] text-text-3">
                      {PROVENANCE[answer.provenance] ?? humanize(answer.provenance)}
                      {answer.source ? ` · ${answer.source}` : ""}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      ) : null}

      <div>
        <h4 className="mb-1.5 text-xs font-semibold text-text-1">Cover letter</h4>
        {letterIsText ? (
          <p className="whitespace-pre-line rounded-lg border border-line bg-surface-2/40 p-3 text-xs leading-relaxed text-text-2">
            {letter}
            {/* The preflight sends the first 400 characters. */}
            {(job.cover_letter_preview ?? "").length >= 400 ? <span className="text-text-3">…</span> : null}
          </p>
        ) : (
          <p className="text-xs text-text-3">{letter ? humanize(letter) : "None"}</p>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        {job.application_id ? (
          <Button asChild size="sm" variant="outline">
            <Link href={`/applications/${job.application_id}`}>Open application</Link>
          </Button>
        ) : null}
        {job.url ? (
          <Button asChild size="sm" variant="ghost">
            <a href={job.url} target="_blank" rel="noreferrer noopener">
              Listing <ExternalLink />
            </a>
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function Fact({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={className}>
      <dt className="text-[10.5px] font-medium uppercase tracking-wider text-text-3">{label}</dt>
      <dd className="mt-0.5 text-text-1">{children}</dd>
    </div>
  );
}

function FitText({ fit }: { fit: Schemas["FitRead"] }) {
  return (
    <span>
      <span
        className={cn(
          "font-medium",
          fit.status === "ok" && "text-success",
          fit.status === "fail" && "text-danger",
          fit.status !== "ok" && fit.status !== "fail" && "text-text-3",
        )}
      >
        {fit.status === "ok" ? "Fits" : fit.status === "fail" ? "Fails" : "Unknown"}
      </span>
      {fit.detail ? <span className="text-text-3"> — {fit.detail}</span> : null}
    </span>
  );
}

function Callout({
  tone,
  icon: Icon,
  title,
  children,
}: {
  tone: "danger" | "warning";
  icon: typeof Ban;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border px-3 py-2.5 text-xs leading-relaxed text-text-1",
        tone === "danger" ? "border-danger/25 bg-danger-soft" : "border-warning/25 bg-warning-soft",
      )}
    >
      <p className="mb-1 flex items-center gap-1.5 font-semibold">
        <Icon className={cn("size-3.5", tone === "danger" ? "text-danger" : "text-warning")} /> {title}
      </p>
      {children}
    </div>
  );
}
