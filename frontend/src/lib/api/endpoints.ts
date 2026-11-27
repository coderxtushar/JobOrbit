/**
 * One typed function per backend endpoint. Pages call these through TanStack Query; they
 * never build URLs themselves. Types come from src/types/api.d.ts, generated from the
 * FastAPI schema by scripts/generate-api-types.sh, so a backend change shows up as a type
 * error here rather than a blank screen.
 */
import { request, type Schemas } from "./client";
import type { ArtifactVersion, Health, LooseRecord, OutcomeReport } from "./types";

type S = Schemas;
type Page<T> = { items: T[]; total: number; limit: number; offset: number };

const enc = encodeURIComponent;

export interface JobListParams {
  search?: string;
  status?: S["JobStatus"];
  source?: S["SourceName"];
  company?: string;
  min_score?: number;
  max_age_days?: number;
  include_duplicates?: boolean;
  sort_by?: "score" | "posted_at" | "discovered_at" | "company" | "title";
  descending?: boolean;
  limit?: number;
  offset?: number;
}

export const api = {
  // ---------------- system ----------------
  health: () => request<Health>("/health"),
  diagnostics: () => request<S["Diagnostics"]>("/api/diagnostics"),
  metrics: () => request<S["OperationalMetrics"]>("/api/metrics"),
  estimatedMetrics: () => request<S["EstimatedMetrics"]>("/api/metrics/estimated"),
  analytics: () => request<S["JobSearchAnalyticsRead"]>("/api/metrics/analytics"),
  outcomes: () => request<OutcomeReport>("/api/metrics/outcomes"),
  duplication: (suspectLimit = 25) =>
    request<S["DuplicationReportRead"]>("/api/metrics/duplication", {
      query: { suspect_limit: suspectLimit },
    }),
  auditLogs: (params: { action?: string; limit?: number; offset?: number } = {}) =>
    request<Page<LooseRecord>>("/api/audit-logs", { query: { ...params } }),
  importRuns: (params: { source?: string; limit?: number } = {}) =>
    request<Page<LooseRecord>>("/api/import-runs", { query: { ...params } }),

  // ---------------- sources and platforms ----------------
  sources: () => request<S["SourceRead"][]>("/api/sources"),
  updateSource: (source: S["SourceName"], body: S["SourceUpdate"]) =>
    request<S["SourceRead"]>(`/api/sources/${source}`, { method: "PATCH", body }),
  platforms: () => request<S["PlatformSummary"][]>("/api/platforms"),
  platform: (key: string) => request<S["PlatformDetail"]>(`/api/platforms/${enc(key)}`),

  // ---------------- account (hosted sign-in) ----------------
  me: () => request<S["AccountRead"]>("/api/auth/me"),
  deleteAccount: (confirmEmail: string) =>
    request<void>("/api/auth/account/delete", { method: "POST", body: { confirm_email: confirmEmail } }),

  // ---------------- profile and resumes ----------------
  profile: () => request<S["ProfileRead"]>("/api/profile"),
  updateProfile: (body: S["ProfileUpdate"]) =>
    request<S["ProfileRead"]>("/api/profile", { method: "PUT", body }),
  completeOnboarding: () =>
    request<S["ProfileRead"]>("/api/profile/onboarding-complete", { method: "POST" }),
  resumes: () => request<Page<S["ResumeRead"]>>("/api/resumes"),
  resume: (id: number) => request<S["ResumeRead"]>(`/api/resumes/${id}`),
  parsedResume: (id: number) => request<S["ParsedResumeFields"]>(`/api/resumes/${id}/parsed`),
  uploadResume: (file: File, label = "base", isPrimary = true) => {
    const form = new FormData();
    form.set("file", file);
    form.set("label", label);
    form.set("is_primary", String(isPrimary));
    return request<S["ResumeUploadResponse"]>("/api/resumes", { method: "POST", form });
  },
  setPrimaryResume: (id: number) =>
    request<S["ResumeRead"]>(`/api/resumes/${id}/primary`, { method: "POST" }),
  resumeVariants: (id: number) =>
    request<Page<S["VariantRead"]>>(`/api/resumes/${id}/variants`),
  createVariant: (body: S["VariantRequest"]) =>
    request<S["VariantRead"]>("/api/resumes/variants", { method: "POST", body }),

  // ---------------- jobs ----------------
  jobs: (params: JobListParams = {}) =>
    request<Page<S["JobRead"]>>("/api/jobs", { query: { ...params } }),
  job: (id: number) => request<S["JobDetail"]>(`/api/jobs/${id}`),
  jobExplanation: (id: number) =>
    request<S["JobExplanationRead"]>(`/api/jobs/${id}/explanation`),
  shortlistJob: (id: number) =>
    request<S["ActionResult"]>(`/api/jobs/${id}/shortlist`, { method: "POST" }),
  skipJob: (id: number, reason = "") =>
    request<S["ActionResult"]>(`/api/jobs/${id}/skip`, { method: "POST", query: { reason } }),
  scoreJobs: (body: S["ScoreRequest"] = { rescore_all: false, offset: 0 }) =>
    request<S["ScoreSummary"]>("/api/jobs/score", { method: "POST", body }),
  discoverJobs: (body: S["DiscoverRequest"] = { trigger: "manual" }) =>
    request<S["ImportSummary"][]>("/api/jobs/discover", { method: "POST", body }),
  importJobs: (body: S["JobImportRequest"]) =>
    request<S["ImportSummary"]>("/api/jobs/import", { method: "POST", body }),
  importJobsCsv: (file: File, source: S["SourceName"]) => {
    const form = new FormData();
    form.set("file", file);
    form.set("source", source);
    return request<S["ImportSummary"]>("/api/jobs/import-csv", { method: "POST", form });
  },

  // ---------------- saved searches ----------------
  searches: () => request<S["SavedSearchRead"][]>("/api/searches"),
  createSearch: (body: S["SavedSearchCreate"]) =>
    request<S["SavedSearchRead"]>("/api/searches", { method: "POST", body }),
  updateSearch: (id: number, body: S["SavedSearchUpdate"]) =>
    request<S["SavedSearchRead"]>(`/api/searches/${id}`, { method: "PATCH", body }),
  deleteSearch: (id: number) => request<void>(`/api/searches/${id}`, { method: "DELETE" }),
  previewSearch: (id: number, limit = 50) =>
    request<S["SavedSearchDigest"]>(`/api/searches/${id}/preview`, { query: { limit } }),
  runSearch: (id: number, limit = 50) =>
    request<S["SavedSearchDigest"]>(`/api/searches/${id}/run`, {
      method: "POST",
      query: { limit },
    }),

  // ---------------- applications ----------------
  applications: (
    params: { status?: S["ApplicationStatus"]; outcome?: S["Outcome"]; limit?: number; offset?: number } = {},
  ) => request<Page<S["ApplicationRead"]>>("/api/applications", { query: { ...params } }),
  application: (id: number) => request<S["ApplicationDetail"]>(`/api/applications/${id}`),
  prepareApplication: (body: S["PrepareRequest"]) =>
    request<S["ApplicationDetail"]>("/api/applications/prepare", { method: "POST", body }),
  updateApplication: (id: number, body: S["ApplicationUpdate"]) =>
    request<S["ApplicationDetail"]>(`/api/applications/${id}`, { method: "PATCH", body }),
  recordOpened: (id: number) =>
    request<S["ApplicationDetail"]>(`/api/applications/${id}/record-opened`, { method: "POST" }),
  regenerateApplication: (id: number) =>
    request<S["ApplicationDetail"]>(`/api/applications/${id}/regenerate`, { method: "POST" }),
  applicationArtifacts: (id: number) =>
    request<ArtifactVersion[]>(`/api/applications/${id}/artifacts`),

  // ---------------- answer bank and action inbox ----------------
  answers: () => request<S["SavedAnswerRead"][]>("/api/answers"),
  inbox: (limit = 100) => request<S["InboxEntryRead"][]>("/api/answers/inbox", { query: { limit } }),
  saveAnswer: (questionKey: string, body: S["SavedAnswerWrite"]) =>
    request<S["ResolveResponse"]>(`/api/answers/${enc(questionKey)}`, { method: "PUT", body }),
  deleteAnswer: (questionKey: string) =>
    request<void>(`/api/answers/${enc(questionKey)}`, { method: "DELETE" }),

  // ---------------- bulk preparation ----------------
  batches: (limit = 20, offset = 0) =>
    request<Page<S["BatchRunRead"]>>("/api/batches", { query: { limit, offset } }),
  batch: (id: number) => request<S["BatchRunDetail"]>(`/api/batches/${id}`),
  previewBatch: (body: S["BatchStartRequest"]) =>
    request<S["BatchPreview"]>("/api/batches/preview", { method: "POST", body }),
  startBatch: (body: S["BatchStartRequest"]) =>
    request<S["BatchRunDetail"]>("/api/batches", { method: "POST", body }),
  cancelBatch: (id: number) =>
    request<S["BatchRunDetail"]>(`/api/batches/${id}/cancel`, { method: "POST" }),
  resumeBatch: (id: number) =>
    request<S["BatchRunDetail"]>(`/api/batches/${id}/resume`, {
      method: "POST",
      query: { run_in_background: true },
    }),

  // ---------------- auto-apply ----------------
  capabilities: () => request<S["SubmissionCapabilitiesRead"]>("/api/autoapply/capabilities"),
  autoapplyPreferences: () => request<S["AutoApplyTargetsIn"]>("/api/autoapply/preferences"),
  saveAutoapplyPreferences: (body: S["AutoApplyTargetsIn"]) =>
    request<S["AutoApplyTargetsIn"]>("/api/autoapply/preferences", { method: "PUT", body }),
  preflight: (body: S["AutoApplyTargetsIn"]) =>
    request<S["PreflightRead"]>("/api/autoapply/preflight", { method: "POST", body }),
  startRun: (body: S["AutoApplyTargetsIn"], background: boolean) =>
    request<S["AutoApplyRunRead"]>("/api/autoapply/runs", {
      method: "POST",
      body,
      query: { run_in_background: background },
    }),
  runs: (limit = 20, offset = 0) =>
    request<Page<S["AutoApplyRunRead"]>>("/api/autoapply", { query: { limit, offset } }),
  run: (id: number) => request<S["AutoApplyRunRead"]>(`/api/autoapply/runs/${id}`),
  pauseRun: (id: number) =>
    request<S["AutoApplyRunRead"]>(`/api/autoapply/runs/${id}/pause`, { method: "POST" }),
  resumeRun: (id: number) =>
    request<S["AutoApplyRunRead"]>(`/api/autoapply/runs/${id}/resume`, {
      method: "POST",
      query: { run_in_background: true },
    }),
  cancelRun: (id: number) =>
    request<S["AutoApplyRunRead"]>(`/api/autoapply/runs/${id}/cancel`, { method: "POST" }),
  runReportUrl: (id: number) => `/api/backend/api/autoapply/runs/${id}/report`,
  attempt: (id: number) => request<S["SubmissionAttemptDetail"]>(`/api/autoapply/attempts/${id}`),
  attemptEvidenceUrl: (id: number) => `/api/backend/api/autoapply/attempts/${id}/evidence`,
  recheckAttempt: (id: number) =>
    request<S["SubmissionAttemptDetail"]>(`/api/autoapply/attempts/${id}/recheck`, {
      method: "POST",
    }),
  resolveAttempt: (id: number, body: S["ResolveAttemptIn"]) =>
    request<S["SubmissionAttemptDetail"]>(`/api/autoapply/attempts/${id}/resolve`, {
      method: "POST",
      body,
    }),
  control: () => request<S["ControlStatusRead"]>("/api/autoapply/control"),
  emergencyStop: (reason = "") =>
    request<S["ControlStatusRead"]>("/api/autoapply/emergency-stop", {
      method: "POST",
      body: { reason },
    }),
  clearEmergencyStop: () =>
    request<S["ControlStatusRead"]>("/api/autoapply/emergency-stop/clear", { method: "POST" }),
  resetCircuit: (target: string) =>
    request<S["ControlStatusRead"]>(`/api/autoapply/circuits/${enc(target)}/reset`, {
      method: "POST",
    }),
  cleanupEvidence: () =>
    request<Record<string, number>>("/api/autoapply/evidence/cleanup", { method: "POST" }),

  // ---------------- email tracking ----------------
  emailStatus: () => request<S["EmailTrackingStatus"]>("/api/email/status"),
  gmailConnect: () => request<S["GmailConnectResponse"]>("/api/email/gmail/connect"),
  syncEmail: () => request<S["EmailSyncResponse"][]>("/api/email/sync", { method: "POST" }),
  ingestEmail: (body: S["EmailIngestRequest"]) =>
    request<S["EmailIngestResponse"]>("/api/email/ingest", { method: "POST", body }),
  emailMessages: (params: { match_state?: string; category?: string; limit?: number; offset?: number } = {}) =>
    request<Page<S["EmailMessageRead"]>>("/api/email/messages", { query: { ...params } }),
  linkEmail: (id: number, body: S["EmailLinkRequest"]) =>
    request<S["EmailLinkResponse"]>(`/api/email/messages/${id}/link`, { method: "POST", body }),
  dismissEmail: (id: number) =>
    request<S["EmailMessageRead"]>(`/api/email/messages/${id}/dismiss`, { method: "POST" }),
  suggestions: (state = "pending", limit = 100) =>
    request<S["StatusSuggestionRead"][]>("/api/email/suggestions", { query: { state, limit } }),
  acceptSuggestion: (id: number) =>
    request<S["SuggestionDecision"]>(`/api/email/suggestions/${id}/accept`, { method: "POST" }),
  dismissSuggestion: (id: number) =>
    request<S["SuggestionDecision"]>(`/api/email/suggestions/${id}/dismiss`, { method: "POST" }),
  disconnectEmail: () =>
    request<S["EmailDisconnectResponse"]>("/api/email/disconnect", { method: "POST" }),
  deleteEmailData: () => request<S["EmailDeleteResponse"]>("/api/email/data", { method: "DELETE" }),

  // ---------------- research, salary, interview prep ----------------
  parseSalary: (text: string, defaultCurrency = "INR") =>
    request<S["SalaryParseRead"]>("/api/research/salary/parse", {
      query: { text, default_currency: defaultCurrency },
    }),
  jobSalary: (jobId: number) => request<S["JobSalaryRead"]>(`/api/research/jobs/${jobId}/salary`),
  jobCompany: (jobId: number) =>
    request<S["CompanyResearchRead"]>(`/api/research/jobs/${jobId}/company`),
  company: (name: string) => request<S["CompanyResearchRead"]>(`/api/research/companies/${enc(name)}`),
  refreshCompany: (name: string, body: S["CompanyRefreshRequest"] | null = null) =>
    request<S["CompanyResearchRead"]>(`/api/research/companies/${enc(name)}/refresh`, {
      method: "POST",
      body: body ?? {},
    }),
  interviewPrep: (applicationId: number) =>
    request<S["InterviewPrepRead"]>(`/api/research/applications/${applicationId}/interview-prep`),
  generateInterviewPrep: (applicationId: number, regenerate = false) =>
    request<S["InterviewPrepRead"]>(`/api/research/applications/${applicationId}/interview-prep`, {
      method: "POST",
      body: { regenerate },
    }),
  nextPracticeQuestion: (applicationId: number, params: { kind?: string; after?: string } = {}) =>
    request<S["NextQuestionRead"]>(
      `/api/research/applications/${applicationId}/interview-prep/next-question`,
      { query: { ...params } },
    ),
  recordPractice: (applicationId: number, body: S["PracticeRequest"]) =>
    request<S["PracticeResult"]>(
      `/api/research/applications/${applicationId}/interview-prep/practice`,
      { method: "POST", body },
    ),
  interviewRounds: (applicationId: number) =>
    request<S["InterviewRoundRead"][]>(`/api/research/applications/${applicationId}/rounds`),
  createInterviewRound: (applicationId: number, body: S["InterviewRoundCreate"]) =>
    request<S["InterviewRoundRead"]>(`/api/research/applications/${applicationId}/rounds`, {
      method: "POST",
      body,
    }),
  updateInterviewRound: (roundId: number, body: S["InterviewRoundUpdate"]) =>
    request<S["InterviewRoundRead"]>(`/api/research/rounds/${roundId}`, { method: "PATCH", body }),
  deleteInterviewRound: (roundId: number) =>
    request<void>(`/api/research/rounds/${roundId}`, { method: "DELETE" }),

  // ---------------- capture extension ----------------
  captureStatus: () => request<S["CaptureStatus"]>("/api/capture/status"),
};

export type Api = typeof api;
