"use client";

import { Bookmark, BookmarkCheck, Building2, CalendarClock, FileCheck2, Laptop, MapPin } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";

import { ScoreRing } from "@/components/shared/score-ring";
import { StateBadge, StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { BAND, JOB_STATUS } from "@/lib/constants/states";
import { formatDate } from "@/lib/formatting";
import { cn } from "@/lib/utils";

import { Meta, SourceChips, VerdictBadge } from "./job-bits";
import {
  WORK_ARRANGEMENT_LABEL,
  experienceVerdict,
  freshnessVerdict,
  isSaved,
  jobSources,
  postedLabel,
  type Job,
} from "./job-utils";

export function JobCard({
  job,
  index = 0,
  active,
  checked,
  onCheckedChange,
  onOpen,
  onSave,
  saving,
}: {
  job: Job;
  index?: number;
  active?: boolean;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  onOpen: () => void;
  onSave: () => void;
  saving?: boolean;
}) {
  const reduced = useReducedMotion();
  const saved = isSaved(job);
  const match = job.match ?? null;
  const sources = jobSources(job);
  const showStatus = job.status !== "SHORTLISTED" && job.status !== "SCORED";

  return (
    <motion.article
      layout={false}
      initial={reduced ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, delay: reduced ? 0 : Math.min(index, 12) * 0.025, ease: [0.22, 1, 0.36, 1] }}
      onClick={onOpen}
      aria-current={active ? "true" : undefined}
      className={cn(
        "orbit-card group relative cursor-pointer p-4 transition-[border-color,box-shadow,background-color] duration-200",
        "hover:border-line-strong hover:shadow-raised",
        active && "border-violet/50 shadow-glow",
        checked && !active && "border-violet/30 bg-violet-soft/40",
      )}
    >
      {active ? (
        <span aria-hidden className="absolute inset-y-3 left-0 w-0.5 rounded-full bg-gradient-to-b from-violet to-cyan" />
      ) : null}
      <div className="flex items-start gap-3">
        <div className="pt-0.5" onClick={(event) => event.stopPropagation()}>
          <Checkbox
            checked={checked}
            onCheckedChange={(value) => onCheckedChange(value === true)}
            aria-label={`Select ${job.title} at ${job.company}`}
          />
        </div>

        <div className="min-w-0 flex-1 space-y-2">
          <div className="min-w-0">
            <h3 className="text-[14.5px] font-semibold leading-snug text-text-1">
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  onOpen();
                }}
                className="text-left decoration-violet/60 underline-offset-4 outline-none hover:underline focus-visible:underline"
              >
                {job.title}
              </button>
            </h3>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px]">
              <Meta icon={Building2} className="font-medium text-text-1">
                {job.company}
              </Meta>
              <Meta icon={MapPin}>{job.location || "Location not stated"}</Meta>
              <Meta icon={Laptop}>{WORK_ARRANGEMENT_LABEL[job.work_arrangement]}</Meta>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            {match ? <StateBadge value={match.band} map={BAND} /> : <StatusBadge dot={false}>Not scored</StatusBadge>}
            <VerdictBadge verdict={experienceVerdict(job)} prefix="Experience" />
            <VerdictBadge verdict={freshnessVerdict(job)} prefix="Freshness" />
            {saved ? <StateBadge value="SHORTLISTED" map={JOB_STATUS} /> : null}
            {showStatus ? <StateBadge value={job.status} map={JOB_STATUS} /> : null}
            {job.has_application ? (
              <StatusBadge tone="violet" dot={false}>
                <FileCheck2 className="size-3" aria-hidden /> Application exists
              </StatusBadge>
            ) : null}
            {job.duplicate_count > 0 ? (
              <StatusBadge dot={false}>
                {job.duplicate_count} duplicate{job.duplicate_count === 1 ? "" : "s"}
              </StatusBadge>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 text-[11.5px] text-text-3">
            <SourceChips sources={sources} />
            <span
              className="inline-flex items-center gap-1 tabular"
              title={job.posted_at ? `Posted ${formatDate(job.posted_at)}` : "No posting date from the source"}
            >
              <CalendarClock className="size-3.5" aria-hidden />
              {job.posted_at ? `Posted ${postedLabel(job)}` : "Undated"}
            </span>
          </div>
        </div>

        <div className="flex shrink-0 flex-col items-center gap-2">
          <ScoreRing score={match?.total_score} band={match?.band} size={46} />
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label={saved ? "Saved" : `Save ${job.title}`}
                aria-pressed={saved}
                disabled={saved || saving}
                onClick={(event) => {
                  event.stopPropagation();
                  onSave();
                }}
                className={cn(saved ? "text-violet disabled:opacity-100" : "text-text-3 hover:text-violet")}
              >
                {saved ? <BookmarkCheck /> : <Bookmark />}
              </Button>
            </TooltipTrigger>
            <TooltipContent>{saved ? "Saved" : "Save job"}</TooltipContent>
          </Tooltip>
        </div>
      </div>
    </motion.article>
  );
}

export function JobCardSkeleton() {
  return (
    <div className="orbit-card flex items-start gap-3 p-4">
      <Skeleton className="mt-0.5 size-4 rounded" />
      <div className="flex-1 space-y-2.5">
        <Skeleton className="h-4 w-3/5" />
        <Skeleton className="h-3 w-2/5" />
        <div className="flex gap-1.5">
          <Skeleton className="h-5 w-20 rounded-full" />
          <Skeleton className="h-5 w-28 rounded-full" />
          <Skeleton className="h-5 w-16 rounded-full" />
        </div>
        <Skeleton className="h-3 w-1/3" />
      </div>
      <Skeleton className="size-[46px] rounded-full" />
    </div>
  );
}
