/**
 * Labels and tones for every backend state. One place, so "outcome_unknown" reads the same
 * on every page and a prepared application is never styled like a submitted one.
 */
export type Tone = "neutral" | "violet" | "cyan" | "success" | "warning" | "danger";

export const APPLICATION_STATUS: Record<string, { label: string; tone: Tone }> = {
  DISCOVERED: { label: "Discovered", tone: "neutral" },
  SCORED: { label: "Scored", tone: "neutral" },
  SHORTLISTED: { label: "Shortlisted", tone: "cyan" },
  READY_FOR_REVIEW: { label: "Ready for review", tone: "violet" },
  APPROVED: { label: "Approved", tone: "violet" },
  SUBMITTED: { label: "Submitted", tone: "success" },
  CONFIRMED: { label: "Confirmed", tone: "success" },
  SKIPPED: { label: "Skipped", tone: "neutral" },
  FAILED: { label: "Failed", tone: "danger" },
  SUBMISSION_UNKNOWN: { label: "Outcome unknown", tone: "warning" },
};

export const OUTCOME: Record<string, { label: string; tone: Tone }> = {
  pending: { label: "Pending", tone: "neutral" },
  no_response: { label: "No response", tone: "neutral" },
  rejected: { label: "Rejected", tone: "danger" },
  screening: { label: "Screening", tone: "cyan" },
  interviewing: { label: "Interviewing", tone: "violet" },
  offer: { label: "Offer", tone: "success" },
  withdrawn: { label: "Withdrawn", tone: "neutral" },
  accepted: { label: "Accepted", tone: "success" },
};

export const ATTEMPT_STATE: Record<string, { label: string; tone: Tone }> = {
  discovered: { label: "Discovered", tone: "neutral" },
  eligible: { label: "Queued", tone: "neutral" },
  prepared: { label: "Prepared", tone: "violet" },
  ready_to_submit: { label: "Ready to submit", tone: "violet" },
  submission_in_progress: { label: "Submitting", tone: "cyan" },
  submitted_confirmed: { label: "Submitted · confirmed", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
  blocked_missing_info: { label: "Needs an answer", tone: "warning" },
  requires_user_action: { label: "Needs you", tone: "warning" },
  unsupported_platform: { label: "Platform permits none", tone: "neutral" },
  outcome_unknown: { label: "Outcome unknown", tone: "warning" },
};

export const RUN_STATUS: Record<string, { label: string; tone: Tone }> = {
  pending: { label: "Pending", tone: "neutral" },
  running: { label: "Running", tone: "cyan" },
  paused: { label: "Paused", tone: "neutral" },
  cancelling: { label: "Stopping", tone: "warning" },
  cancelled: { label: "Cancelled", tone: "neutral" },
  completed: { label: "Completed", tone: "success" },
  completed_with_errors: { label: "Completed with errors", tone: "warning" },
  failed: { label: "Failed", tone: "danger" },
  interrupted: { label: "Interrupted", tone: "warning" },
};

export const PLAN_STATUS: Record<string, { label: string; tone: Tone }> = {
  ready: { label: "Ready", tone: "success" },
  needs_answers: { label: "Needs answers", tone: "warning" },
  unsupported: { label: "Platform permits none", tone: "neutral" },
  blocked: { label: "Blocked", tone: "danger" },
  ineligible: { label: "Ineligible", tone: "danger" },
  below_threshold: { label: "Below threshold", tone: "neutral" },
  stale: { label: "Stale", tone: "neutral" },
  applied: { label: "Already applied", tone: "neutral" },
  duplicate: { label: "Duplicate", tone: "neutral" },
};

export const JOB_STATUS: Record<string, { label: string; tone: Tone }> = {
  DISCOVERED: { label: "New", tone: "cyan" },
  SCORED: { label: "Scored", tone: "neutral" },
  SHORTLISTED: { label: "Saved", tone: "violet" },
  SKIPPED: { label: "Skipped", tone: "neutral" },
  FILTERED_OUT: { label: "Filtered out", tone: "danger" },
  EXPIRED: { label: "Expired", tone: "neutral" },
  DUPLICATE: { label: "Duplicate", tone: "neutral" },
};

export const BAND: Record<string, { label: string; tone: Tone }> = {
  high: { label: "Strong match", tone: "success" },
  review: { label: "Worth a look", tone: "violet" },
  low: { label: "Weak match", tone: "neutral" },
};
