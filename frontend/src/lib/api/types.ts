/** Response shapes the backend returns as untyped dicts, written out by hand. */

export interface Health {
  status: string;
  version: string;
  database: string;
  database_dialect: string;
  llm_provider: string;
  llm_enabled: boolean;
  scheduler_enabled: boolean;
  loopback_only: boolean;
  demo_mode?: boolean;
  automated_submission_supported?: boolean;
}

export interface RateValue {
  value: number | null;
  numerator: number;
  denominator: number;
  note: string;
}

export interface Segment {
  discovered: number;
  sent: number;
  interviews: number;
  rejections: number;
  offers: number;
  interview_rate: number | null;
  interview_rate_note: string;
}

/** GET /api/metrics/outcomes: only recorded data; rates need a minimum denominator. */
export interface OutcomeReport {
  funnel: {
    jobs_discovered: number;
    eligible_jobs: number;
    applications_prepared: number;
    submission_attempts: number;
    confirmed_submissions: number;
    applications_confirmed: number;
    applications_marked_submitted: number;
    unknown_outcomes: number;
    failed_submissions: number;
    failed_before_submit: number;
    waiting_on_you: number;
    interviews: number;
    rejections: number;
    offers: number;
  };
  rates: Record<"interview_rate" | "rejection_rate" | "offer_rate" | "confirmation_rate", RateValue>;
  time_saved: {
    estimate_minutes: number;
    confirmed_auto_submissions: number;
    assumption: string;
    is_estimate: boolean;
  };
  by_source: Record<string, Segment>;
  by_job_family: Record<string, Segment>;
  by_employer: Record<string, Segment>;
  by_score_band: Record<string, Segment>;
  failure_reasons: Record<string, number>;
  duplicate_rate: number | null;
  freshness: {
    median_hours_posted_to_sent: number | null;
    measured: number;
    undated_postings: number;
  };
  weekly: Record<string, Record<string, number>>;
  monthly: Record<string, Record<string, number>>;
  missing: Record<string, number>;
  notes: string[];
  min_denominator: number;
}

export interface ArtifactVersion {
  id: number;
  kind: string;
  label: string;
  content_sha256: string;
  byte_size: number;
  created_at: string;
  locked: boolean;
  locked_at: string | null;
  preview: string;
}

/** Rows of /api/audit-logs and /api/import-runs are free-form dicts. */
export type LooseRecord = Record<string, unknown>;
