# API Reference

Base URL `http://127.0.0.1:8000`. Interactive docs at `/docs`, schema at `/openapi.json`.

Authentication is off when bound to loopback. Setting `JA_API_TOKEN` enables
`Authorization: Bearer <token>` on every `/api/*` route, and a non-loopback
`JA_API_HOST` without a token is refused at startup.

**There is no endpoint that submits an application.** The furthest the API goes is
recording that *you* submitted one, which requires naming who did it.

## Error shape

Every error, from any route, returns this and nothing else. Stack traces, SQL and resume
content never appear.

```json
{
  "error": {
    "code": "validation_error",
    "message": "The request body or query parameters failed validation.",
    "field_errors": { "salary_expectation_min": ["must be <= salary_expectation_max"] }
  }
}
```

| Code | Status | Meaning |
|---|---|---|
| `validation_error` | 422 | Body or query parameters rejected by Pydantic |
| `not_found` | 404 | No such job, resume or application |
| `duplicate_resume` | 409 | That exact file is already stored |
| `duplicate_application` | 409 | An application for this job already exists |
| `invalid_transition` | 409 | The status change is not permitted from the current state |
| `capability_not_available` | 422 | The source cannot do this, with the policy reason |
| `unsupported_file_type` | 415 | Not a `.pdf` or `.docx` |
| `file_too_large` | 413 | Over `JA_MAX_UPLOAD_MB` |
| `corrupt_upload` | 400 | Content does not match the extension |
| `resume_unreadable` | 422 | Encrypted or unparseable document |
| `source_unavailable` | 503 | Transient source failure; retryable |
| `automated_submission_blocked` | 403 | A non-human actor tried to record a submission |
| `internal_error` | 500 | Unexpected; carries a log reference, no detail |

## Pagination

Every list endpoint returns the same envelope and accepts `limit` (1-200, default 25) and
`offset` (≥ 0).

```json
{ "items": [], "total": 0, "limit": 25, "offset": 0 }
```

---

## System

### `GET /health`
Liveness plus dependency state. Always reports
`"automated_submission_supported": false`.

### `GET /api/diagnostics`
Per-source explanation of why it is or is not returning jobs, plus the runtime environment.

### `GET /api/metrics`
Counted facts only — every value is a row count.

### `GET /api/metrics/estimated`
Estimates, separated deliberately. Each carries the assumption it rests on in `basis`.

### `GET /api/import-runs?source=&limit=`
Import and discovery history, including `skipped_unsupported` runs and their reasons.

### `GET /api/audit-logs?action=&limit=&offset=`
The audit trail.

---

## Profile

### `GET /api/profile`
Returns the profile, creating it on first call. `unanswered_sensitive_fields` lists the
sensitive values the user has not supplied; they are flagged for manual entry rather than
guessed.

### `PUT /api/profile`
Partial update — only fields present in the body are written. Unknown fields are rejected
(`extra="forbid"`) rather than ignored.

```bash
curl -X PUT http://127.0.0.1:8000/api/profile \
  -H 'Content-Type: application/json' \
  -d '{"target_titles":["Backend Developer","AI Engineer"],
       "technical_skills":["python","fastapi","postgresql"],
       "preferred_locations":["Bengaluru","Remote"],
       "work_arrangements":["remote","hybrid"],
       "experience_level":"fresher","years_experience":0}'
```

Validated: `experience_level` ∈ fresher|junior|mid|senior|lead, `work_arrangements` ⊆
onsite|hybrid|remote, `employment_types` ⊆ full_time|part_time|internship|contract|temporary,
`minimum_match_score` 0-100, `max_job_age_days` 1-365, and salary min ≤ max.

---

## Resumes

### `POST /api/resumes`
`multipart/form-data`: `file` (required, `.pdf` or `.docx`), `label`, `is_primary`.

Returns the stored resume plus `parsed` fields. **`applied_to_profile` is always `false`**:
extraction is a proposal the user confirms through `PUT /api/profile`.

```bash
curl -X POST http://127.0.0.1:8000/api/resumes \
  -F "file=@resume.docx" -F "label=base" -F "is_primary=true"
```

Validation: extension, size, and magic bytes must agree. Filenames are rebuilt, so a
traversal attempt cannot escape the data directory.

### `GET /api/resumes`
### `GET /api/resumes/{id}`
### `GET /api/resumes/{id}/parsed`
### `POST /api/resumes/{id}/primary`
### `GET /api/resumes/{id}/variants`

### `POST /api/resumes/variants`
Builds a truthful variant for a job family. If the rendered variant would claim a skill
absent from both the resume and the profile, the request is rejected with
`variant_unsourced_claim` rather than stored.

```json
{ "job_family": "genai", "emphasised_skills": ["Python", "LangChain"] }
```

Families: `general_software`, `backend`, `frontend`, `fullstack`, `ai_ml`, `genai`,
`cloud_devops`, `data`.

---

## Jobs

### `POST /api/jobs/import`
JSON records. Each needs `source`, `title`, `company`, and at least one of `external_id`
or `url` — a record with no provenance cannot be deduplicated or revisited.

```bash
curl -X POST http://127.0.0.1:8000/api/jobs/import \
  -H 'Content-Type: application/json' \
  -d '{"records":[{"source":"linkedin","external_id":"LI-1",
       "title":"Backend Developer","company":"Acme Technologies",
       "location":"Bengaluru","url":"https://example.com/jobs/1",
       "required_skills":["Python","FastAPI"],"experience_raw":"0-2 years",
       "salary_raw":"6-10 LPA","posted_at":"3 days ago",
       "description":"Build REST APIs."}]}'
```

`posted_at` accepts a datetime **or** the source's raw string; relative phrases are
resolved at import and flagged `posted_at_is_approximate`.

### `POST /api/jobs/import-csv`
`multipart/form-data`: `file` (CSV, TSV or JSON), `source`. Column names are matched
case-insensitively against a synonym table, so board exports import unedited. Invalid rows
are counted and reported with their row number.

Returns an `ImportSummary`: `jobs_created`, `jobs_updated`, `duplicates_detected`,
`records_invalid`, `status` (`success` | `partial` | `failed`), and `errors`.

### `POST /api/jobs/discover`
Runs authorized discovery for the requested sources. A source with no authorized interface
records a `skipped_unsupported` run carrying the policy reason — it never returns
fabricated listings.

### `POST /api/jobs/score`
`{"rescore_all": true}` or `{"job_ids": [1,2,3]}`. Returns counts per band plus
`filtered_out` and `scorer` (always `rule_based`).

### `GET /api/jobs`
Filters: `search`, `status` (repeatable), `source` (repeatable), `company`, `min_score`,
`max_age_days`, `include_duplicates`, `sort_by`
(`score|posted_at|discovered_at|company|title`), `descending`, `limit`, `offset`.

Each job carries its `match` object with `category_scores`, `explanation`,
`matched_skills`, `missing_required_skills`, `uncertain_requirements`, `filtered_out` and
`filter_reasons`, plus `source_references` for every platform it appeared on.

A job whose URL failed the safety check is returned with `url: ""`.

### `GET /api/jobs/{id}`
As above plus the full `description`.

### `POST /api/jobs/{id}/shortlist`
### `POST /api/jobs/{id}/skip?reason=`

---

## Applications

### `POST /api/applications/prepare`
Selects the resume variant, drafts the cover letter, builds the answer set with provenance,
and moves the application to `READY_FOR_REVIEW`. It stops there.

```json
{ "job_id": 1, "include_cover_letter": true, "extra_questions": [] }
```

Returns `blocking_questions` — the answers needing user input before approval.

### `GET /api/applications?status=&outcome=&limit=&offset=`
### `GET /api/applications/{id}`
Includes `answers` and the full `events` history.

### `PATCH /api/applications/{id}`
Edit answers, the cover letter, notes, follow-up date, outcome and interview stage, and
drive the status machine.

```bash
# approve
curl -X PATCH .../api/applications/1 -H 'Content-Type: application/json' \
  -d '{"user_approved":true,"status":"APPROVED"}'

# record that you submitted it yourself
curl -X PATCH .../api/applications/1 -H 'Content-Type: application/json' \
  -d '{"status":"SUBMITTED","submitted_by":"Your Name"}'

# confirm, with evidence
curl -X PATCH .../api/applications/1 -H 'Content-Type: application/json' \
  -d '{"status":"CONFIRMED","confirmation_evidence":"Email ref ACME-99","outcome":"screening"}'
```

Rules enforced:

- `APPROVED` requires `user_approved` true and no blocking questions.
- `SUBMITTED` requires a non-empty `submitted_by`; a non-human actor is rejected with
  `automated_submission_blocked`.
- `CONFIRMED` requires `confirmation_evidence`. Use `SUBMISSION_UNKNOWN` when the outcome
  is unclear, rather than assuming success.
- `CONFIRMED` is terminal.

Allowed transitions:

```
DISCOVERED         → SCORED, SHORTLISTED, SKIPPED
SCORED             → SHORTLISTED, SKIPPED
SHORTLISTED        → READY_FOR_REVIEW, SKIPPED, FAILED
READY_FOR_REVIEW   → APPROVED, SHORTLISTED, SKIPPED, FAILED
APPROVED           → SUBMITTED, SUBMISSION_UNKNOWN, READY_FOR_REVIEW, SKIPPED, FAILED
SUBMITTED          → CONFIRMED, SUBMISSION_UNKNOWN, FAILED
SUBMISSION_UNKNOWN → CONFIRMED, SUBMITTED, FAILED, SKIPPED
CONFIRMED          → (terminal)
SKIPPED            → SHORTLISTED
FAILED             → SHORTLISTED, READY_FOR_REVIEW, SKIPPED
```

Editing an answer sets its provenance to `user_entered`.

---

## Sources

### `GET /api/sources`
Per source: `capabilities` (what the adapter declares), `effective_capabilities` (after
your settings), `policy_basis`, `limitations` and `status_detail`.
`automated_submission_enabled` is always `false`.

### `PATCH /api/sources/{source}`
Narrow a source's settings. Requesting a capability the adapter does not declare returns
`capability_not_available` with the policy reason, rather than being silently ignored.

```bash
curl -X PATCH http://127.0.0.1:8000/api/sources/linkedin \
  -H 'Content-Type: application/json' -d '{"manual_import_enabled": false}'
```
