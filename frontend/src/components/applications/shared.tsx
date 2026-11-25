"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { toast } from "sonner";

import { errorMessage } from "@/components/shared/query-state";
import { Button } from "@/components/ui/button";
import type { Schemas } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import type { Tone } from "@/lib/constants/states";

export type Application = Schemas["ApplicationRead"];
export type ApplicationDetail = Schemas["ApplicationDetail"];
export type ApplicationStatus = Schemas["ApplicationStatus"];
export type Outcome = Schemas["Outcome"];

export const STATUSES: ApplicationStatus[] = [
  "DISCOVERED",
  "SCORED",
  "SHORTLISTED",
  "READY_FOR_REVIEW",
  "APPROVED",
  "SUBMITTED",
  "SUBMISSION_UNKNOWN",
  "CONFIRMED",
  "SKIPPED",
  "FAILED",
];

export const OUTCOMES: Outcome[] = [
  "pending",
  "no_response",
  "screening",
  "interviewing",
  "offer",
  "accepted",
  "rejected",
  "withdrawn",
];

/**
 * Mirror of ALLOWED_TRANSITIONS in app/services/tracking.py, used only to offer sensible
 * choices. The backend validates every change and its message is shown when it refuses.
 */
export const NEXT_STATUSES: Record<ApplicationStatus, ApplicationStatus[]> = {
  DISCOVERED: ["SCORED", "SHORTLISTED", "SKIPPED"],
  SCORED: ["SHORTLISTED", "SKIPPED"],
  SHORTLISTED: ["READY_FOR_REVIEW", "SKIPPED", "FAILED"],
  READY_FOR_REVIEW: ["APPROVED", "SHORTLISTED", "SKIPPED", "FAILED"],
  APPROVED: ["SUBMITTED", "SUBMISSION_UNKNOWN", "READY_FOR_REVIEW", "SKIPPED", "FAILED"],
  SUBMITTED: ["CONFIRMED", "SUBMISSION_UNKNOWN", "FAILED"],
  SUBMISSION_UNKNOWN: ["CONFIRMED", "SUBMITTED", "FAILED", "SKIPPED"],
  CONFIRMED: [],
  SKIPPED: ["SHORTLISTED"],
  FAILED: ["SHORTLISTED", "READY_FOR_REVIEW", "SKIPPED"],
};

export const PROVENANCE: Record<string, { label: string; tone: Tone }> = {
  profile_verified: { label: "From profile", tone: "success" },
  resume_extracted: { label: "From resume", tone: "cyan" },
  ai_draft: { label: "AI draft", tone: "violet" },
  user_entered: { label: "You entered", tone: "neutral" },
  needs_user_input: { label: "Needs you", tone: "warning" },
};

/** Invalidate everything an application change can affect. */
export function useInvalidateApplications() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: ["applications"] });
    void queryClient.invalidateQueries({ queryKey: ["nav"] });
  };
}

/**
 * Opens the employer's own page and records that it was opened. A real link (so the
 * browser treats it as a user-initiated navigation and never blocks it as a popup); the
 * record call is fired on the same click. Opening a page is not submitting: the status is
 * left as it is.
 */
export function OpenEmployerButton({
  application,
  size = "sm",
  variant = "outline",
}: {
  application: Pick<Application, "id" | "job_url">;
  size?: "sm" | "default";
  variant?: "outline" | "default" | "ghost";
}) {
  const invalidate = useInvalidateApplications();
  const record = useMutation({
    mutationFn: () => api.recordOpened(application.id),
    onSuccess: invalidate,
    onError: (error) => toast.error("Could not record that the page was opened", { description: errorMessage(error) }),
  });
  if (!application.job_url) {
    return (
      <Button size={size} variant={variant} disabled title="The listing has no URL">
        Open employer page <ExternalLink />
      </Button>
    );
  }
  return (
    <Button asChild size={size} variant={variant}>
      <a href={application.job_url} target="_blank" rel="noreferrer noopener" onClick={() => record.mutate()}>
        Open employer page <ExternalLink />
      </a>
    </Button>
  );
}
