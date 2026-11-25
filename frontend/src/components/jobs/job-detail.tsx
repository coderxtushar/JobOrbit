"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Bookmark,
  BookmarkCheck,
  Building2,
  ClipboardList,
  CalendarClock,
  ExternalLink,
  FileCheck2,
  FileText,
  Laptop,
  Maximize2,
  MapPin,
  SearchCheck,
  SkipForward,
  Sparkles,
  Wand2,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ErrorState } from "@/components/shared/query-state";
import { StateBadge, StatusBadge } from "@/components/shared/status-badge";
import { Surface } from "@/components/shared/surface";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/endpoints";
import { BAND, JOB_STATUS } from "@/lib/constants/states";
import { formatDate, formatDateTime, formatSalary, humanize } from "@/lib/formatting";
import { cn } from "@/lib/utils";

import { CompanyMark, Meta, VerdictBadge } from "./job-bits";
import {
  EMPLOYMENT_TYPE_LABEL,
  WORK_ARRANGEMENT_LABEL,
  experienceVerdict,
  freshnessVerdict,
  isSaved,
  paragraphs,
  sourceLabel,
  type JobDetail,
} from "./job-utils";
import { MatchAnalysis } from "./match-analysis";
import { usePrepareJob, useSaveJob, useScoreJobs, useSkipJob } from "./use-job-actions";

/* ---------------- small layout pieces ---------------- */

function FactRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[7.5rem_1fr] gap-3 py-2 text-[12.5px]">
      <dt className="text-text-3">{label}</dt>
      <dd className="min-w-0 text-text-1">{children}</dd>
    </div>
  );
}

function NotStated({ children = "Not stated" }: { children?: React.ReactNode }) {
  return <span className="text-text-3">{children}</span>;
}

function Block({ title, children, className }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn("space-y-2", className)}>
      <h3 className="text-[11px] font-semibold uppercase tracking-wider text-text-3">{title}</h3>
      {children}
    </section>
  );
}

function SkillList({ skills, tone }: { skills: string[]; tone: "required" | "preferred" }) {
  if (!skills.length) return <NotStated>None listed</NotStated>;
  return (
    <div className="flex flex-wrap gap-1">
      {skills.map((skill) => (
        <span
          key={skill}
          className={cn(
            "rounded-md border px-1.5 py-0.5 text-[11.5px] font-medium",
            tone === "required" ? "border-cyan/25 bg-cyan-soft text-cyan" : "border-line bg-surface-2 text-text-2",
          )}
        >
          {skill}
        </span>
      ))}
    </div>
  );
}

/* ---------------- salary ---------------- */

function SalaryFacts({ job }: { job: JobDetail }) {
  const salary = useQuery({
    queryKey: ["job", job.id, "salary"],
    queryFn: () => api.jobSalary(job.id),
  });
  const stated = formatSalary(job.salary_min, job.salary_max, job.salary_currency);
  const listing = salary.data?.listing;
  const normalised =
    listing && listing.disclosed && (listing.inr_annual_minimum || listing.inr_annual_maximum)
      ? formatSalary(listing.inr_annual_minimum, listing.inr_annual_maximum, "INR")
      : "";
  return (
    <div className="space-y-1.5">
      <p>{stated || job.salary_raw || <NotStated>The listing does not state a salary</NotStated>}</p>
      {job.salary_raw && stated && job.salary_raw !== stated ? (
        <p className="text-[11.5px] text-text-3">Listing text: “{job.salary_raw}”</p>
      ) : null}
      {salary.isLoading ? <Skeleton className="h-3 w-40" /> : null}
      {salary.data ? (
        <div className="space-y-1 rounded-md border border-line bg-surface-2/60 p-2 text-[11.5px] leading-relaxed text-text-2">
          {normalised ? (
            <p>
              Normalised: <span className="font-medium text-text-1">{normalised}</span> per year
              {listing?.period ? ` (stated per ${listing.period})` : ""}
            </p>
          ) : null}
          {listing?.assumptions.map((assumption) => (
            <p key={assumption} className="text-text-3">
              · {assumption}
            </p>
          ))}
          {listing?.disclosed && salary.data.comparison.statement ? <p>{salary.data.comparison.statement}</p> : null}
        </div>
      ) : null}
    </div>
  );
}

/* ---------------- sections ---------------- */

function ListingFacts({ job }: { job: JobDetail }) {
  const experience = experienceVerdict(job);
  const freshness = freshnessVerdict(job);
  return (
    <div className="space-y-5">
      <dl className="divide-y divide-line">
        <FactRow label="Salary">
          <SalaryFacts job={job} />
        </FactRow>
        <FactRow label="Experience">
          <div className="flex flex-wrap items-center gap-1.5">
            <VerdictBadge verdict={experience} prefix="Experience" />
            {job.experience_raw ? <span className="text-text-3">“{job.experience_raw}”</span> : null}
          </div>
        </FactRow>
        <FactRow label="Education">
          {job.education_requirements.length ? (
            <ul className="space-y-0.5">
              {job.education_requirements.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : (
            <NotStated />
          )}
        </FactRow>
        <FactRow label="Employment">{EMPLOYMENT_TYPE_LABEL[job.employment_type]}</FactRow>
        <FactRow label="Work mode">{WORK_ARRANGEMENT_LABEL[job.work_arrangement]}</FactRow>
        <FactRow label="Apply via">{job.application_method ? humanize(job.application_method) : <NotStated />}</FactRow>
        <FactRow label="Posted">
          <div className="flex flex-wrap items-center gap-1.5">
            <span>
              {job.posted_at ? (
                <>
                  {job.posted_at_is_approximate ? "About " : ""}
                  {formatDate(job.posted_at)}
                </>
              ) : (
                <NotStated>Undated by the source</NotStated>
              )}
            </span>
            <VerdictBadge verdict={freshness} prefix="Freshness" />
          </div>
        </FactRow>
        <FactRow label="Discovered">{formatDateTime(job.discovered_at)}</FactRow>
        <FactRow label="Application">
          {job.has_application ? (
            <span className="inline-flex flex-wrap items-center gap-2">
              <StatusBadge tone="violet" dot={false}>
                <FileCheck2 className="size-3" aria-hidden /> An application exists
              </StatusBadge>
              <Link href="/applications" className="text-violet underline-offset-4 hover:underline">
                Open applications
              </Link>
            </span>
          ) : (
            <NotStated>No application prepared yet</NotStated>
          )}
        </FactRow>
        {job.duplicate_of_id !== null || job.duplicate_count > 0 ? (
          <FactRow label="Duplicates">
            {job.duplicate_of_id !== null ? (
              <Link href={`/jobs/${job.duplicate_of_id}`} className="text-violet underline-offset-4 hover:underline">
                Duplicate of job #{job.duplicate_of_id}
              </Link>
            ) : (
              `${job.duplicate_count} other listing${job.duplicate_count === 1 ? "" : "s"} merged into this one`
            )}
          </FactRow>
        ) : null}
      </dl>

      <Block title="Required skills · from the listing">
        <SkillList skills={job.required_skills} tone="required" />
      </Block>
      <Block title="Preferred skills · from the listing">
        <SkillList skills={job.preferred_skills} tone="preferred" />
      </Block>

      <Block title="Sources">
        {job.source_references?.length ? (
          <ul className="space-y-1.5">
            {job.source_references.map((ref) => (
              <li
                key={`${ref.source}-${ref.external_id ?? ref.url}`}
                className="flex items-center justify-between gap-3 rounded-md border border-line bg-surface-2/50 px-2.5 py-1.5 text-[12px]"
              >
                <span className="min-w-0">
                  <span className="font-medium text-text-1">{sourceLabel(ref.source)}</span>
                  <span className="text-text-3">
                    {" "}
                    · {humanize(ref.retrieval_method)} · {formatDate(ref.retrieved_at)}
                  </span>
                </span>
                {ref.url ? (
                  <a
                    href={ref.url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-flex shrink-0 items-center gap-1 text-violet hover:underline"
                  >
                    Open <ExternalLink className="size-3" aria-hidden />
                    <span className="sr-only">(opens in a new tab)</span>
                  </a>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <NotStated>No source recorded</NotStated>
        )}
      </Block>
    </div>
  );
}

function Description({ text }: { text: string }) {
  const parts = paragraphs(text);
  if (!parts.length) return <NotStated>The source supplied no description.</NotStated>;
  return (
    <div className="max-w-[68ch] space-y-3 text-[13.5px] leading-relaxed text-text-2">
      {parts.map((part, index) => (
        <p key={index} className="whitespace-pre-line break-words">
          {part}
        </p>
      ))}
    </div>
  );
}

/* ---------------- skip dialog ---------------- */

function SkipDialog({
  open,
  onOpenChange,
  job,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  job: JobDetail;
}) {
  const [reason, setReason] = useState("");
  const skip = useSkipJob();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Skip this job?</DialogTitle>
          <DialogDescription>
            “{job.title}” at {job.company} will be marked as skipped and left out of bulk preparation.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <Label htmlFor="skip-reason">Reason (optional)</Label>
          <Textarea
            id="skip-reason"
            value={reason}
            maxLength={300}
            onChange={(event) => setReason(event.target.value)}
            placeholder="e.g. Not interested in this domain"
          />
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={skip.isPending}
            onClick={() =>
              skip.mutate(
                { jobId: job.id, reason: reason.trim() },
                {
                  onSuccess: () => {
                    setReason("");
                    onOpenChange(false);
                  },
                },
              )
            }
          >
            <SkipForward /> {skip.isPending ? "Skipping…" : "Skip job"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ---------------- header + actions ---------------- */

function JobHeader({ job, variant }: { job: JobDetail; variant: "panel" | "page" }) {
  return (
    <div className="flex items-start gap-3">
      <CompanyMark company={job.company} size="lg" />
      <div className="min-w-0 flex-1 space-y-1.5">
        <h2
          className={cn(
            "font-heading font-semibold leading-tight tracking-tight text-text-1",
            variant === "page" ? "text-2xl" : "text-lg",
          )}
        >
          {job.title}
        </h2>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px]">
          <Meta icon={Building2} className="font-medium text-text-1">
            {job.company}
          </Meta>
          <Meta icon={MapPin}>{job.location || "Location not stated"}</Meta>
          <Meta icon={Laptop}>{WORK_ARRANGEMENT_LABEL[job.work_arrangement]}</Meta>
          <Meta icon={CalendarClock}>
            {job.posted_at ? `${job.posted_at_is_approximate ? "~" : ""}${formatDate(job.posted_at)}` : "Undated"}
          </Meta>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
          <StateBadge value={job.status} map={JOB_STATUS} />
          {job.match ? <StateBadge value={job.match.band} map={BAND} /> : <StatusBadge dot={false}>Not scored</StatusBadge>}
          {job.has_application ? (
            <StatusBadge tone="violet" dot={false}>
              Application exists
            </StatusBadge>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function JobActions({ job, variant }: { job: JobDetail; variant: "panel" | "page" }) {
  const save = useSaveJob();
  const prepare = usePrepareJob();
  const [skipOpen, setSkipOpen] = useState(false);
  const saved = isSaved(job);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        size="sm"
        onClick={() => prepare.mutate(job.id)}
        disabled={prepare.isPending}
        title="Drafts a resume variant, cover letter and answers. Nothing is submitted."
      >
        <Wand2 /> {prepare.isPending ? "Preparing…" : job.has_application ? "Prepare again" : "Prepare application"}
      </Button>
      <Button
        size="sm"
        variant="outline"
        onClick={() => save.mutate(job.id)}
        disabled={saved || save.isPending}
        aria-pressed={saved}
        className={cn(saved && "text-violet disabled:opacity-100")}
      >
        {saved ? <BookmarkCheck /> : <Bookmark />} {saved ? "Saved" : save.isPending ? "Saving…" : "Save"}
      </Button>
      <Button
        size="sm"
        variant="outline"
        onClick={() => setSkipOpen(true)}
        disabled={job.status === "SKIPPED"}
      >
        <SkipForward /> {job.status === "SKIPPED" ? "Skipped" : "Skip"}
      </Button>
      {job.url ? (
        <Button size="sm" variant="ghost" asChild>
          <a href={job.url} target="_blank" rel="noreferrer noopener">
            <ExternalLink /> Open listing<span className="sr-only"> (opens in a new tab)</span>
          </a>
        </Button>
      ) : null}
      <Button size="sm" variant="ghost" asChild>
        <Link href={`/company-research?job=${job.id}`}>
          <SearchCheck /> Company research
        </Link>
      </Button>
      {variant === "panel" ? (
        <Button size="sm" variant="ghost" asChild>
          <Link href={`/jobs/${job.id}`}>
            <Maximize2 /> Full view
          </Link>
        </Button>
      ) : null}
      <SkipDialog open={skipOpen} onOpenChange={setSkipOpen} job={job} />
    </div>
  );
}

/* ---------------- main ---------------- */

export function JobDetailSkeleton() {
  return (
    <div className="space-y-5">
      <div className="flex gap-3">
        <Skeleton className="size-11 rounded-lg" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-6 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-5 w-40 rounded-full" />
        </div>
      </div>
      <div className="flex gap-2">
        <Skeleton className="h-7 w-36" />
        <Skeleton className="h-7 w-20" />
        <Skeleton className="h-7 w-20" />
      </div>
      <Skeleton className="h-32 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

function useJobWithExplanation(jobId: number) {
  const job = useQuery({ queryKey: ["job", jobId], queryFn: () => api.job(jobId) });
  const scored = Boolean(job.data?.match);
  const explanation = useQuery({
    queryKey: ["job", jobId, "explanation"],
    queryFn: () => api.jobExplanation(jobId),
    enabled: scored,
  });
  return { job, explanation };
}

/**
 * Everything the API returns about one job. `panel` packs it into tabs for the side panel
 * and sheet; `page` lays it out in columns for /jobs/[id].
 */
export function JobDetailView({ jobId, variant }: { jobId: number; variant: "panel" | "page" }) {
  const { job, explanation } = useJobWithExplanation(jobId);
  const score = useScoreJobs();

  if (job.isLoading) return <JobDetailSkeleton />;
  if (job.isError || !job.data) return <ErrorState error={job.error} onRetry={() => job.refetch()} />;

  const data = job.data;
  const analysis = (
    <MatchAnalysis
      match={data.match}
      explanation={explanation.data}
      explanationLoading={explanation.isLoading}
      explanationError={explanation.error}
      onScore={() => score.mutate({ job_ids: [data.id], rescore_all: false, offset: 0 })}
      scoring={score.isPending}
    />
  );

  if (variant === "page") {
    return (
      <div className="space-y-6">
        <Surface className="space-y-4 p-5">
          <JobHeader job={data} variant="page" />
          <JobActions job={data} variant="page" />
          <p className="text-[11.5px] text-text-3">
            Preparing drafts the application for your review. Nothing is ever submitted from this page.
          </p>
        </Surface>
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,24rem)]">
          <Surface className="p-5">
            <h2 className="mb-4 flex items-center gap-2 font-heading text-[15px] font-semibold text-text-1">
              <Sparkles className="size-4 text-violet" aria-hidden /> Match analysis
            </h2>
            {analysis}
          </Surface>
          <Surface className="h-fit p-5">
            <h2 className="mb-2 font-heading text-[15px] font-semibold text-text-1">From the listing</h2>
            <ListingFacts job={data} />
          </Surface>
        </div>
        <Surface className="p-5">
          <h2 className="mb-3 font-heading text-[15px] font-semibold text-text-1">Description</h2>
          <Description text={data.description} />
        </Surface>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <JobHeader job={data} variant="panel" />
      <JobActions job={data} variant="panel" />
      <Tabs defaultValue="match" className="gap-3">
        <TabsList className="w-full">
          <TabsTrigger value="match">
            <Sparkles /> Match
          </TabsTrigger>
          <TabsTrigger value="listing">
            <ClipboardList /> Listing
          </TabsTrigger>
          <TabsTrigger value="description">
            <FileText /> Description
          </TabsTrigger>
        </TabsList>
        <TabsContent value="match">{analysis}</TabsContent>
        <TabsContent value="listing">
          <ListingFacts job={data} />
        </TabsContent>
        <TabsContent value="description">
          <Description text={data.description} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
