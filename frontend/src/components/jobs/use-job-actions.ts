"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { toast } from "sonner";

import { errorMessage } from "@/components/shared/query-state";
import { api } from "@/lib/api/endpoints";
import type { Schemas } from "@/lib/api/client";

/** Everything that changes after a job action: lists, the job itself, its explanation. */
function useInvalidateJobs() {
  const client = useQueryClient();
  return useCallback(
    (jobId?: number) => {
      void client.invalidateQueries({ queryKey: ["jobs"] });
      if (jobId !== undefined) void client.invalidateQueries({ queryKey: ["job", jobId] });
    },
    [client],
  );
}

export function useSaveJob() {
  const invalidate = useInvalidateJobs();
  return useMutation({
    mutationFn: (jobId: number) => api.shortlistJob(jobId),
    onSuccess: (result, jobId) => {
      toast.success("Saved", { description: result.message || undefined });
      invalidate(jobId);
    },
    onError: (error) => toast.error("Could not save this job", { description: errorMessage(error) }),
  });
}

export function useSkipJob() {
  const invalidate = useInvalidateJobs();
  return useMutation({
    mutationFn: ({ jobId, reason }: { jobId: number; reason: string }) => api.skipJob(jobId, reason),
    onSuccess: (result, { jobId }) => {
      toast.success("Skipped", { description: result.message || undefined });
      invalidate(jobId);
    },
    onError: (error) => toast.error("Could not skip this job", { description: errorMessage(error) }),
  });
}

/** Save several jobs, one request each, and report what actually happened. */
export function useSaveMany() {
  const invalidate = useInvalidateJobs();
  const [running, setRunning] = useState(false);
  const run = useCallback(
    async (jobIds: number[]) => {
      if (!jobIds.length) return;
      setRunning(true);
      let saved = 0;
      const failures: string[] = [];
      for (const id of jobIds) {
        try {
          await api.shortlistJob(id);
          saved += 1;
        } catch (error) {
          failures.push(`#${id}: ${errorMessage(error)}`);
        }
      }
      setRunning(false);
      invalidate();
      if (failures.length === 0) toast.success(`Saved ${saved} job${saved === 1 ? "" : "s"}`);
      else
        toast.warning(`Saved ${saved} of ${jobIds.length}`, {
          description: failures.slice(0, 3).join(" · "),
        });
    },
    [invalidate],
  );
  return { run, running };
}

function describePrepared(app: Schemas["ApplicationDetail"]): "ready" | "needs_action" {
  return (app.blocking_questions?.length ?? 0) > 0 ? "needs_action" : "ready";
}

/** Prepare one application. Preparation stops at review: nothing is ever submitted here. */
export function usePrepareJob() {
  const invalidate = useInvalidateJobs();
  const router = useRouter();
  return useMutation({
    mutationFn: (jobId: number) => api.prepareApplication({ job_id: jobId, include_cover_letter: true }),
    onSuccess: (app, jobId) => {
      invalidate(jobId);
      if (describePrepared(app) === "needs_action") {
        const count = app.blocking_questions?.length ?? 0;
        toast.warning(`Prepared, with ${count} question${count === 1 ? "" : "s"} to answer`, {
          description: "Nothing was submitted. Answer them in the action inbox before review.",
          action: { label: "Action inbox", onClick: () => router.push("/action-inbox") },
        });
      } else {
        toast.success("Prepared for review", {
          description: "Nothing was submitted. Check it in the review queue.",
          action: { label: "Review queue", onClick: () => router.push("/review-queue") },
        });
      }
    },
    onError: (error) => toast.error("Preparation failed", { description: errorMessage(error) }),
  });
}

/** Prepare several applications in sequence, with a live progress toast. */
export function usePrepareMany() {
  const invalidate = useInvalidateJobs();
  const router = useRouter();
  const [running, setRunning] = useState(false);
  const run = useCallback(
    async (jobIds: number[]) => {
      if (!jobIds.length) return;
      setRunning(true);
      const toastId = toast.loading(`Preparing 0 of ${jobIds.length}…`, {
        description: "Preparation only drafts the application. Nothing is submitted.",
      });
      let ready = 0;
      let needsAction = 0;
      const failures: string[] = [];
      for (const [index, id] of jobIds.entries()) {
        toast.loading(`Preparing ${index + 1} of ${jobIds.length}…`, {
          id: toastId,
          description: "Preparation only drafts the application. Nothing is submitted.",
        });
        try {
          const app = await api.prepareApplication({ job_id: id, include_cover_letter: true });
          if (describePrepared(app) === "ready") ready += 1;
          else needsAction += 1;
        } catch (error) {
          failures.push(`#${id}: ${errorMessage(error)}`);
        }
      }
      setRunning(false);
      invalidate();
      const parts = [
        `${ready} ready for review`,
        needsAction ? `${needsAction} need answers` : null,
        failures.length ? `${failures.length} failed` : null,
      ].filter(Boolean);
      const options = {
        id: toastId,
        description: [parts.join(" · "), "Nothing was submitted.", ...failures.slice(0, 2)].join(" "),
        action: needsAction
          ? { label: "Action inbox", onClick: () => router.push("/action-inbox") }
          : { label: "Review queue", onClick: () => router.push("/review-queue") },
      };
      if (failures.length === jobIds.length) toast.error("Preparation failed", options);
      else if (failures.length || needsAction) toast.warning(`Prepared ${ready + needsAction} of ${jobIds.length}`, options);
      else toast.success(`Prepared ${ready} application${ready === 1 ? "" : "s"}`, options);
    },
    [invalidate, router],
  );
  return { run, running };
}

export function useScoreJobs() {
  const invalidate = useInvalidateJobs();
  const mutation = useMutation({
    mutationFn: (body: Schemas["ScoreRequest"]) => api.scoreJobs(body),
    onSuccess: (summary, body) => {
      invalidate(body.job_ids?.length === 1 ? body.job_ids[0] : undefined);
      const description = [
        `${summary.high} strong · ${summary.review} worth a look · ${summary.low} weak · ${summary.filtered_out} filtered out`,
        summary.remaining ? `${summary.remaining} still unscored.` : null,
        summary.failures?.length ? `${summary.failures.length} failed: ${summary.failures[0]}` : null,
        `Scorer: ${summary.scorer}.`,
      ]
        .filter(Boolean)
        .join(" ");
      const title =
        summary.scored === 0 ? "Nothing new to score" : `Scored ${summary.scored} job${summary.scored === 1 ? "" : "s"}`;
      const options = {
        description,
        action:
          summary.remaining > 0
            ? { label: "Score more", onClick: () => mutation.mutate({ rescore_all: false, offset: 0 }) }
            : undefined,
      };
      if (summary.failures?.length) toast.warning(title, options);
      else toast.success(title, options);
    },
    onError: (error) => toast.error("Scoring failed", { description: errorMessage(error) }),
  });
  return mutation;
}

export function useDiscoverJobs() {
  const invalidate = useInvalidateJobs();
  return useMutation({
    mutationFn: () => api.discoverJobs({ trigger: "manual" }),
    onSuccess: (summaries) => {
      invalidate();
      const created = summaries.reduce((sum, item) => sum + item.jobs_created, 0);
      const updated = summaries.reduce((sum, item) => sum + item.jobs_updated, 0);
      const errored = summaries.filter((item) => (item.errors?.length ?? 0) > 0).length;
      const description = `${created} new · ${updated} updated across ${summaries.length} source${
        summaries.length === 1 ? "" : "s"
      }${errored ? ` · ${errored} reported errors` : ""}.`;
      if (errored) toast.warning("Discovery finished with errors", { description });
      else toast.success("Discovery finished", { description });
    },
    onError: (error) => toast.error("Discovery failed", { description: errorMessage(error) }),
  });
}
