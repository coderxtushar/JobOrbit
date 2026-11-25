"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Building2,
  ClipboardList,
  FileText,
  Info,
  Loader2,
  Mic,
  RefreshCw,
  Sparkles,
  Wand2,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { ErrorState, errorMessage } from "@/components/shared/query-state";
import { StateBadge, StatusBadge } from "@/components/shared/status-badge";
import { Surface } from "@/components/shared/surface";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { Schemas } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { APPLICATION_STATUS, OUTCOME } from "@/lib/constants/states";
import { formatDateTime, formatRelative, humanize } from "@/lib/formatting";

import { ApplicationPicker, sortForPrep } from "./application-picker";
import { InterviewRounds } from "./interview-rounds";
import { MockInterview } from "./mock-interview";
import { PrepSections } from "./prep-sections";
import { isNotGenerated, type PracticeEntry, type PrepContent, type PrepItem } from "./research-types";

type Application = Schemas["ApplicationRead"];

function parseId(value: string | null): number | null {
  if (!value) return null;
  const id = Number(value);
  return Number.isInteger(id) && id > 0 ? id : null;
}

export function InterviewPrepView() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const applicationId = parseId(params.get("application"));

  const applications = useQuery({
    queryKey: ["applications", "prep-picker"],
    queryFn: () => api.applications({ limit: 200 }),
  });

  const pick = (id: number | null) => {
    router.replace(id ? `${pathname}?application=${id}` : pathname, { scroll: false });
  };

  const items = applications.data?.items ?? [];
  const selected = items.find((item) => item.id === applicationId) ?? null;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Research"
        title="Interview prep"
        description="Preparation built by fixed rules from the listing, your profile and the cited company profile. Every item says what it was derived from; nothing claims experience you have not recorded."
        actions={
          <div className="flex w-full items-center gap-2 sm:w-auto">
            <ApplicationPicker
              applications={items}
              selectedId={applicationId}
              onPick={pick}
              loading={applications.isPending}
            />
            {applicationId ? (
              <Button variant="ghost" size="icon" onClick={() => pick(null)} aria-label="Clear selection">
                <X />
              </Button>
            ) : null}
          </div>
        }
      />

      {applications.isError && !applicationId ? (
        <ErrorState error={applications.error} onRetry={() => applications.refetch()} />
      ) : !applicationId ? (
        <PickApplication applications={items} loading={applications.isPending} onPick={pick} />
      ) : (
        <PrepWorkspace key={applicationId} applicationId={applicationId} application={selected} />
      )}
    </div>
  );
}

function PickApplication({
  applications,
  loading,
  onPick,
}: {
  applications: Application[];
  loading: boolean;
  onPick: (id: number) => void;
}) {
  const { interviewing, others } = sortForPrep(applications);
  const list = [...interviewing, ...others].slice(0, 12);
  if (loading) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton key={index} className="h-24 rounded-xl" />
        ))}
      </div>
    );
  }
  if (!applications.length) {
    return (
      <EmptyState
        icon={FileText}
        title="No applications yet"
        description="Interview prep is built per application. Prepare an application from a job first."
        action={
          <Button asChild size="sm" variant="outline">
            <Link href="/jobs">Browse jobs</Link>
          </Button>
        }
      />
    );
  }
  return (
    <div className="space-y-3">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-text-3">
        {interviewing.length ? "In interviews first" : "Pick an application"}
      </p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {list.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => onPick(item.id)}
            className="orbit-card group flex flex-col gap-2 p-4 text-left transition-[border-color,box-shadow,transform] duration-200 hover:-translate-y-px hover:border-line-strong hover:shadow-raised"
          >
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium text-text-1 group-hover:text-violet">
                {item.job_title || "Untitled role"}
              </span>
              <span className="block truncate text-xs text-text-3">{item.job_company || "Company not stated"}</span>
            </span>
            <span className="flex flex-wrap gap-1.5">
              <StateBadge value={item.status} map={APPLICATION_STATUS} />
              <StateBadge value={item.outcome} map={OUTCOME} />
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function PrepWorkspace({ applicationId, application }: { applicationId: number; application: Application | null }) {
  const client = useQueryClient();
  const [tab, setTab] = useState("prep");
  const [target, setTarget] = useState<PrepItem | null>(null);

  // The picker list can be capped; fall back to the application itself for the header.
  const detail = useQuery({
    queryKey: ["applications", "detail", applicationId],
    queryFn: () => api.application(applicationId),
    enabled: application === null,
  });
  const app: Application | null = application ?? (detail.data as Application | undefined) ?? null;

  const prep = useQuery({
    queryKey: ["interview-prep", applicationId],
    queryFn: () => api.interviewPrep(applicationId),
    retry: (count, error) => !isNotGenerated(error) && count < 2,
  });

  const generate = useMutation({
    mutationFn: (regenerate: boolean) => api.generateInterviewPrep(applicationId, regenerate),
    onSuccess: (data, regenerate) => {
      client.setQueryData(["interview-prep", applicationId], data);
      toast.success(regenerate ? "Preparation rebuilt" : "Preparation generated", {
        description: regenerate ? "Your practice history was kept." : "Built by rules from the listing and your profile.",
      });
    },
    onError: (error) => toast.error("Preparation was not generated", { description: errorMessage(error) }),
  });

  const content = (prep.data?.content ?? null) as unknown as PrepContent | null;
  const practice = useMemo(() => (prep.data?.practice ?? []) as unknown as PracticeEntry[], [prep.data]);
  const practiceCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const entry of practice) counts.set(entry.question_id, (counts.get(entry.question_id) ?? 0) + 1);
    return counts;
  }, [practice]);

  const rounds = useQuery({
    queryKey: ["interview-rounds", applicationId],
    queryFn: () => api.interviewRounds(applicationId),
  });

  const practise = (item: PrepItem) => {
    setTarget({ ...item, times_practised: practiceCounts.get(item.id) ?? 0 });
    setTab("practice");
  };

  const title = content?.job?.title || app?.job_title || `Application #${applicationId}`;
  const company = content?.job?.company || app?.job_company || "";
  const jobId = content?.job?.id ?? app?.job_id;

  return (
    <div className="space-y-5">
      <Surface className="relative overflow-hidden p-5">
        <div className="pointer-events-none absolute -top-20 -right-16 size-56 rounded-full bg-violet-soft blur-3xl" aria-hidden />
        <div className="relative flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0 space-y-1.5">
            <h2 className="truncate font-heading text-xl font-semibold tracking-tight text-text-1">{title}</h2>
            <p className="text-sm text-text-2">{company || <span className="italic text-text-3">Company not stated</span>}</p>
            <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
              {app ? <StateBadge value={app.status} map={APPLICATION_STATUS} /> : null}
              {app ? <StateBadge value={app.outcome} map={OUTCOME} /> : null}
              {prep.data?.interview_stage ? <StatusBadge tone="violet">Interview stage</StatusBadge> : null}
              {content?.job?.family ? (
                <span className="text-[11px] text-text-3">job family: {humanize(content.job.family)}</span>
              ) : null}
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            {jobId ? (
              <Button asChild size="sm" variant="outline">
                <Link href={`/company-research?job=${jobId}`}>
                  <Building2 /> Company research
                </Link>
              </Button>
            ) : null}
            {prep.data ? (
              <Button size="sm" variant="secondary" onClick={() => generate.mutate(true)} disabled={generate.isPending}>
                {generate.isPending ? <Loader2 className="animate-spin" /> : <RefreshCw />}
                Regenerate
              </Button>
            ) : null}
          </div>
        </div>
      </Surface>

      {prep.isPending ? (
        <PrepSkeleton />
      ) : prep.isError && isNotGenerated(prep.error) ? (
        <Surface className="relative overflow-hidden">
          <EmptyState
            icon={Wand2}
            title="No preparation for this application yet"
            description="Generating builds questions from this listing's skills and responsibilities, your profile, resume and projects, and the cited company profile. It uses fixed rules, not an AI model, and takes a moment."
            className="border-0"
            action={
              <Button onClick={() => generate.mutate(false)} disabled={generate.isPending} className="shadow-glow">
                {generate.isPending ? <Loader2 className="animate-spin" /> : <Sparkles />}
                Generate preparation
              </Button>
            }
          />
        </Surface>
      ) : prep.isError ? (
        <ErrorState error={prep.error} onRetry={() => prep.refetch()} />
      ) : (
        <Tabs value={tab} onValueChange={setTab} className="gap-4">
          <TabsList variant="line" className="h-9 w-full justify-start gap-4 border-b border-line">
            <TabsTrigger value="prep" className="flex-none px-1">
              <Sparkles /> Preparation
            </TabsTrigger>
            <TabsTrigger value="practice" className="flex-none px-1">
              <Mic /> Mock interview
              {practice.length ? (
                <span className="tabular rounded-full bg-surface-3 px-1.5 text-[10.5px] text-text-2">{practice.length}</span>
              ) : null}
            </TabsTrigger>
            <TabsTrigger value="rounds" className="flex-none px-1">
              <ClipboardList /> Interview rounds
              {rounds.data?.length ? (
                <span className="tabular rounded-full bg-surface-3 px-1.5 text-[10.5px] text-text-2">{rounds.data.length}</span>
              ) : null}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="prep" className="space-y-4">
            <div className="flex flex-col gap-3 rounded-xl border border-violet/20 bg-violet-soft/40 p-4 sm:flex-row sm:items-start sm:justify-between">
              <div className="space-y-1.5">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge tone="violet">Generated · rule-based</StatusBadge>
                  <span className="text-[11px] text-text-3" title={formatDateTime(prep.data.generated_at)}>
                    built {formatRelative(prep.data.generated_at)}
                  </span>
                </div>
                {(content?.notes ?? []).map((note) => (
                  <p key={note} className="flex gap-1.5 text-xs leading-relaxed text-text-2">
                    <Info className="mt-0.5 size-3 shrink-0 text-violet" /> {note}
                  </p>
                ))}
              </div>
              {content?.job?.required_skills?.length || content?.job?.preferred_skills?.length ? (
                <div className="max-w-sm space-y-1 sm:text-right">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-text-3">Skills in the listing</p>
                  <p className="text-xs text-text-1">{(content.job.required_skills ?? []).join(", ") || "none required"}</p>
                  {content.job.preferred_skills?.length ? (
                    <p className="text-xs text-text-3">preferred: {content.job.preferred_skills.join(", ")}</p>
                  ) : null}
                </div>
              ) : null}
            </div>
            {content ? (
              <PrepSections content={content} practiceCounts={practiceCounts} onPractise={practise} />
            ) : null}
          </TabsContent>

          <TabsContent value="practice" forceMount className="data-[state=inactive]:hidden">
            <MockInterview
              key={target?.id ?? "auto"}
              applicationId={applicationId}
              initialQuestion={target ?? ((prep.data.next_question ?? null) as unknown as PrepItem | null)}
              practice={practice}
            />
          </TabsContent>

          <TabsContent value="rounds">
            <InterviewRounds applicationId={applicationId} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}

function PrepSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Loading interview preparation">
      <Skeleton className="h-9 w-80" />
      <Skeleton className="h-20 w-full rounded-xl" />
      <div className="orbit-card space-y-1 p-3">
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton key={index} className="h-12 w-full" />
        ))}
      </div>
    </div>
  );
}

export function InterviewPrepFallback() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-4 w-full max-w-xl" />
      </div>
      <PrepSkeleton />
    </div>
  );
}
