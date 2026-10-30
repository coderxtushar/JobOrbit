# Bulk preparation: 100+ applications in one run

The slow part of a job search is not the final click. It is producing a hundred tailored
applications and answering the same screening questions a hundred times. This is what the
bulk pipeline removes, and what it deliberately does not.

**It prepares. It never submits.** A finished run leaves prepared applications in the
review queue and unanswered questions in the action inbox. There is no submit endpoint on
`/api/batches` any more than on `/api/applications`, and `tests/test_batch.py` asserts
that the bulk path cannot acquire a capability the single-job path refuses.

## The workflow

1. **Select** by band, minimum score, posting age, title and source. `POST
   /api/batches/preview` reports the count before anything is written. Jobs you already
   submitted, approved or skipped are excluded automatically.
2. **Prepare** each selected job: pick the truthful resume variant, draft a cover letter
   from verified facts, build the question set, and fill every question that has a banked
   answer.
3. **Review** the exceptions. Each item lands in one of six states, and every one carries
   a reason.
4. **Answer once** in the action inbox. One answer is written to every open application
   waiting on that question.
5. **Approve and submit yourself** from the review queue.

## Item states

| State | Meaning |
|---|---|
| `prepared` | Ready for review with no outstanding questions |
| `needs_action` | Prepared, but some questions need you — see the action inbox |
| `skipped_duplicate` | An application for this posting already exists and was submitted |
| `skipped_ineligible` | No application URL, or the URL was rejected as unsafe |
| `failed` | Every attempt failed; the reason and attempt count are recorded |
| `queued` / `in_progress` | Not finished — a resume will pick these up |

## The four properties a long run needs

**Checkpointed.** Each item is committed in its own transaction as it finishes, so a crash
loses at most the item in flight. Progress is readable from `GET /api/batches/{id}` while
the run is still going.

**Resumable.** On startup, any run left `RUNNING` by a dead process is reconciled to
`INTERRUPTED` and its in-flight items returned to `QUEUED`. `POST /api/batches/{id}/resume`
then processes only what never finished. A **cancelled** item is resumable too — it was
never attempted, so treating it as final would make Resume useless on exactly the runs that
need it.

**Idempotent.** Preparing a job that already has an open application refreshes it instead
of creating a second one; the `(job_id, profile_id)` unique constraint makes a duplicate
structurally impossible. Verified live: a cancelled 103-job run was resumed to completion
and the application count did not change.

**Cancellable.** `POST /api/batches/{id}/cancel` sets a flag the workers re-read from the
database between items — not from an ORM copy, because the request is written by a
different thread in a different session. Work already done is kept.

## Concurrency

`concurrency` (1–16, enforced by a `CHECK` constraint) overlaps the per-job work: variant
selection, letter drafting and question mapping. On SQLite the database still serialises
writers, so values above about 4 buy little. The connection sets `journal_mode=WAL` and
`busy_timeout=15000` so concurrent workers wait for each other instead of failing with
"database is locked", and a lock error that does slip through is treated as retryable.

Retries are bounded by `max_attempts` (1–10) with exponential backoff. A condition that
will not improve — a missing job, an unsafe URL — is not retried at all; it is recorded as
skipped with the reason.

## Dry run

`"dry_run": true` reports exactly which jobs are eligible and writes nothing: no
application, no answer, no artifact. Item rows are still created so you can read the plan.
Verified: a 103-job dry run left the application table empty.

## The answer bank and action inbox

The inbox is **derived, not stored**. It groups `application_answer` rows by
`question_key`, so one question blocking eighty applications is a single row with a count
of eighty. The work is proportional to the number of distinct questions, not the number of
jobs.

Two rules keep reuse honest:

- Only an answer you typed or one read from a verified profile field can enter the bank.
  An `ai_draft` is rejected by `UnbankableAnswerError` **and** by a database `CHECK`
  constraint — reuse would repeat one unreviewed sentence to a hundred employers.
- A sensitive or legal question is never drafted. Work authorization, sponsorship, salary,
  notice period, experience, education and legal declarations can only be filled from a
  verified profile field or by you typing them.

Backfill only touches applications that are still open. One already submitted or confirmed
is the record of what an employer received and is never rewritten.

Measured on the live 104-application run: four answers given once filled 416 answer slots
and dropped the inbox from 825 outstanding slots to 417.

## Artifacts

Every preparation snapshots the exact resume variant text and cover letter into
`application_artifact`, content-addressed by SHA-256. Re-preparing with identical text adds
no row; changed text is kept **alongside** the earlier version, so what a given employer
received stays reproducible after the variant is regenerated.

## Reference

```bash
# how many jobs would this cover?
curl -X POST http://127.0.0.1:8000/api/batches/preview \
  -H 'Content-Type: application/json' \
  -d '{"selection":{"bands":["high","review"],"min_score":65,"max_age_days":30,"limit":200}}'

# prepare them (returns immediately; progress is readable while it runs)
curl -X POST http://127.0.0.1:8000/api/batches \
  -H 'Content-Type: application/json' \
  -d '{"selection":{"bands":["high","review"],"limit":200},"concurrency":4,"max_attempts":3}'

curl http://127.0.0.1:8000/api/batches/1          # status and every item
curl -X POST http://127.0.0.1:8000/api/batches/1/cancel
curl -X POST http://127.0.0.1:8000/api/batches/1/resume

# answer one question everywhere it is needed
curl http://127.0.0.1:8000/api/answers/inbox
curl -X PUT http://127.0.0.1:8000/api/answers/notice_period \
  -H 'Content-Type: application/json' -d '{"answer":"Immediately available"}'
```

| Setting | Default | Effect |
|---|---|---|
| `JA_BATCH_CONCURRENCY` | 4 | Default worker count |
| `JA_BATCH_MAX_ATTEMPTS` | 3 | Attempts per job before it is recorded as failed |
| `JA_BATCH_MAX_JOBS` | 500 | Upper bound on one selection |
