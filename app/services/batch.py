"""Bulk application preparation.

Prepares many applications in one run: a hundred jobs selected by score, freshness, role
and application state, each one given a resume variant, a cover letter and a full answer
set. It stops exactly where the single-job path stops — at ``READY_FOR_REVIEW``. There is
no submission step here and no browser is driven; the run's output is a review queue and
an action inbox.

Four properties make a long run survivable:

* **Checkpointed.** Each item is committed in its own transaction as it finishes, so a
  crash loses at most the item in flight.
* **Resumable.** Re-running a run only picks up items that are not yet terminal, and the
  ``(run, job)`` unique constraint makes re-queuing impossible.
* **Idempotent.** Preparing a job that already has an open application refreshes it rather
  than creating a second one; a submitted application is skipped, never overwritten.
* **Cancellable.** The worker re-reads the cancel flag from the database between items,
  because the request is written by a different thread in a different session.

Concurrency overlaps the per-job work (variant selection, letter drafting, question
mapping). On SQLite the database still serialises writers, so values above ~4 buy little;
the ceiling of 16 is enforced in the schema.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.base import session_scope
from app.db.models import (
    Application,
    ApplicationStatus,
    BatchItemStatus,
    BatchRun,
    BatchRunItem,
    BatchStatus,
    CandidateProfile,
    Job,
    JobMatch,
    JobSourceReference,
    JobStatus,
    SourceName,
    utcnow,
)
from app.db.repositories import (
    AuditRepository,
    BatchRunRepository,
    DuplicateApplicationError,
    ProfileRepository,
)
from app.llm.base import LLMProvider
from app.logging_conf import get_logger
from app.services.application_prep import ApplicationPreparationService
from app.services.url_safety import is_safe_url

logger = get_logger(__name__)

#: Statuses that mean "already dealt with"; such a job is never re-queued by a selection.
_ALREADY_HANDLED: frozenset[ApplicationStatus] = frozenset(
    {
        ApplicationStatus.APPROVED,
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.CONFIRMED,
        ApplicationStatus.SKIPPED,
    }
)

#: A locked or momentarily busy database is the ordinary cost of running several workers
#: against SQLite, so it is retried rather than reported as a failed job.
_RETRYABLE_EXCEPTIONS = (OSError, TimeoutError, OperationalError)


@dataclass(slots=True)
class BatchSelection:
    """Which jobs a run should cover."""

    min_score: float | None = None
    bands: list[str] = field(default_factory=list)
    max_age_days: int | None = None
    titles: list[str] = field(default_factory=list)
    sources: list[SourceName] = field(default_factory=list)
    include_filtered: bool = False
    include_unscored: bool = False
    limit: int = 100

    def as_dict(self) -> dict[str, object]:
        return {
            "min_score": self.min_score,
            "bands": list(self.bands),
            "max_age_days": self.max_age_days,
            "titles": list(self.titles),
            "sources": [source.value for source in self.sources],
            "include_filtered": self.include_filtered,
            "include_unscored": self.include_unscored,
            "limit": self.limit,
        }


@dataclass(slots=True)
class BatchOptions:
    concurrency: int = 4
    max_attempts: int = 3
    dry_run: bool = False
    include_cover_letter: bool = True


@dataclass(slots=True)
class ItemResult:
    job_id: int
    status: BatchItemStatus
    detail: str = ""
    application_id: int | None = None
    blocking_questions: int = 0
    attempts: int = 1


def select_job_ids(
    session: Session, profile: CandidateProfile, selection: BatchSelection
) -> list[int]:
    """Resolve a selection into an ordered list of job ids, highest score first."""
    statement = (
        select(Job.id, JobMatch.total_score)
        .outerjoin(
            JobMatch,
            (JobMatch.job_id == Job.id) & (JobMatch.profile_id == profile.id),
        )
        .outerjoin(
            Application,
            (Application.job_id == Job.id) & (Application.profile_id == profile.id),
        )
        .where(
            Job.status.notin_([JobStatus.DUPLICATE, JobStatus.EXPIRED, JobStatus.SKIPPED]),
            Application.id.is_(None) | Application.status.notin_(_ALREADY_HANDLED),
        )
    )

    if not selection.include_unscored:
        statement = statement.where(JobMatch.id.isnot(None))
    if not selection.include_filtered:
        statement = statement.where(JobMatch.filtered_out.isnot(True))
    if selection.min_score is not None:
        statement = statement.where(JobMatch.total_score >= selection.min_score)
    if selection.bands:
        statement = statement.where(JobMatch.band.in_(selection.bands))
    if selection.max_age_days is not None:
        cutoff = utcnow() - timedelta(days=selection.max_age_days)
        statement = statement.where(Job.posted_at.is_(None) | (Job.posted_at >= cutoff))
    if selection.sources:
        statement = statement.where(
            Job.id.in_(
                select(JobSourceReference.job_id).where(
                    JobSourceReference.source.in_(selection.sources)
                )
            )
        )
    if selection.titles:
        clauses = [Job.title.ilike(f"%{title.strip()}%") for title in selection.titles if title]
        if clauses:
            statement = statement.where(or_(*clauses))

    statement = statement.order_by(JobMatch.total_score.desc().nullslast(), Job.id).limit(
        max(1, selection.limit)
    )
    return [int(row[0]) for row in session.execute(statement).all()]


class BatchPreparationService:
    """Creates and executes bulk preparation runs."""

    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        session_factory: Callable[[], AbstractContextManager[Session]] | None = None,
    ) -> None:
        self._provider = provider
        self._session_factory = session_factory
        self._cancel_events: dict[int, threading.Event] = {}

    @contextmanager
    def _session(self) -> Iterator[Session]:
        factory = self._session_factory or session_scope
        with factory() as session:
            yield session

    # ---------------- run lifecycle ----------------

    def create_run(
        self,
        session: Session,
        profile: CandidateProfile,
        selection: BatchSelection,
        options: BatchOptions,
    ) -> BatchRun:
        runs = BatchRunRepository(session)
        job_ids = select_job_ids(session, profile, selection)
        run = runs.create(
            BatchRun(
                profile_id=profile.id,
                status=BatchStatus.PENDING,
                dry_run=options.dry_run,
                concurrency=max(1, min(16, options.concurrency)),
                max_attempts=max(1, min(10, options.max_attempts)),
                selection=selection.as_dict(),
            )
        )
        runs.add_items(run, job_ids)
        AuditRepository(session).record(
            "batch.created",
            entity_type="batch_run",
            entity_id=run.id,
            detail={
                "jobs": len(job_ids),
                "dry_run": options.dry_run,
                "concurrency": run.concurrency,
                "selection": selection.as_dict(),
            },
        )
        logger.info(
            "batch run created",
            extra={"run_id": run.id, "jobs": len(job_ids), "dry_run": options.dry_run},
        )
        return run

    def request_cancel(self, session: Session, run: BatchRun) -> BatchRun:
        BatchRunRepository(session).request_cancel(run)
        event = self._cancel_events.get(run.id)
        if event is not None:
            event.set()
        AuditRepository(session).record(
            "batch.cancel_requested", entity_type="batch_run", entity_id=run.id
        )
        return run

    def execute(self, run_id: int, *, include_cover_letter: bool = True) -> dict[str, object]:
        """Run or resume a batch. Returns the final counts.

        Safe to call on a run that is partly done: only non-terminal items are processed.
        """
        cancel_event = self._cancel_events.setdefault(run_id, threading.Event())
        cancel_event.clear()

        with self._session() as session:
            runs = BatchRunRepository(session)
            run = runs.get(run_id)
            if run is None:
                raise KeyError(f"batch run {run_id} does not exist")
            if run.status in (BatchStatus.RUNNING, BatchStatus.CANCELLING):
                raise RuntimeError(f"batch run {run_id} is already running")
            profile_id = run.profile_id
            dry_run = run.dry_run
            concurrency = run.concurrency
            max_attempts = run.max_attempts
            run.status = BatchStatus.RUNNING
            run.finished_at = None
            run.message = ""
            session.flush()
            pending = [(item.id, item.job_id) for item in runs.pending_items(run_id)]

        processed = 0
        try:
            if pending:
                with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
                    futures = [
                        pool.submit(
                            self._run_item,
                            run_id=run_id,
                            item_id=item_id,
                            job_id=job_id,
                            profile_id=profile_id,
                            dry_run=dry_run,
                            max_attempts=max_attempts,
                            include_cover_letter=include_cover_letter,
                            cancel_event=cancel_event,
                        )
                        for item_id, job_id in pending
                    ]
                    for future in futures:
                        try:
                            future.result()
                        except Exception as exc:  # noqa: BLE001 - one worker must not abort the run
                            logger.error(
                                "batch worker raised",
                                extra={"run_id": run_id, "reason": str(exc)},
                            )
                        else:
                            processed += 1
        finally:
            self._cancel_events.pop(run_id, None)

        with self._session() as session:
            runs = BatchRunRepository(session)
            run = runs.get(run_id)
            assert run is not None
            counts = runs.item_status_counts(run.id)
            cancelled = run.cancel_requested or cancel_event.is_set()
            failed = counts.get(BatchItemStatus.FAILED.value, 0)
            if cancelled:
                status, message = BatchStatus.CANCELLED, "cancelled on request"
            elif failed:
                status = BatchStatus.COMPLETED_WITH_ERRORS
                message = f"{failed} item(s) failed; open the run to see each reason"
            else:
                status, message = BatchStatus.COMPLETED, "every selected job was processed"
            if dry_run:
                message = f"dry run: nothing was written. {message}"
            runs.finish(run, status, message)
            AuditRepository(session).record(
                "batch.finished",
                entity_type="batch_run",
                entity_id=run.id,
                detail={"status": status.value, "counts": counts, "processed": processed},
            )
            summary: dict[str, object] = {
                "run_id": run.id,
                "status": status.value,
                "counts": counts,
                "prepared": run.prepared_count,
                "needs_action": run.needs_action_count,
                "skipped": run.skipped_count,
                "failed": run.failed_count,
                "message": message,
            }
        logger.info(
            "batch run finished",
            extra={
                "run_id": summary["run_id"],
                "run_status": summary["status"],
                "prepared": summary["prepared"],
                "needs_action": summary["needs_action"],
                "skipped": summary["skipped"],
                "failed": summary["failed"],
            },
        )
        return summary

    # ---------------- per-item work ----------------

    def _run_item(
        self,
        *,
        run_id: int,
        item_id: int,
        job_id: int,
        profile_id: int,
        dry_run: bool,
        max_attempts: int,
        include_cover_letter: bool,
        cancel_event: threading.Event,
    ) -> None:
        if cancel_event.is_set() or self._cancel_flag(run_id):
            cancel_event.set()
            self._checkpoint(
                item_id,
                ItemResult(job_id, BatchItemStatus.CANCELLED, "cancelled before this job started"),
            )
            return

        result = self._prepare_with_retries(
            job_id=job_id,
            profile_id=profile_id,
            dry_run=dry_run,
            max_attempts=max_attempts,
            include_cover_letter=include_cover_letter,
        )
        try:
            self._checkpoint(item_id, result)
        except Exception as exc:  # noqa: BLE001 - see below
            # The work succeeded but recording it did not. The item is deliberately left
            # non-terminal so a resume picks it up again; preparation is idempotent, so
            # redoing it refreshes the same application rather than creating a second.
            logger.error(
                "batch checkpoint failed; item left resumable",
                extra={"run_id": run_id, "item_id": item_id, "reason": str(exc)},
            )

    def _cancel_flag(self, run_id: int) -> bool:
        with self._session() as session:
            return BatchRunRepository(session).cancel_requested(run_id)

    def _prepare_with_retries(
        self,
        *,
        job_id: int,
        profile_id: int,
        dry_run: bool,
        max_attempts: int,
        include_cover_letter: bool,
    ) -> ItemResult:
        last_error = ""
        for attempt in range(1, max_attempts + 1):
            try:
                result = self._prepare_one(
                    job_id=job_id,
                    profile_id=profile_id,
                    dry_run=dry_run,
                    include_cover_letter=include_cover_letter,
                )
                result.attempts = attempt
                return result
            except _NonRetryable as exc:
                return ItemResult(
                    job_id, BatchItemStatus.SKIPPED_INELIGIBLE, str(exc), attempts=attempt
                )
            except DuplicateApplicationError as exc:
                return ItemResult(
                    job_id, BatchItemStatus.SKIPPED_DUPLICATE, str(exc), attempts=attempt
                )
            except _RETRYABLE_EXCEPTIONS as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "batch item attempt failed",
                    extra={"job_id": job_id, "attempt": attempt, "reason": last_error},
                )
            except Exception as exc:  # noqa: BLE001 - one bad job must not kill the run
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "batch item raised",
                    extra={"job_id": job_id, "attempt": attempt, "reason": last_error},
                )
        return ItemResult(
            job_id,
            BatchItemStatus.FAILED,
            f"failed after {max_attempts} attempt(s): {last_error}",
            attempts=max_attempts,
        )

    def _prepare_one(
        self,
        *,
        job_id: int,
        profile_id: int,
        dry_run: bool,
        include_cover_letter: bool,
    ) -> ItemResult:
        with self._session() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise _NonRetryable(f"job {job_id} no longer exists")
            profile = ProfileRepository(session).get(profile_id)
            if profile is None:
                raise _NonRetryable(f"candidate profile {profile_id} no longer exists")

            destination = job.url or job.canonical_url
            if not destination:
                raise _NonRetryable(
                    "this listing has no application URL, so there is nowhere to send you"
                )
            if not is_safe_url(destination):
                raise _NonRetryable(
                    "this listing's application URL was rejected as unsafe, so it was not prepared"
                )

            if dry_run:
                return ItemResult(
                    job_id,
                    BatchItemStatus.PREPARED,
                    "dry run: eligible, nothing written",
                )

            service = ApplicationPreparationService(session, self._provider)
            prepared = service.prepare(
                job,
                profile,
                include_cover_letter=include_cover_letter,
            )
            blocking = len(prepared.blocking_questions)
            status = BatchItemStatus.NEEDS_ACTION if blocking else BatchItemStatus.PREPARED
            detail = (
                f"{blocking} question(s) need your answer"
                if blocking
                else f"ready for review; {prepared.reused_answers} answer(s) reused"
            )
            return ItemResult(
                job_id,
                status,
                detail,
                application_id=prepared.application.id,
                blocking_questions=blocking,
            )

    def _checkpoint(self, item_id: int, result: ItemResult) -> None:
        with self._session() as session:
            item = session.get(BatchRunItem, item_id)
            if item is None:
                return
            item.status = result.status
            item.detail = result.detail[:2000]
            item.attempts = result.attempts
            item.application_id = result.application_id
            item.blocking_questions = result.blocking_questions
            item.started_at = item.started_at or utcnow()
            item.finished_at = utcnow()
            run = session.get(BatchRun, item.batch_run_id)
            if run is not None:
                BatchRunRepository(session).refresh_counts(run)


class _NonRetryable(RuntimeError):
    """A per-job condition that will not improve on another attempt."""
