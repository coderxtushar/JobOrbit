# Database Schema

12 tables. SQLite locally; the same models run on PostgreSQL by changing
`JA_DATABASE_URL`, because no SQL exists outside `app/db/repositories`.

All timestamps are stored in UTC through the `UtcDateTime` type decorator, which attaches
`tzinfo` on read so SQLite and PostgreSQL behave identically. SQLite additionally needs
`PRAGMA foreign_keys=ON` per connection; that is set in `app/db/base.py` and is the only
dialect-specific code in the project.

## Diagram

```
                         ┌────────────────────────┐
                         │   candidate_profile    │
                         │ (one row: the local    │
                         │  user's verified data) │
                         └───┬────────────┬───────┘
                             │1           │1
              ┌──────────────┘            └──────────────┬──────────────┐
              │N                                        │N             │N
      ┌───────────────┐                         ┌──────────────┐ ┌─────────────┐
      │    resume     │                         │  job_match   │ │ application │
      │ file + parsed │                         │  COMPUTED    │ │             │
      │   extraction  │                         │  score only  │ │             │
      └───────┬───────┘                         └──────┬───────┘ └──┬───┬──────┘
              │1                                       │N           │N  │N
              │                                        │            │   │
      ┌───────────────┐                         ┌──────────────┐    │   │
      │resume_variant │                         │     job      │────┘   │
      │ reordered     │                         │  IMPORTED    │1       │
      │ facts only    │                         │  data only   │        │
      └───────────────┘                         └──────┬───────┘        │
                                                       │1               │
                                              ┌────────────────────┐    │
                                              │job_source_reference│    │
                                              │ one row per        │    │
                                              │ platform sighting  │    │
                                              └─────────┬──────────┘    │
                                                        │N              │
                                              ┌──────────────┐          │
                                              │  import_run  │          │
                                              └──────────────┘          │
                                                                        │
                            ┌───────────────────────────────────────────┤
                            │N                                         │N
                   ┌────────────────────┐                   ┌────────────────────┐
                   │ application_answer │                   │ application_event  │
                   │ + provenance       │                   │ append-only audit  │
                   └────────────────────┘                   └────────────────────┘

   Standalone:  source_configuration (per-source settings, capability ceiling)
                audit_log            (append-only record of user/system actions)
```

## Tables

### candidate_profile
The user's verified facts and preferences. Exactly one row in normal use.

Sensitive columns are nullable on purpose: `salary_expectation_min`, `notice_period_days`,
`work_authorization`, `requires_sponsorship`, `graduation_date`, `open_to_relocation`.
`NULL` means "the user has not told us" and is never read as a value.

Constraints: `minimum_match_score` between 0 and 100, `max_job_age_days > 0`.

### resume
An uploaded file plus what the parser extracted. `extracted_fields` and `parse_warnings`
hold machine output and stay separate from the profile the user confirmed. Indexed on
`profile_id` and `sha256` (the hash is what detects a re-upload of the same file).

### resume_variant
A job-family-specific rendering that only *selects and reorders* facts from its source
resume. `included_items` records exactly which facts were used so the variant can be
audited against the original. Unique on `(resume_id, job_family, version)`.

### job
A normalized listing holding **source-provided data only**. Nothing computed lives here.

| Column | Why it exists |
|---|---|
| `posted_at` (nullable) | What the source said. Nullable because many listings omit it. |
| `posted_at_is_approximate` | True when derived from "3 days ago". |
| `discovered_at` | When we first stored it. Never substituted for `posted_at`. |
| `fingerprint` | Unique. SHA-256 of normalized title, company, city and a description signature. |
| `duplicate_of_id` | Self-referencing FK, kept for listings deliberately retained as duplicates. |
| `canonical_url` | Indexed. Tracking parameters stripped, so one posting has one key. |

Indexes: `status`, `posted_at`, `discovered_at`, `company_normalized`, `canonical_url`,
`fingerprint` (unique), plus composites `(status, discovered_at)` and
`(company_normalized, title)`.

### job_source_reference
One row per platform a job was seen on. A cross-platform duplicate collapses into a single
`job` with several references, so the user still sees every platform it appeared on.
Unique on `(source, external_id)` — the platform's own identifier is authoritative within
that platform.

### job_match
The computed score for a `(job, profile)` pair, unique on that pair so re-scoring is
idempotent. Holds `category_scores`, `weights_used`, matched and missing skills,
`uncertain_requirements`, the `explanation` lines, and `filtered_out` plus
`filter_reasons`. A filtered job keeps its row, which is what lets the UI explain an
exclusion instead of a job silently vanishing.

Constraint: `total_score` between 0 and 100. Indexed on `(profile_id, total_score)`.

### application
One application per job per profile. **Unique on `(job_id, profile_id)`** — this is the
structural guarantee against applying twice.

`submitted_by` is a required non-empty string before the status can become `SUBMITTED`,
and `confirmation_evidence` is required before `CONFIRMED`. Nothing in the codebase can
supply either automatically.

### application_answer
One question/answer pair with an explicit `provenance` enum
(`profile_verified`, `resume_extracted`, `ai_draft`, `user_entered`, `needs_user_input`)
plus `is_sensitive`, `requires_user_input` and `flag_reason`. An application cannot be
approved while a sensitive answer is empty or merely `ai_draft`.

### application_event
Append-only `(from_status, to_status, actor, detail, created_at)`. Written by the tracking
service on every transition, so the lifecycle is fully auditable.

### source_configuration
Per-source user settings. Unique on `source`. The adapter's declared capabilities are the
ceiling; these columns can only narrow them.

Constraints: `CHECK (NOT automated_submission_enabled)` — the database itself refuses to
record an enabled automated-submission capability — and `rate_limit_per_hour > 0`.

### import_run
One row per import or discovery attempt, successful or not, including
`SKIPPED_UNSUPPORTED` runs that record *why* a source could not be searched. Carries
`records_received`, `records_invalid`, `jobs_created`, `jobs_updated`,
`duplicates_detected`, `attempts` and `errors`.

### audit_log
Append-only record of notable actions (`jobs.import`, `jobs.scored`,
`application.prepared`, `application.status_changed`, `profile.updated`,
`source.updated`, `resume.uploaded`). Indexed on `action`, `created_at` and
`(entity_type, entity_id)`.

## Separation of data kinds

The brief asks for imported data, generated content and verified user data to be kept
explicitly apart. Where each lives:

| Kind | Location |
|---|---|
| Imported from a source | `job`, `job_source_reference`, `job.raw_payload` |
| Computed by this app | `job_match`, `resume.extracted_fields` |
| Generated prose | `resume_variant.content`, `application.cover_letter` (with `generated_by`) |
| Verified by the user | `candidate_profile`, answers with `provenance = profile_verified` or `user_entered` |

## Migrations

```bash
alembic upgrade head        # create or update the schema
alembic check               # verify the models match the migrations
alembic downgrade base      # tear down
alembic revision --autogenerate -m "description"
```

`migrations/env.py` reads the URL and metadata from the application's own settings and
models, so a revision can never be generated against a different schema than the app uses.
`render_as_batch=True` is set because SQLite cannot `ALTER` a column in place. The script
template imports `app.db.models` so autogenerated columns can reference the custom
`UtcDateTime` type.
