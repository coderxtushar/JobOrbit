"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";

import { PageHeader, SectionHeading } from "@/components/shared/page-header";
import { errorMessage } from "@/components/shared/query-state";
import { Surface } from "@/components/shared/surface";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/endpoints";
import type { Schemas } from "@/lib/api/client";
import { cn } from "@/lib/utils";

import { BatchForm } from "./batch-form";
import { BatchPreviewPanel } from "./batch-preview";
import { BatchRunDetailView, BatchRunList } from "./batch-runs";
import {
  ACTIVE_STATUSES,
  BATCH_DEFAULTS,
  batchFormSchema,
  selectionKey,
  toBatchRequest,
  type BatchFormValues,
} from "./batch-utils";

function Step({ n, title, description, children, className }: {
  n: number;
  title: string;
  description: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Surface className={cn("p-5", className)}>
      <div className="mb-5 flex items-start gap-3">
        <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-violet-soft font-heading text-[13px] font-semibold text-violet ring-1 ring-inset ring-violet/25">
          {n}
        </span>
        <div>
          <h2 className="font-heading text-[15px] font-semibold tracking-tight text-text-1">{title}</h2>
          <p className="mt-0.5 text-xs text-text-3">{description}</p>
        </div>
      </div>
      {children}
    </Surface>
  );
}

/** /bulk: select → preview (backend count) → run, then follow each run item by item. */
export function BulkView() {
  const client = useQueryClient();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const form = useForm<BatchFormValues>({
    resolver: zodResolver(batchFormSchema),
    defaultValues: BATCH_DEFAULTS,
    mode: "onChange",
  });
  const values = useWatch({ control: form.control }) as BatchFormValues;
  const parsed = batchFormSchema.safeParse(values);
  const currentKey = parsed.success ? selectionKey(toBatchRequest(parsed.data)) : null;

  const [preview, setPreview] = useState<{ key: string; data: Schemas["BatchPreview"] } | null>(null);
  const previewMutation = useMutation({
    mutationFn: (request: Schemas["BatchStartRequest"]) => api.previewBatch(request),
    onSuccess: (data, request) => setPreview({ key: selectionKey(request), data }),
  });

  const runs = useQuery({ queryKey: ["batches"], queryFn: () => api.batches(20, 0) });
  const urlRun = Number(searchParams.get("run"));
  const runId = Number.isInteger(urlRun) && urlRun > 0 ? urlRun : (runs.data?.items[0]?.id ?? null);
  const running = runs.data?.items.find((run) => ACTIVE_STATUSES.has(run.status));

  const selectRun = (id: number) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("run", String(id));
    router.replace(`${pathname}?${params}`, { scroll: false });
  };

  const start = useMutation({
    mutationFn: (request: Schemas["BatchStartRequest"]) => api.startBatch(request),
    onSuccess: (detail) => {
      client.setQueryData(["batch", detail.id], detail);
      void client.invalidateQueries({ queryKey: ["batches"] });
      setPreview(null);
      selectRun(detail.id);
      toast.success(`Run #${detail.id} started`, {
        description: `${detail.total_items} job${detail.total_items === 1 ? "" : "s"} queued for preparation. Nothing will be submitted.`,
      });
      document.getElementById("batch-runs")?.scrollIntoView({ behavior: "smooth", block: "start" });
    },
    onError: (error) => toast.error("Could not start the run", { description: errorMessage(error) }),
  });

  const onPreview = form.handleSubmit((data) => previewMutation.mutate(toBatchRequest(data)));
  const onStart = form.handleSubmit((data) => {
    const request = toBatchRequest(data);
    if (selectionKey(request) !== preview?.key) return;
    start.mutate(request);
  });

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Automate"
        title="Bulk preparation"
        description="Prepare many applications in one run: a resume variant, a cover letter and an answer set for each job."
      />

      <div className="flex items-start gap-3 rounded-xl border border-success/25 bg-success-soft px-4 py-3">
        <ShieldCheck className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />
        <p className="text-[13px] leading-relaxed text-text-1">
          Bulk preparation never submits anything. Each job ends in the{" "}
          <span className="font-medium">review queue</span>, or in the{" "}
          <span className="font-medium">action inbox</span> when a question needs your answer.
        </p>
      </div>

      {running ? (
        <p className="rounded-lg border border-cyan/25 bg-cyan-soft px-3 py-2 text-xs text-text-1">
          Run #{running.id} is still in progress. A new run can start once it finishes or is cancelled.
        </p>
      ) : null}

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <Step n={1} title="Choose the jobs" description="Filters the batch API supports, with its own limits.">
          <BatchForm form={form} onPreview={onPreview} previewing={previewMutation.isPending} />
        </Step>
        <Step
          n={2}
          title="Check the preview"
          description="The real count from the backend, before anything runs."
          className="xl:sticky xl:top-[calc(var(--topbar-height)+1rem)]"
        >
          <BatchPreviewPanel
            preview={preview?.data ?? null}
            stale={preview !== null && preview.key !== currentKey}
            error={previewMutation.error}
            limit={parsed.success ? parsed.data.limit : BATCH_DEFAULTS.limit}
            dryRun={Boolean(values.dry_run)}
            onStart={onStart}
            starting={start.isPending}
          />
        </Step>
      </div>

      <section id="batch-runs" className="scroll-mt-20 space-y-3">
        <SectionHeading
          title="Runs"
          description="Progress refreshes on its own while a run is going. Finished items are kept even if you cancel."
        />
        <div className="grid items-start gap-5 lg:grid-cols-[17rem_minmax(0,1fr)]">
          <BatchRunList activeId={runId} onSelect={selectRun} />
          <Surface className="min-h-64 p-5">
            {runId !== null ? (
              <BatchRunDetailView key={runId} runId={runId} />
            ) : runs.isLoading ? (
              <Skeleton className="h-48 w-full" />
            ) : (
              <p className="py-16 text-center text-sm text-text-3">Start a run to follow it here, item by item.</p>
            )}
          </Surface>
        </div>
      </section>
    </div>
  );
}

export function BulkViewSkeleton() {
  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-4 w-96 max-w-full" />
      </div>
      <Skeleton className="h-12 w-full rounded-xl" />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <Skeleton className="h-[36rem] rounded-xl" />
        <Skeleton className="h-72 rounded-xl" />
      </div>
    </div>
  );
}
