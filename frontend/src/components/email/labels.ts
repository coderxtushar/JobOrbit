import type { Tone } from "@/lib/constants/states";

/** Email categories as the classifier names them, with what each one would suggest. */
export const EMAIL_CATEGORY: Record<string, { label: string; tone: Tone; suggests: string }> = {
  application_confirmation: {
    label: "Application confirmation",
    tone: "success",
    suggests: "status → Confirmed",
  },
  rejection: { label: "Rejection", tone: "danger", suggests: "outcome → Rejected" },
  interview_invitation: { label: "Interview invitation", tone: "violet", suggests: "outcome → Interviewing" },
  assessment_invitation: { label: "Assessment invitation", tone: "cyan", suggests: "outcome → Screening" },
  offer: { label: "Offer", tone: "success", suggests: "outcome → Offer" },
  recruiter_message: { label: "Recruiter message", tone: "neutral", suggests: "nothing; shown for reference" },
  process_update: { label: "Process update", tone: "neutral", suggests: "nothing; shown for reference" },
  other_job_related: { label: "Other job-related", tone: "neutral", suggests: "nothing; shown for reference" },
  not_job_related: { label: "Not job-related", tone: "neutral", suggests: "not kept" },
};

export const INGEST_OUTCOME: Record<string, { label: string; tone: Tone; detail: string }> = {
  created: { label: "Stored", tone: "success", detail: "The email was classified and stored." },
  duplicate: { label: "Already stored", tone: "neutral", detail: "This exact message was processed before." },
  skipped_not_job_related: {
    label: "Not job-related",
    tone: "neutral",
    detail: "It does not look like a reply to an application, so nothing was kept.",
  },
};

export const MATCH_STATE: Record<string, { label: string; tone: Tone }> = {
  auto_linked: { label: "Linked automatically", tone: "success" },
  user_linked: { label: "Linked by you", tone: "success" },
  needs_review: { label: "Needs your pick", tone: "warning" },
  unmatched: { label: "No matching application", tone: "neutral" },
  dismissed: { label: "Dismissed", tone: "neutral" },
};

export function categoryLabel(category: string): { label: string; tone: Tone; suggests: string } {
  return (
    EMAIL_CATEGORY[category] ?? {
      label: category.replace(/_/g, " "),
      tone: "neutral",
      suggests: "",
    }
  );
}

export function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

/** "status" / "outcome" → a readable field name. */
export function fieldLabel(field: string): string {
  if (field === "status") return "Status";
  if (field === "outcome") return "Outcome";
  return field.replace(/_/g, " ");
}
