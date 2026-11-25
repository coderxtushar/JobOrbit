/**
 * Listing-level helpers for the job pages. Everything here is derived from fields the
 * listing itself carries (posted date, stated experience, sources); nothing is inferred
 * about the candidate and nothing is estimated.
 */
import type { JobListParams } from "@/lib/api/endpoints";
import type { Schemas } from "@/lib/api/client";
import type { Tone } from "@/lib/constants/states";
import { formatDate, formatRelative } from "@/lib/formatting";

export type Job = Schemas["JobRead"];
export type JobDetail = Schemas["JobDetail"];
export type SourceName = Schemas["SourceName"];
export type JobStatus = Schemas["JobStatus"];
export type SortBy = NonNullable<JobListParams["sort_by"]>;

export const SOURCE_LABEL: Record<SourceName, string> = {
  manual: "Manual",
  csv: "CSV import",
  email_alert: "Email alert",
  linkedin: "LinkedIn",
  indeed: "Indeed",
  naukri: "Naukri",
  wellfound: "Wellfound",
  instahyre: "Instahyre",
  cutshort: "Cutshort",
  hirist: "Hirist",
  greenhouse: "Greenhouse",
  lever: "Lever",
  workable: "Workable",
  ashby: "Ashby",
  smartrecruiters: "SmartRecruiters",
  arbeitnow: "Arbeitnow",
  remoteok: "RemoteOK",
  remotive: "Remotive",
  himalayas: "Himalayas",
  jobicy: "Jobicy",
  workday: "Workday",
  company_site: "Company site",
};

export const SOURCES = Object.keys(SOURCE_LABEL) as SourceName[];

export const JOB_STATUSES: JobStatus[] = [
  "DISCOVERED",
  "SCORED",
  "SHORTLISTED",
  "SKIPPED",
  "FILTERED_OUT",
  "EXPIRED",
  "DUPLICATE",
];

export const SORT_OPTIONS: { value: SortBy; label: string }[] = [
  { value: "score", label: "Match score" },
  { value: "posted_at", label: "Posted date" },
  { value: "discovered_at", label: "Discovered date" },
  { value: "company", label: "Company" },
  { value: "title", label: "Title" },
];

export const AGE_OPTIONS = [1, 3, 7, 14, 30, 60, 90];

export const WORK_ARRANGEMENT_LABEL: Record<Schemas["WorkArrangement"], string> = {
  remote: "Remote",
  hybrid: "Hybrid",
  onsite: "On-site",
  unknown: "Arrangement not stated",
};

export const EMPLOYMENT_TYPE_LABEL: Record<Schemas["EmploymentType"], string> = {
  full_time: "Full-time",
  part_time: "Part-time",
  internship: "Internship",
  contract: "Contract",
  temporary: "Temporary",
  unknown: "Type not stated",
};

export function sourceLabel(source: string): string {
  return SOURCE_LABEL[source as SourceName] ?? source;
}

/** Distinct sources a job was seen on, in the order they were recorded. */
export function jobSources(job: Pick<Job, "source_references">): SourceName[] {
  const seen = new Set<SourceName>();
  for (const ref of job.source_references ?? []) seen.add(ref.source);
  return [...seen];
}

export interface Verdict {
  label: string;
  detail: string;
  tone: Tone;
}

function years(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

/** The listing's own stated experience range, put into a level. No range means "not stated". */
export function experienceVerdict(
  job: Pick<Job, "experience_min_years" | "experience_max_years" | "experience_raw">,
): Verdict {
  const min = job.experience_min_years;
  const max = job.experience_max_years;
  if (min === null && max === null) {
    return {
      label: "Experience not stated",
      detail: job.experience_raw
        ? `The listing says "${job.experience_raw}" but gives no year range.`
        : "The listing does not state an experience requirement.",
      tone: "neutral",
    };
  }
  const range =
    min !== null && max !== null && max !== min
      ? `${years(min)}–${years(max)} yrs`
      : min !== null
        ? `${years(min)}+ yrs`
        : `up to ${years(max as number)} yrs`;
  const floor = min ?? 0;
  const level =
    floor <= 1 ? "Entry level" : floor <= 3 ? "Early career" : floor <= 6 ? "Mid level" : floor <= 10 ? "Senior" : "Staff+";
  return {
    label: `${level} · ${range}`,
    detail: `Stated by the listing${job.experience_raw ? `: "${job.experience_raw}"` : ""}.`,
    tone: floor <= 3 ? "cyan" : "neutral",
  };
}

function ageInDays(value: string): number {
  return (Date.now() - new Date(value).getTime()) / 86_400_000;
}

/** How old the posting is, from the listing's posted date. A missing date is "undated", not new. */
export function freshnessVerdict(job: Pick<Job, "posted_at" | "posted_at_is_approximate">): Verdict {
  if (!job.posted_at) {
    return {
      label: "Undated",
      detail: "The source gave no posting date, so its age is unknown.",
      tone: "neutral",
    };
  }
  const days = ageInDays(job.posted_at);
  const approx = job.posted_at_is_approximate ? "approximately " : "";
  const detail = `Posted ${approx}${formatDate(job.posted_at)}.`;
  if (days < 3) return { label: "Fresh", detail, tone: "success" };
  if (days <= 14) return { label: "Recent", detail, tone: "cyan" };
  if (days <= 30) return { label: "Aging", detail, tone: "neutral" };
  return { label: "Stale", detail, tone: "warning" };
}

export function postedLabel(job: Pick<Job, "posted_at" | "posted_at_is_approximate">): string {
  if (!job.posted_at) return "Undated";
  return `${job.posted_at_is_approximate ? "~" : ""}${formatRelative(job.posted_at)}`;
}

export function isSaved(job: Pick<Job, "status">): boolean {
  return job.status === "SHORTLISTED";
}

/* ---------------- filters <-> URL ---------------- */

export const DEFAULT_LIMIT = 25;
export const PAGE_SIZES = [25, 50, 100];

export interface JobFilters {
  search: string;
  status: JobStatus | null;
  source: SourceName | null;
  company: string;
  min_score: number | null;
  max_age_days: number | null;
  include_duplicates: boolean;
  sort_by: SortBy;
  descending: boolean;
  limit: number;
  offset: number;
}

function int(value: string | null, min: number, max: number): number | null {
  if (value === null || value.trim() === "") return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return null;
  return Math.min(max, Math.max(min, Math.round(parsed)));
}

export function readFilters(params: URLSearchParams, fixedStatus?: JobStatus): JobFilters {
  const status = params.get("status");
  const source = params.get("source");
  const sort = params.get("sort_by");
  return {
    search: params.get("search") ?? "",
    status: fixedStatus ?? (JOB_STATUSES.includes(status as JobStatus) ? (status as JobStatus) : null),
    source: SOURCES.includes(source as SourceName) ? (source as SourceName) : null,
    company: params.get("company") ?? "",
    min_score: int(params.get("min_score"), 0, 100),
    max_age_days: int(params.get("max_age_days"), 1, 3650),
    include_duplicates: params.get("include_duplicates") === "1",
    sort_by: SORT_OPTIONS.some((option) => option.value === sort) ? (sort as SortBy) : "score",
    descending: params.get("descending") !== "0",
    limit: int(params.get("limit"), 1, 200) ?? DEFAULT_LIMIT,
    offset: int(params.get("offset"), 0, 1_000_000) ?? 0,
  };
}

/** Write filters into a copy of `params`, dropping defaults so URLs stay short. */
export function writeFilters(params: URLSearchParams, filters: JobFilters, fixedStatus?: JobStatus): URLSearchParams {
  const next = new URLSearchParams(params);
  const set = (key: string, value: string | null) => {
    if (value === null || value === "") next.delete(key);
    else next.set(key, value);
  };
  set("search", filters.search.trim() || null);
  set("status", fixedStatus ? null : filters.status);
  set("source", filters.source);
  set("company", filters.company.trim() || null);
  set("min_score", filters.min_score === null ? null : String(filters.min_score));
  set("max_age_days", filters.max_age_days === null ? null : String(filters.max_age_days));
  set("include_duplicates", filters.include_duplicates ? "1" : null);
  set("sort_by", filters.sort_by === "score" ? null : filters.sort_by);
  set("descending", filters.descending ? null : "0");
  set("limit", filters.limit === DEFAULT_LIMIT ? null : String(filters.limit));
  set("offset", filters.offset === 0 ? null : String(filters.offset));
  return next;
}

export function toListParams(filters: JobFilters): JobListParams {
  return {
    search: filters.search.trim() || undefined,
    status: filters.status ?? undefined,
    source: filters.source ?? undefined,
    company: filters.company.trim() || undefined,
    min_score: filters.min_score ?? undefined,
    max_age_days: filters.max_age_days ?? undefined,
    include_duplicates: filters.include_duplicates || undefined,
    sort_by: filters.sort_by,
    descending: filters.descending,
    limit: filters.limit,
    offset: filters.offset,
  };
}

/** Number of narrowing filters set (search, sort and paging excluded). */
export function activeFilterCount(filters: JobFilters, fixedStatus?: JobStatus): number {
  return [
    !fixedStatus && filters.status,
    filters.source,
    filters.company.trim(),
    filters.min_score !== null,
    filters.max_age_days !== null,
    filters.include_duplicates,
  ].filter(Boolean).length;
}

/** Split plain description text into paragraphs; single line breaks are kept inside each. */
export function paragraphs(text: string): string[] {
  return text
    .replace(/\r\n?/g, "\n")
    .split(/\n\s*\n/)
    .map((part) => part.trim())
    .filter(Boolean);
}
