"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "motion/react";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  FileText,
  GraduationCap,
  History,
  Loader2,
  Lock,
  LockOpen,
  RefreshCw,
  Save,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ConfirmDialog } from "@/components/auto-apply/confirm-dialog";
import { Field } from "@/components/auto-apply/form-bits";
import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState, errorMessage } from "@/components/shared/query-state";
import { StateBadge, StatusBadge } from "@/components/shared/status-badge";
import { Surface } from "@/components/shared/surface";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import type { ArtifactVersion } from "@/lib/api/types";
import { APPLICATION_STATUS, OUTCOME } from "@/lib/constants/states";
import { formatDate, formatDateTime, formatNumber, humanize } from "@/lib/formatting";
import { cn } from "@/lib/utils";

import {
  NEXT_STATUSES,
  OUTCOMES,
  OpenEmployerButton,
  PROVENANCE,
  useInvalidateApplications,
  type ApplicationDetail,
  type ApplicationStatus,
} from "./shared";

export function ApplicationDetailView({ id }: { id: number }) {
  const query = useQuery({ queryKey: ["applications", "detail", id], queryFn: () => api.application(id) });

  if (query.isPending) return <DetailSkeleton />;
  if (query.isError) {
    const notFound = query.error instanceof ApiError && query.error.status === 404;
    return (
      <div className="space-y-4">
        <BackLink />
        {notFound ? (
          <EmptyState icon={FileText} title={`Application ${id} was not found`} description="It may have been removed." />
        ) : (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        )}
      </div>
    );
  }
  return <Detail app={query.data} />;
}

function BackLink() {
  return (
    <Link href="/applications" className="inline-flex items-center gap-1.5 text-xs text-text-3 transition-colors hover:text-text-1">
      <ArrowLeft className="size-3.5" /> Applications
    </Link>
  );
}

function Detail({ app }: { app: ApplicationDetail }) {
  const queryClient = useQueryClient();
  const invalidate = useInvalidateApplications();
  const [regenOpen, setRegenOpen] = useState(false);

  const regenerate = useMutation({
    mutationFn: () => api.regenerateApplication(app.id),
    onSuccess: (next) => {
      queryClient.setQueryData(["applications", "detail", app.id], next);
      invalidate();
      setRegenOpen(false);
      toast.success("Drafts regenerated", { description: "Earlier versions are kept under Versions." });
    },
    onError: (error) => {
      setRegenOpen(false);
      toast.error("Drafts were not regenerated", { description: errorMessage(error) });
    },
  });
  const blocking = app.blocking_questions ?? [];

  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }} className="space-y-6">
      <div className="space-y-3">
        <BackLink />
        <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0 space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-violet">{app.job_company || "Employer not recorded"}</p>
            <h1 className="font-heading text-2xl font-semibold tracking-tight text-text-1 sm:text-[28px]">
              {app.job_title || `Job ${app.job_id}`}
            </h1>
            <div className="flex flex-wrap items-center gap-1.5">
              <StateBadge value={app.status} map={APPLICATION_STATUS} />
              <StateBadge value={app.outcome} map={OUTCOME} />
              <StatusBadge tone="neutral" dot={false}>
                {humanize(app.platform)}
              </StatusBadge>
              {app.employer_page_opened ? (
                <StatusBadge tone="cyan" dot={false}>
                  Employer page opened
                </StatusBadge>
              ) : null}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={() => setRegenOpen(true)} disabled={regenerate.isPending}>
              {regenerate.isPending ? <Loader2 className="animate-spin" /> : <RefreshCw />} Regenerate drafts
            </Button>
            <Button asChild variant="outline">
              <Link href={`/interview-prep?application=${app.id}`}>
                <GraduationCap /> Interview prep
              </Link>
            </Button>
            <OpenEmployerButton application={app} size="default" variant="default" />
          </div>
        </header>
      </div>

      {regenerate.isError ? (
        <div role="alert" className="flex items-start gap-2.5 rounded-xl border border-danger/25 bg-danger-soft px-4 py-3 text-xs text-text-1">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-danger" />
          <div>
            <p className="font-semibold">Drafts were not regenerated</p>
            <p className="text-text-2">{errorMessage(regenerate.error)}</p>
          </div>
        </div>
      ) : null}

      <div className="flex items-start gap-3 rounded-xl border border-violet/25 bg-violet-soft px-4 py-3">
        <Sparkles className="mt-0.5 size-4 shrink-0 text-violet" />
        <div className="min-w-0 text-sm">
          <p className="font-medium text-text-1">{app.next_action || "No next step recorded."}</p>
          {blocking.length ? (
            <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-xs text-text-2">
              {blocking.map((question) => (
                <li key={question}>{question}</li>
              ))}
            </ul>
          ) : null}
          {blocking.length ? (
            <Link href="/action-inbox" className="mt-1.5 inline-flex items-center gap-1 text-xs text-violet hover:underline">
              Answer in the Action inbox <ArrowRight className="size-3" />
            </Link>
          ) : null}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-6">
          <Surface className="p-5">
            <CardTitle
              title="Cover letter"
              meta={`v${app.cover_letter_version} · ${humanize(app.cover_letter_generated_by) || "—"}`}
            />
            {app.cover_letter ? (
              <p className="whitespace-pre-line text-sm leading-relaxed text-text-2">{app.cover_letter}</p>
            ) : (
              <p className="text-sm text-text-3">No cover letter for this application.</p>
            )}
            <p className="mt-3 text-xs text-text-3">Resume: {app.resume_version_label || "—"}</p>
          </Surface>

          <Answers app={app} />
          <Artifacts id={app.id} />
        </div>

        <div className="space-y-6">
          <StatusCard app={app} />
          <OutcomeCard app={app} />
          <RecordCard app={app} />
          <Timeline app={app} />
        </div>
      </div>

      <ConfirmDialog
        open={regenOpen}
        onOpenChange={setRegenOpen}
        icon={<RefreshCw className="size-4" />}
        title="Regenerate the drafts?"
        description="The resume variant, cover letter and answers are prepared again. Earlier versions are kept. If this application may already be with the employer, the backend refuses, because its drafts are the record of what was sent."
        confirmLabel="Regenerate"
        pending={regenerate.isPending}
        onConfirm={() => regenerate.mutate()}
      />
    </motion.div>
  );
}

function CardTitle({ title, meta, icon }: { title: string; meta?: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <h2 className="flex items-center gap-2 font-heading text-[15px] font-semibold text-text-1">
        {icon}
        {title}
      </h2>
      {meta ? <span className="text-xs text-text-3">{meta}</span> : null}
    </div>
  );
}

function Answers({ app }: { app: ApplicationDetail }) {
  const answers = app.answers ?? [];
  return (
    <Surface className="overflow-hidden">
      <div className="px-5 pt-5">
        <CardTitle title="Answers" meta={`${answers.length} question(s)`} />
      </div>
      {answers.length === 0 ? (
        <p className="px-5 pb-5 text-sm text-text-3">No screening answers were prepared.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow className="border-line hover:bg-transparent">
              <TableHead className="h-8 bg-surface-2/50 pl-5 text-[11px] uppercase tracking-wider text-text-3">Question</TableHead>
              <TableHead className="h-8 bg-surface-2/50 text-[11px] uppercase tracking-wider text-text-3">Answer</TableHead>
              <TableHead className="h-8 bg-surface-2/50 pr-5 text-[11px] uppercase tracking-wider text-text-3">Provenance</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {answers.map((answer) => {
              const provenance = PROVENANCE[answer.provenance] ?? { label: humanize(answer.provenance), tone: "neutral" as const };
              const missing = !answer.answer?.trim();
              return (
                <TableRow key={answer.id} className="border-line align-top">
                  <TableCell className="max-w-[16rem] whitespace-normal py-2 pl-5 text-xs text-text-2">
                    {answer.question}
                    {answer.flag_reason ? <p className="mt-0.5 text-[11px] text-warning">{answer.flag_reason}</p> : null}
                  </TableCell>
                  <TableCell className="max-w-[20rem] whitespace-normal break-words py-2 text-xs text-text-1">
                    {missing ? <span className="text-warning">Not answered</span> : answer.answer}
                  </TableCell>
                  <TableCell className="py-2 pr-5">
                    <div className="flex flex-wrap gap-1">
                      <StatusBadge tone={provenance.tone}>{provenance.label}</StatusBadge>
                      {answer.is_sensitive ? (
                        <StatusBadge tone="neutral" dot={false}>
                          <Lock className="size-3" /> Sensitive
                        </StatusBadge>
                      ) : null}
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </Surface>
  );
}

function Artifacts({ id }: { id: number }) {
  const query = useQuery({ queryKey: ["applications", "artifacts", id], queryFn: () => api.applicationArtifacts(id) });
  return (
    <Surface className="p-5">
      <CardTitle title="Versions" meta="Newest first. Locked versions were part of a dispatched submission." />
      {query.isPending ? (
        <div className="space-y-2">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : query.data.length === 0 ? (
        <p className="text-sm text-text-3">No versions recorded yet.</p>
      ) : (
        <ul className="space-y-2">
          {query.data.map((artifact) => (
            <ArtifactRow key={artifact.id} artifact={artifact} />
          ))}
        </ul>
      )}
    </Surface>
  );
}

function ArtifactRow({ artifact }: { artifact: ArtifactVersion }) {
  const [open, setOpen] = useState(false);
  return (
    <li className={cn("rounded-lg border", artifact.locked ? "border-warning/25 bg-warning-soft/40" : "border-line bg-surface-2/30")}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-3 px-3 py-2 text-left"
      >
        {artifact.locked ? <Lock className="size-4 shrink-0 text-warning" /> : <LockOpen className="size-4 shrink-0 text-text-3" />}
        <span className="min-w-0 flex-1">
          <span className="block text-sm text-text-1">
            {humanize(artifact.kind)} <span className="text-text-3">· {artifact.label}</span>
          </span>
          <span className="block text-[11px] text-text-3">
            {formatDateTime(artifact.created_at)} · {formatNumber(artifact.byte_size)} bytes ·{" "}
            <span className="font-mono">{artifact.content_sha256.slice(0, 10)}</span>
          </span>
        </span>
        {artifact.locked ? (
          <StatusBadge tone="warning" dot={false}>
            Locked {artifact.locked_at ? formatDate(artifact.locked_at) : ""}
          </StatusBadge>
        ) : null}
      </button>
      {open ? (
        <p className="whitespace-pre-line border-t border-line px-3 py-2.5 text-xs leading-relaxed text-text-2">
          {artifact.preview || "No text preview."}
          {artifact.preview.length >= 600 ? <span className="text-text-3">…</span> : null}
        </p>
      ) : null}
    </li>
  );
}

// -------------------------------------------------------------------------------------
// Status
// -------------------------------------------------------------------------------------

function StatusCard({ app }: { app: ApplicationDetail }) {
  const queryClient = useQueryClient();
  const invalidate = useInvalidateApplications();
  const options = NEXT_STATUSES[app.status] ?? [];
  const [target, setTarget] = useState<ApplicationStatus | "">("");
  const [reviewed, setReviewed] = useState(false);
  const [submittedBy, setSubmittedBy] = useState("");
  const [evidence, setEvidence] = useState("");

  const update = useMutation({
    mutationFn: () => {
      if (!target) throw new Error("Pick a status");
      return api.updateApplication(app.id, {
        status: target,
        ...(target === "APPROVED" ? { user_approved: true } : {}),
        ...(target === "SUBMITTED" ? { submitted_by: submittedBy.trim() } : {}),
        ...(target === "CONFIRMED" || (target === "SUBMITTED" && evidence.trim())
          ? { confirmation_evidence: evidence.trim() }
          : {}),
      });
    },
    onSuccess: (next) => {
      queryClient.setQueryData(["applications", "detail", app.id], next);
      invalidate();
      setTarget("");
      setReviewed(false);
      setSubmittedBy("");
      setEvidence("");
      toast.success(`Status is now ${APPLICATION_STATUS[next.status]?.label ?? next.status}`);
    },
  });

  const missing =
    (target === "APPROVED" && !reviewed) ||
    (target === "SUBMITTED" && !submittedBy.trim()) ||
    (target === "CONFIRMED" && !evidence.trim());

  return (
    <Surface className="p-5">
      <CardTitle title="Status" icon={<History className="size-4 text-text-3" />} />
      <div className="mb-3 flex items-center gap-2 text-sm">
        <span className="text-text-3">Now</span>
        <StateBadge value={app.status} map={APPLICATION_STATUS} />
      </div>
      {options.length === 0 ? (
        <p className="text-xs text-text-3">This status is final.</p>
      ) : (
        <div className="space-y-3">
          <Field label="Move to" htmlFor="status-target">
            <Select value={target} onValueChange={(next) => setTarget(next as ApplicationStatus)}>
              <SelectTrigger id="status-target" className="w-full">
                <SelectValue placeholder="Choose the next status" />
              </SelectTrigger>
              <SelectContent>
                {options.map((value) => (
                  <SelectItem key={value} value={value}>
                    {APPLICATION_STATUS[value]?.label ?? humanize(value)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          {target === "APPROVED" ? (
            <label className="flex cursor-pointer items-start gap-2.5 text-xs text-text-1">
              <Checkbox checked={reviewed} onCheckedChange={(next) => setReviewed(next === true)} className="mt-0.5" />
              I reviewed the cover letter and answers and approve this application.
            </label>
          ) : null}
          {target === "SUBMITTED" ? (
            <Field label="Who submitted it" htmlFor="submitted-by" hint="A person's name. Applications are recorded as submitted only by a human.">
              <Input id="submitted-by" value={submittedBy} onChange={(event) => setSubmittedBy(event.target.value)} placeholder="Your name" />
            </Field>
          ) : null}
          {target === "CONFIRMED" || target === "SUBMITTED" ? (
            <Field
              label={target === "CONFIRMED" ? "Confirmation evidence" : "Confirmation evidence (optional)"}
              htmlFor="confirm-evidence"
              hint="A confirmation email subject or reference number. A click is not a confirmation."
            >
              <Textarea id="confirm-evidence" value={evidence} onChange={(event) => setEvidence(event.target.value)} className="min-h-14" />
            </Field>
          ) : null}
          <Button className="w-full" disabled={!target || missing || update.isPending} onClick={() => update.mutate()}>
            {update.isPending ? <Loader2 className="animate-spin" /> : null} Update status
          </Button>
          {update.isError ? (
            <p role="alert" className="rounded-lg bg-danger-soft px-3 py-2 text-xs text-text-1">
              {errorMessage(update.error)}
            </p>
          ) : null}
        </div>
      )}
    </Surface>
  );
}

// -------------------------------------------------------------------------------------
// Outcome, interview stage, follow-up, notes
// -------------------------------------------------------------------------------------

const outcomeSchema = z.object({
  outcome: z.enum(OUTCOMES as [string, ...string[]]),
  interview_status: z.string().max(100, "Keep it under 100 characters"),
  follow_up_date: z.string().regex(/^(\d{4}-\d{2}-\d{2})?$/, "Use a valid date"),
  notes: z.string().max(8000, "Notes are limited to 8,000 characters"),
});
type OutcomeValues = z.infer<typeof outcomeSchema>;

function OutcomeCard({ app }: { app: ApplicationDetail }) {
  const queryClient = useQueryClient();
  const invalidate = useInvalidateApplications();
  const defaults: OutcomeValues = {
    outcome: app.outcome,
    interview_status: app.interview_status ?? "",
    follow_up_date: app.follow_up_date ? app.follow_up_date.slice(0, 10) : "",
    notes: app.notes ?? "",
  };
  const form = useForm<OutcomeValues>({ resolver: zodResolver(outcomeSchema), defaultValues: defaults, values: defaults });
  const { dirtyFields, errors } = form.formState;

  const save = useMutation({
    mutationFn: (values: OutcomeValues) =>
      api.updateApplication(app.id, {
        ...(dirtyFields.outcome ? { outcome: values.outcome as ApplicationDetail["outcome"] } : {}),
        ...(dirtyFields.interview_status ? { interview_status: values.interview_status } : {}),
        ...(dirtyFields.follow_up_date && values.follow_up_date ? { follow_up_date: values.follow_up_date } : {}),
        ...(dirtyFields.notes ? { notes: values.notes } : {}),
      }),
    onSuccess: (next) => {
      queryClient.setQueryData(["applications", "detail", app.id], next);
      invalidate();
      toast.success("Saved");
    },
  });
  const followUp = useWatch({ control: form.control, name: "follow_up_date" });
  const clearingDate = Boolean(dirtyFields.follow_up_date) && !followUp && Boolean(app.follow_up_date);

  return (
    <Surface className="p-5">
      <CardTitle title="Outcome & follow-up" />
      <form className="space-y-3" onSubmit={form.handleSubmit((values) => save.mutate(values))} noValidate>
        <Controller
          control={form.control}
          name="outcome"
          render={({ field }) => (
            <Field label="Outcome" htmlFor="outcome">
              <Select value={field.value} onValueChange={field.onChange}>
                <SelectTrigger id="outcome" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {OUTCOMES.map((value) => (
                    <SelectItem key={value} value={value}>
                      {OUTCOME[value]?.label ?? humanize(value)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          )}
        />
        <Field label="Interview stage" htmlFor="interview" error={errors.interview_status?.message}>
          <Input id="interview" placeholder="e.g. Technical round 2" {...form.register("interview_status")} />
        </Field>
        <Field
          label="Follow up on"
          htmlFor="follow-up"
          error={errors.follow_up_date?.message}
          hint={clearingDate ? "A follow-up date cannot be cleared here; the backend keeps the existing one." : undefined}
        >
          <Input id="follow-up" type="date" {...form.register("follow_up_date")} />
        </Field>
        <Field label="Notes" htmlFor="notes" error={errors.notes?.message}>
          <Textarea id="notes" className="min-h-20" {...form.register("notes")} />
        </Field>
        <Button type="submit" variant="outline" className="w-full" disabled={!form.formState.isDirty || save.isPending}>
          {save.isPending ? <Loader2 className="animate-spin" /> : <Save />} Save changes
        </Button>
        {save.isError ? (
          <p role="alert" className="rounded-lg bg-danger-soft px-3 py-2 text-xs text-text-1">
            {errorMessage(save.error)}
          </p>
        ) : null}
      </form>
    </Surface>
  );
}

function RecordCard({ app }: { app: ApplicationDetail }) {
  const rows: [string, React.ReactNode][] = [
    ["Prepared", formatDateTime(app.prepared_at)],
    ["Reviewed", formatDateTime(app.reviewed_at)],
    ["Approved", app.user_approved ? formatDateTime(app.approved_at) : "Not yet"],
    ["Submitted", app.submitted_at ? `${formatDateTime(app.submitted_at)}${app.submitted_by ? ` by ${app.submitted_by}` : ""}` : "—"],
    ["Confirmed", formatDateTime(app.confirmed_at)],
    ["Evidence", app.confirmation_evidence || "—"],
  ];
  return (
    <Surface className="p-5">
      <CardTitle title="Record" />
      <dl className="space-y-2 text-xs">
        {rows.map(([label, value]) => (
          <div key={label} className="flex gap-3">
            <dt className="w-20 shrink-0 text-text-3">{label}</dt>
            <dd className="min-w-0 break-words text-text-1">{value}</dd>
          </div>
        ))}
      </dl>
    </Surface>
  );
}

function Timeline({ app }: { app: ApplicationDetail }) {
  const events = [...(app.events ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at));
  return (
    <Surface className="p-5">
      <CardTitle title="Timeline" meta={`${events.length} event(s)`} />
      {events.length === 0 ? (
        <p className="text-xs text-text-3">No events yet.</p>
      ) : (
        <ol className="relative space-y-3 border-l border-line pl-4">
          {events.map((event) => {
            const moved = event.from_status !== event.to_status;
            return (
              <li key={event.id} className="relative text-xs">
                <span className={cn("absolute -left-[21px] top-1 size-2 rounded-full ring-2 ring-surface-1", moved ? "bg-violet" : "bg-cyan")} />
                <div className="flex flex-wrap items-center gap-1">
                  {moved ? (
                    <>
                      {event.from_status ? <StateBadge value={event.from_status} map={APPLICATION_STATUS} /> : null}
                      <ArrowRight className="size-3 text-text-3" />
                      <StateBadge value={event.to_status} map={APPLICATION_STATUS} />
                    </>
                  ) : (
                    <span className="font-medium text-text-1">Note</span>
                  )}
                </div>
                {event.detail ? <p className="mt-1 text-text-2 first-letter:uppercase">{event.detail}</p> : null}
                <p className="text-[11px] text-text-3">
                  {formatDateTime(event.created_at)} · {event.actor}
                </p>
              </li>
            );
          })}
        </ol>
      )}
    </Surface>
  );
}

function DetailSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-3 w-24" />
      <div className="space-y-2">
        <Skeleton className="h-3 w-32" />
        <Skeleton className="h-8 w-80 max-w-full" />
        <Skeleton className="h-5 w-48" />
      </div>
      <Skeleton className="h-14 w-full rounded-xl" />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="space-y-6">
          <Skeleton className="h-56 w-full rounded-xl" />
          <Skeleton className="h-72 w-full rounded-xl" />
        </div>
        <div className="space-y-6">
          <Skeleton className="h-48 w-full rounded-xl" />
          <Skeleton className="h-72 w-full rounded-xl" />
        </div>
      </div>
    </div>
  );
}
