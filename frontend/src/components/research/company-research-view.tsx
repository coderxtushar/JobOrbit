"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, CalendarClock, ExternalLink, Globe, Info, Loader2, RefreshCw, ShieldAlert, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useId, useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { ErrorState } from "@/components/shared/query-state";
import { StatusBadge } from "@/components/shared/status-badge";
import { Surface } from "@/components/shared/surface";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { ApiError, type Schemas } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { formatDate, formatDateTime, formatNumber, formatRelative } from "@/lib/formatting";

import { CompanyPicker, type CompanySelection } from "./company-picker";
import { CompanyProfileSections, JobContextSection } from "./company-profile";
import type { CompanyData, JobContext } from "./research-types";
import { sourceMap } from "./research-types";
import { SalaryTool } from "./salary-tool";

type Research = Schemas["CompanyResearchRead"];

function parseJobId(value: string | null): number | null {
  if (!value) return null;
  const id = Number(value);
  return Number.isInteger(id) && id > 0 ? id : null;
}

const REFUSAL_TITLE: Record<string, string> = {
  external_research_disabled: "Website fetching is turned off",
  website_unknown: "No website is known for this company",
  unsafe_url: "That website address was refused",
  invalid_company: "That company name could not be used",
  demo_mode: "Not available in the demo",
};

export function CompanyResearchView() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const jobId = parseJobId(params.get("job"));
  const companyParam = jobId ? null : params.get("company")?.trim() || null;

  const select = (selection: CompanySelection | null) => {
    const next = new URLSearchParams();
    if (selection && "job" in selection) next.set("job", String(selection.job));
    if (selection && "company" in selection) next.set("company", selection.company);
    const query = next.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  const queryKey = jobId ? ["research", "job-company", jobId] : ["research", "company", companyParam];
  const research = useQuery({
    queryKey,
    queryFn: () => (jobId ? api.jobCompany(jobId) : api.company(companyParam as string)),
    enabled: Boolean(jobId || companyParam),
    retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
  });

  const label = research.data?.company ?? companyParam ?? (jobId ? `Job #${jobId}` : null);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Research"
        title="Company research"
        description="A profile built from the listings JobOrbit holds. Every fact shows the source it came from and when that source was read; anything no source states stays “not stated”."
        actions={
          <div className="flex w-full items-center gap-2 sm:w-auto">
            <CompanyPicker label={label} onPick={select} />
            {jobId || companyParam ? (
              <Button variant="ghost" size="icon" onClick={() => select(null)} aria-label="Clear selection">
                <X />
              </Button>
            ) : null}
          </div>
        }
      />

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-4">
          {!jobId && !companyParam ? (
            <QuickPicks onPick={select} />
          ) : research.isPending ? (
            <ResearchSkeleton />
          ) : research.isError ? (
            <ErrorState error={research.error} onRetry={() => research.refetch()} />
          ) : (
            <ResearchBody key={research.data.company_normalized} research={research.data} queryKey={queryKey} jobId={jobId} />
          )}
        </div>
        <aside className="space-y-4 xl:sticky xl:top-[calc(var(--topbar-height)+1rem)]">
          <SalaryTool key={jobId ?? "none"} jobId={jobId} />
        </aside>
      </div>
    </div>
  );
}

function ResearchBody({
  research,
  queryKey,
  jobId,
}: {
  research: Research;
  queryKey: unknown[];
  jobId: number | null;
}) {
  const data = research.data as unknown as CompanyData;
  const sources = sourceMap(research.sources as unknown[]);
  const context = (research.job_context ?? null) as unknown as JobContext | null;

  return (
    <>
      <ProfileHeader
        research={research}
        data={data}
        queryKey={queryKey}
        jobId={jobId}
        listingUrl={context?.source?.url || null}
      />
      {context ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <JobContextSection context={context} />
        </div>
      ) : null}
      <CompanyProfileSections data={data} sources={sources} />
      {data.notes?.length ? (
        <ul className="space-y-1 rounded-xl border border-dashed border-line-strong p-4">
          {data.notes.map((note) => (
            <li key={note} className="flex gap-2 text-xs text-text-3">
              <Info className="mt-0.5 size-3 shrink-0" /> {note}
            </li>
          ))}
        </ul>
      ) : null}
    </>
  );
}

function ProfileHeader({
  research,
  data,
  queryKey,
  jobId,
  listingUrl,
}: {
  research: Research;
  data: CompanyData;
  queryKey: unknown[];
  jobId: number | null;
  listingUrl: string | null;
}) {
  const id = useId();
  const client = useQueryClient();
  const [website, setWebsite] = useState(research.website ?? "");
  const [fetchWebsite, setFetchWebsite] = useState(false);

  const refresh = useMutation({
    mutationFn: () =>
      api.refreshCompany(research.company, {
        website: website.trim() || null,
        fetch_website: fetchWebsite,
      }),
    onSuccess: (result) => {
      client.setQueryData<Research>(queryKey, (previous) => ({
        ...result,
        job_context: previous?.job_context ?? result.job_context ?? null,
      }));
      client.setQueryData(["research", "company", research.company], result);
      if (jobId) void client.invalidateQueries({ queryKey: ["research", "job-company", jobId] });
      toast.success(`Rebuilt the profile of ${result.company}`, {
        description: fetchWebsite ? "The website was fetched as part of the rebuild." : "Built from the listings held.",
      });
    },
  });

  const refusal = refresh.error instanceof ApiError ? refresh.error : null;

  return (
    <Surface className="relative overflow-hidden p-5">
      <div className="pointer-events-none absolute -top-24 -right-24 size-64 rounded-full bg-violet-soft blur-3xl" aria-hidden />
      <div className="relative flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-violet-soft text-violet shadow-glow">
            <Building2 className="size-5" />
          </span>
          <div className="min-w-0 space-y-1.5">
            <h2 className="truncate font-heading text-xl font-semibold tracking-tight text-text-1">
              {data.display_name || research.company}
            </h2>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-text-2">
              <span className="flex items-center gap-1">
                <Globe className="size-3 text-text-3" />
                {research.website ? (
                  <a href={research.website} target="_blank" rel="noopener noreferrer" className="hover:text-violet hover:underline">
                    {research.website.replace(/^https?:\/\//, "")}
                  </a>
                ) : (
                  <span className="italic text-text-3">website not stated</span>
                )}
              </span>
              <span className="tabular">
                {formatNumber(data.listing_count ?? 0)} listing{data.listing_count === 1 ? "" : "s"}
              </span>
              <span className="flex items-center gap-1">
                <CalendarClock className="size-3 text-text-3" />
                seen {formatDate(data.first_seen)} – {formatDate(data.last_seen)}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
              <StatusBadge tone={research.from_cache ? "neutral" : "cyan"}>
                {research.from_cache ? "From cache" : "Freshly built"}
              </StatusBadge>
              <span className="text-[11px] text-text-3" title={formatDateTime(research.refreshed_at)}>
                Profile built {formatRelative(research.refreshed_at)}
              </span>
              {jobId ? (
                <Link
                  href={`/jobs/${jobId}`}
                  className="inline-flex items-center gap-1 text-[11px] text-text-3 hover:text-violet"
                >
                  Job details
                </Link>
              ) : null}
              {listingUrl ? (
                <a
                  href={listingUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-[11px] text-text-3 hover:text-violet"
                >
                  View listing <ExternalLink className="size-3" />
                </a>
              ) : null}
            </div>
          </div>
        </div>

        <form
          className="w-full space-y-2.5 rounded-xl border border-line bg-surface-2/50 p-3 lg:w-[20rem]"
          onSubmit={(event) => {
            event.preventDefault();
            refresh.mutate();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor={`${id}-website`} className="text-xs">
              Company website (optional)
            </Label>
            <Input
              id={`${id}-website`}
              type="url"
              inputMode="url"
              value={website}
              onChange={(event) => setWebsite(event.target.value)}
              placeholder="https://example.com"
            />
          </div>
          <div className="flex items-center justify-between gap-3">
            <Label htmlFor={`${id}-fetch`} className="text-xs font-normal text-text-2">
              Fetch its title and description
            </Label>
            <Switch id={`${id}-fetch`} checked={fetchWebsite} onCheckedChange={setFetchWebsite} />
          </div>
          <Button type="submit" size="sm" variant="secondary" className="w-full" disabled={refresh.isPending}>
            {refresh.isPending ? <Loader2 className="animate-spin" /> : <RefreshCw />}
            Rebuild profile
          </Button>
          <p className="text-[11px] leading-snug text-text-3">
            Rebuilding re-reads the listings. A website is only fetched when you switch it on and the server allows external research.
          </p>
        </form>
      </div>

      {refresh.isError ? (
        <div
          role="alert"
          className="relative mt-4 flex gap-3 rounded-lg border border-warning/30 bg-warning-soft p-3"
        >
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-warning" />
          <div className="min-w-0 space-y-0.5">
            <p className="text-sm font-medium text-text-1">
              {(refusal && REFUSAL_TITLE[refusal.code]) || "The profile was not rebuilt"}
            </p>
            <p className="text-xs leading-relaxed text-text-2">{refresh.error.message}</p>
          </div>
        </div>
      ) : null}
    </Surface>
  );
}

function QuickPicks({ onPick }: { onPick: (selection: CompanySelection) => void }) {
  const applications = useQuery({
    queryKey: ["applications", "research-quick-picks"],
    queryFn: () => api.applications({ limit: 50 }),
  });
  const seen = new Set<string>();
  const picks = (applications.data?.items ?? []).filter((item) => {
    const key = item.job_company.toLowerCase();
    if (!item.job_company || seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  return (
    <div className="space-y-4">
      <EmptyState
        icon={Building2}
        title="Pick a company to research"
        description="Search your listings above, or start from a company you have applied to. Nothing is looked up on the web unless you ask for it."
      />
      {applications.isPending ? (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-16 rounded-xl" />
          ))}
        </div>
      ) : applications.isError ? (
        <ErrorState error={applications.error} onRetry={() => applications.refetch()} />
      ) : picks.length ? (
        <div className="space-y-2">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-text-3">From your applications</p>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {picks.slice(0, 12).map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => onPick({ job: item.job_id })}
                className="orbit-card group flex items-center gap-3 p-3 text-left transition-[border-color,box-shadow,transform] duration-200 hover:-translate-y-px hover:border-line-strong hover:shadow-raised"
              >
                <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-surface-3 font-heading text-xs font-semibold text-text-1 uppercase">
                  {item.job_company.slice(0, 2)}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium text-text-1 group-hover:text-violet">
                    {item.job_company}
                  </span>
                  <span className="block truncate text-xs text-text-3">{item.job_title || "Title not stated"}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ResearchSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Loading company research">
      <Skeleton className="h-36 w-full rounded-xl" />
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-40 rounded-xl lg:col-span-2" />
        <Skeleton className="h-32 rounded-xl" />
        <Skeleton className="h-32 rounded-xl" />
        <Skeleton className="h-40 rounded-xl" />
        <Skeleton className="h-40 rounded-xl" />
      </div>
    </div>
  );
}

export function CompanyResearchFallback() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-4 w-full max-w-xl" />
      </div>
      <ResearchSkeleton />
    </div>
  );
}
