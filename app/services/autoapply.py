"""One-click auto-apply orchestration.

Chains the whole morning into a single authorised run: discover from the selected
authorized sources, score, filter to the eligible set, prepare each application, dispatch
it where a provider permits dispatch, verify the outcome, and record what actually
happened. One user action authorises everything inside the configured scope.

What the single click does **not** do is guarantee a hundred applications. Authorising a
hundred attempts authorises a hundred *attempts*; how many become confirmed submissions
depends on how many jobs are eligible and how many providers permit submission at all.
Those are reported as separate numbers for that reason, and in a default installation the
confirmed count is zero because no real platform authorises candidate submission.

Four properties make a long run survivable, mirroring the bulk preparation engine:

* **Checkpointed.** Every attempt is committed in its own transaction as it finishes.
* **Resumable.** A resumed run only picks up attempts that are not terminal, and the
  ``(run, job)`` unique constraint makes re-queuing a job impossible.
* **Idempotent.** The idempotency key is derived from the job and the profile rather than
  from the attempt, so a retry reuses it and a provider honouring it cannot create a
  second application. ``OUTCOME_UNKNOWN`` is never retried at all.
* **Pausable and cancellable.** Both flags are re-read from the database between items,
  because the request is written by a different thread in a different session.

The phases are deliberately separable. ``dry_run`` runs every phase except dispatch, which
is the default, so the first thing a new user sees is what *would* be sent.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.browser.session import BrowserUnavailable
from app.config import Settings, get_settings
from app.db.base import session_scope
from app.db.models import (
    AnswerProvenance,
    Application,
    ApplicationAnswer,
    ApplicationArtifact,
    ApplicationStatus,
    AutoApplyRun,
    BatchStatus,
    CandidateProfile,
    Job,
    Resume,
    SourceName,
    SubmissionAttempt,
    SubmissionState,
    utcnow,
)
from app.db.repositories import AuditRepository, ProfileRepository, SavedAnswerRepository
from app.llm.base import LLMProvider
from app.logging_conf import get_logger
from app.services.application_prep import ApplicationPreparationService, profile_facts
from app.services.autoapply_control import (
    EmergencyStopActive,
    acquire_job_lock,
    breaker_state,
    is_emergency_stopped,
    lock_holder,
    platform_slot,
    record_breaker_outcome,
    record_event,
    release_job_lock,
    resolve_interrupted_attempt,
)
from app.services.batch import BatchSelection
from app.services.preflight import dispatched_today, effective_daily_cap, run_preflight
from app.services.redaction import mask_value
from app.services.tracking import (
    ApplicationTracker,
    AutomatedSubmissionBlocked,
    InvalidTransition,
    TransitionRequest,
    blocking_questions,
)
from app.submission import (
    AnswerValue,
    Attachment,
    CandidateIdentity,
    FilledForm,
    ResumeDocument,
    SubmissionAdapter,
    SubmissionResult,
    adapter_for_job,
    target_for_job,
)
from app.submission.forms import PendingQuestion
from app.submission.registry import BROWSER_TARGET_KEYS
from app.submission.states import (
    NEEDS_USER_STATES,
    TERMINAL_STATES,
    TRANSIENT_FAILURES,
    USER_ACTION_FAILURES,
    FailureCategory,
    submit_may_have_happened,
)

logger = get_logger(__name__)

_RETRYABLE_EXCEPTIONS = (OSError, TimeoutError, OperationalError)

#: States the worker will not pick up again. Composed from the authoritative sets rather
#: than listed, so adding a terminal state cannot leave this query behind and start
#: re-dispatching something already finished.
_NOT_PICKED_UP: frozenset[SubmissionState] = (
    TERMINAL_STATES | NEEDS_USER_STATES | {SubmissionState.SUBMISSION_IN_PROGRESS}
)

_ACTIVE_RUN_STATUSES = (BatchStatus.PENDING, BatchStatus.RUNNING, BatchStatus.PAUSED)

#: States of an earlier run's attempt that prove nothing reached the employer, so a new
#: run may try the job again — typically after the user answered the question it was
#: waiting on. Anything that pressed Submit (confirmed, unknown, or handed to the user
#: mid-submission) is absent and is therefore never re-queued.
_RETRY_IN_NEW_RUN: frozenset[SubmissionState] = frozenset(
    {
        SubmissionState.ELIGIBLE,
        SubmissionState.PREPARED,
        SubmissionState.READY_TO_SUBMIT,
        SubmissionState.BLOCKED_MISSING_INFO,
        SubmissionState.UNSUPPORTED_PLATFORM,
        SubmissionState.FAILED,
    }
)

#: States that mean an application was dispatched today, for the daily ceiling.
_DISPATCHED: frozenset[SubmissionState] = frozenset(
    {
        SubmissionState.SUBMITTED_CONFIRMED,
        SubmissionState.OUTCOME_UNKNOWN,
        SubmissionState.SUBMISSION_IN_PROGRESS,
        SubmissionState.REQUIRES_USER_ACTION,
    }
)

#: Freshness windows the product offers. Anything else is rejected rather than silently
#: rounded, because "jobs from the last 48 hours" is a claim shown to the user.
ALLOWED_AGE_HOURS: frozenset[int] = frozenset({24, 48, 72, 168, 336, 720})


@dataclass(slots=True)
class AutoApplyTargets:
    """The scope a single click authorises."""

    sources: list[SourceName] = field(default_factory=list)
    max_discover: int = 200
    max_submissions: int = 100
    max_age_hours: int = 48
    min_score: float = 70.0
    min_confidence: str = "medium"
    bands: list[str] = field(default_factory=lambda: ["high", "review"])
    titles: list[str] = field(default_factory=list)
    excluded_companies: list[str] = field(default_factory=list)
    concurrency: int = 4
    max_attempts: int = 2
    dry_run: bool = True
    include_cover_letter: bool = True
    #: Hard constraints, each enforced on its own regardless of score.
    role_families: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    remote_preference: str = "any"
    #: Years a listing may ask for beyond the candidate's own experience.
    experience_tolerance_years: float | None = 1.0
    #: Lower than the installation-wide cap when set; never higher.
    daily_cap: int | None = None
    #: Submission targets (``greenhouse``, ``lever``...) the run may use. Empty means all.
    platforms: list[str] = field(default_factory=list)
    #: The exact jobs the user approved in the preflight. Empty means "the whole plan".
    approved_job_ids: list[int] = field(default_factory=list)

    def normalized_age_hours(self) -> int:
        return self.max_age_hours if self.max_age_hours in ALLOWED_AGE_HOURS else 48

    def as_selection(self) -> BatchSelection:
        return BatchSelection(
            min_score=self.min_score,
            bands=list(self.bands),
            max_age_hours=self.normalized_age_hours(),
            min_confidence=self.min_confidence,
            titles=list(self.titles),
            sources=list(self.sources),
            excluded_companies=list(self.excluded_companies),
            limit=max(1, self.max_submissions),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "sources": [source.value for source in self.sources],
            "max_discover": self.max_discover,
            "max_submissions": self.max_submissions,
            "max_age_hours": self.normalized_age_hours(),
            "min_score": self.min_score,
            "min_confidence": self.min_confidence,
            "bands": list(self.bands),
            "titles": list(self.titles),
            "excluded_companies": list(self.excluded_companies),
            "concurrency": self.concurrency,
            "max_attempts": self.max_attempts,
            "dry_run": self.dry_run,
            "include_cover_letter": self.include_cover_letter,
            "role_families": list(self.role_families),
            "locations": list(self.locations),
            "remote_preference": self.remote_preference,
            "experience_tolerance_years": self.experience_tolerance_years,
            "daily_cap": self.daily_cap,
            "platforms": list(self.platforms),
            "approved_job_ids": list(self.approved_job_ids),
        }


@dataclass(slots=True)
class RunPreview:
    """What a run would do, computed without touching a provider.

    ``submittable`` is the number that matters and is almost always far below
    ``eligible``: it counts only the jobs whose provider authorises submission. Showing
    both is how the page avoids implying that every eligible job can be sent.
    """

    eligible: int = 0
    submittable: int = 0
    by_target: dict[str, int] = field(default_factory=dict)
    unsupported_reasons: dict[str, str] = field(default_factory=dict)
    job_ids: list[int] = field(default_factory=list)


def idempotency_key(profile_id: int, job_id: int) -> str:
    """Stable key for one profile applying to one job.

    Derived from the pair rather than from the attempt, so every retry of the same
    application presents the same key. A provider that honours it therefore cannot be made
    to create a duplicate by a resumed run, and the unique index on
    ``submission_attempt.idempotency_key`` catches it locally even if the provider does not.
    """
    digest = hashlib.sha256(f"{profile_id}:{job_id}".encode()).hexdigest()
    return f"ja-{digest[:32]}"


def preview(session: Session, profile: CandidateProfile, targets: AutoApplyTargets) -> RunPreview:
    """Resolve the eligible set and report how much of it can actually be submitted.

    A summary of :func:`~app.services.preflight.run_preflight`, so the count shown before a
    run and the queue the run builds can never disagree.
    """
    job_ids = list(run_preflight(session, profile, targets).queue_job_ids)
    result = RunPreview(eligible=len(job_ids), job_ids=job_ids)
    if not job_ids:
        return result

    jobs = session.scalars(select(Job).where(Job.id.in_(job_ids))).all()
    for job in jobs:
        target = target_for_job(job)
        result.by_target[target.key] = result.by_target.get(target.key, 0) + 1
        report = adapter_for_job(job).check_capability(job)
        if report.supported:
            result.submittable += 1
        else:
            result.unsupported_reasons.setdefault(target.key, report.reason)
    return result


#: Stop events for runs executing in this process, shared by every service instance so
#: the emergency stop and Pause reach a run started by a different request.
_STOP_EVENTS: dict[int, threading.Event] = {}
_STOP_EVENTS_LOCK = threading.Lock()


def _stop_event(run_id: int) -> threading.Event:
    with _STOP_EVENTS_LOCK:
        return _STOP_EVENTS.setdefault(run_id, threading.Event())


def signal_all_runs() -> None:
    """Wake every run executing in this process so it re-reads its flags at once."""
    with _STOP_EVENTS_LOCK:
        for event in _STOP_EVENTS.values():
            event.set()


@dataclass(slots=True)
class _RunState:
    """What one execution of a run remembers between attempts, in memory only."""

    #: Attempts left alone for this execution: lock held elsewhere, breaker open.
    skipped: set[int] = field(default_factory=set)
    dispatched: int = 0


def _category_for(error: BaseException) -> str:
    if isinstance(error, EmergencyStopActive):
        return FailureCategory.EMERGENCY_STOP
    name = type(error).__name__
    text = str(error).casefold()
    if (
        isinstance(error, BrowserUnavailable)
        or "target closed" in text
        or "has been closed" in text
    ):
        return FailureCategory.BROWSER_CRASH
    if isinstance(error, TimeoutError) or "timeout" in name.casefold() or "timeout" in text:
        return FailureCategory.TIMEOUT
    return FailureCategory.TRANSIENT


class AutoApplyService:
    """Creates and executes auto-apply runs."""

    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        session_factory: Callable[[], AbstractContextManager[Session]] | None = None,
    ) -> None:
        self._provider = provider
        self._session_factory = session_factory
        self._last_target = ""

    @property
    def _stop_events(self) -> dict[int, threading.Event]:
        return _STOP_EVENTS

    @contextmanager
    def _session(self) -> Iterator[Session]:
        factory = self._session_factory or session_scope
        with factory() as session:
            yield session

    # ---------------- lifecycle ----------------

    def create_run(
        self, session: Session, profile: CandidateProfile, targets: AutoApplyTargets
    ) -> AutoApplyRun:
        run = AutoApplyRun(
            profile_id=profile.id,
            status=BatchStatus.PENDING,
            dry_run=targets.dry_run,
            concurrency=max(1, min(16, targets.concurrency)),
            max_attempts=max(1, min(10, targets.max_attempts)),
            max_submissions=max(0, min(500, targets.max_submissions)),
            max_discover=max(0, min(500, targets.max_discover)),
            targets=targets.as_dict(),
            approved_job_ids=list(targets.approved_job_ids),
        )
        session.add(run)
        session.flush()
        AuditRepository(session).record(
            action="autoapply_run_created",
            entity_type="autoapply_run",
            entity_id=run.id,
            actor="user",
            detail={
                "dry_run": targets.dry_run,
                "max_submissions": run.max_submissions,
                "approved_jobs": len(targets.approved_job_ids),
            },
        )
        return run

    def request_pause(self, session: Session, run_id: int) -> None:
        run = session.get(AutoApplyRun, run_id)
        if run is None:
            return
        run.pause_requested = True
        if run.status is BatchStatus.RUNNING:
            run.status = BatchStatus.PAUSED
        event = _STOP_EVENTS.get(run_id)
        if event is not None:
            event.set()

    def request_cancel(self, session: Session, run_id: int) -> None:
        run = session.get(AutoApplyRun, run_id)
        if run is None:
            return
        run.cancel_requested = True
        run.status = BatchStatus.CANCELLING
        event = _STOP_EVENTS.get(run_id)
        if event is not None:
            event.set()

    def resume(self, session: Session, run_id: int) -> None:
        """Clear a pause so the run can be executed again.

        Does not clear ``cancel_requested``: a cancelled run is restarted by executing it
        again, which re-queues only its non-terminal attempts, and silently un-cancelling
        would make the Cancel button unreliable. An attempt left mid-dispatch by a worker
        that died is settled from its checkpoint first, so resuming cannot re-send it.
        """
        run = session.get(AutoApplyRun, run_id)
        if run is None:
            return
        for attempt in run.attempts:
            resolve_interrupted_attempt(attempt, "the run was resumed after it stopped")
        run.pause_requested = False
        if run.status in {BatchStatus.PAUSED, BatchStatus.INTERRUPTED}:
            run.status = BatchStatus.PENDING

    # ---------------- execution ----------------

    def execute(self, run_id: int, targets: AutoApplyTargets) -> AutoApplyRun:
        """Run every phase for ``run_id`` and return the refreshed run row."""
        event = _stop_event(run_id)
        event.clear()

        with self._session() as session:
            run = session.get(AutoApplyRun, run_id)
            if run is None:
                raise LookupError(f"no auto-apply run {run_id}")
            if is_emergency_stopped(session):
                run.status = BatchStatus.CANCELLED
                run.cancel_requested = True
                run.message = "Not started: the emergency stop is on. Clear it to run again."
                session.flush()
                session.refresh(run)
                session.expunge(run)
                return run
            run.status = BatchStatus.RUNNING
            run.pause_requested = False
            run.heartbeat_at = utcnow()
            profile = ProfileRepository(session).get_or_create_default()
            plan = run_preflight(session, profile, targets, exclude_run_id=run_id)
            run.discovered_count = plan.counts.total_discovered
            run.eligible_count = len(plan.queue_job_ids)
            run.preflight = plan.summary()
            self._queue(session, run, plan.queue_job_ids)
            session.flush()

        self._process(run_id, targets)

        with self._session() as session:
            run = session.get(AutoApplyRun, run_id)
            if run is None:
                raise LookupError(f"no auto-apply run {run_id}")
            self._finalise(session, run)
            session.flush()
            session.refresh(run)
            session.expunge(run)
            return run

    def _queue(self, session: Session, run: AutoApplyRun, job_ids: Sequence[int]) -> None:
        existing = {
            int(row)
            for row in session.scalars(
                select(SubmissionAttempt.job_id).where(SubmissionAttempt.autoapply_run_id == run.id)
            ).all()
        }
        for job_id in job_ids:
            if job_id in existing:
                continue
            key = idempotency_key(run.profile_id, job_id)
            earlier = session.scalars(
                select(SubmissionAttempt).where(SubmissionAttempt.idempotency_key == key)
            ).first()
            if earlier is not None:
                # The idempotency key is unique table-wide. A job whose earlier attempt
                # reached the employer — or might have — is never queued again: that is
                # the duplicate prevention. One that provably never left this machine
                # (waiting on an answer, unsupported at the time, or stopped before
                # Submit) is retried, with the old row keeping its history under a
                # retired key — unless it still belongs to another run that is active.
                if not _may_requeue(earlier):
                    continue
                owner = session.get(AutoApplyRun, earlier.autoapply_run_id)
                if (
                    owner is not None
                    and owner.id != run.id
                    and owner.status in _ACTIVE_RUN_STATUSES
                    and earlier.state not in TERMINAL_STATES
                ):
                    continue
                earlier.idempotency_key = f"{key}#retired-{earlier.id}"[:120]
                session.flush()
            attempt = SubmissionAttempt(
                autoapply_run_id=run.id,
                job_id=job_id,
                state=SubmissionState.ELIGIBLE,
                idempotency_key=key,
                checkpoint="queued",
            )
            try:
                with session.begin_nested():
                    session.add(attempt)
                    record_event(attempt, "checkpoint", "queued", f"queued by run {run.id}")
            except IntegrityError:
                continue

    def _process(self, run_id: int, targets: AutoApplyTargets) -> None:
        event = _stop_event(run_id)
        state = _RunState()

        while True:
            with self._session() as session:
                run = session.get(AutoApplyRun, run_id)
                if run is None or run.cancel_requested or run.pause_requested or event.is_set():
                    return
                if is_emergency_stopped(session):
                    run.cancel_requested = True
                    run.message = "Stopped by the emergency stop."
                    return
                run.heartbeat_at = utcnow()
                budget = run.max_submissions
                attempt_id, wait_s = self._next_attempt_id(
                    session, run_id, run.max_attempts, state.skipped
                )
            if attempt_id is None:
                if wait_s is None:
                    return
                # Only transient failures waiting out their backoff remain.
                self._wait(run_id, event, wait_s)
                continue
            if not targets.dry_run and state.dispatched >= budget:
                return
            if not targets.dry_run and self._daily_ceiling_reached(targets):
                logger.info("autoapply_daily_ceiling_reached", extra={"run_id": run_id})
                return

            self._last_target = ""
            sent = self._run_one(run_id, attempt_id, targets, state)
            if sent:
                state.dispatched += 1
                if self._last_target in BROWSER_TARGET_KEYS:
                    # A person does not submit forty forms a minute. The wait is
                    # interruptible, so Pause, Cancel and the emergency stop still take
                    # effect at once.
                    self._wait(run_id, event, self._between_applications_delay())

    def _wait(self, run_id: int, event: threading.Event, seconds: float) -> None:
        """Sleep interruptibly, keeping the run's heartbeat fresh while it waits."""
        deadline = time.monotonic() + max(0.0, seconds)
        while not event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            event.wait(min(remaining, 20.0))
            with self._session() as session:
                run = session.get(AutoApplyRun, run_id)
                if run is not None:
                    run.heartbeat_at = utcnow()

    def _daily_ceiling_reached(self, targets: AutoApplyTargets | None = None) -> bool:
        """Whether today's browser submissions have reached the effective daily cap."""
        settings = get_settings()
        if not settings.browser_submission_enabled:
            return False
        cap = effective_daily_cap(targets or AutoApplyTargets())
        if cap is None:
            return False
        with self._session() as session:
            count = dispatched_today(session, BROWSER_TARGET_KEYS)
        return count >= cap

    @staticmethod
    def _between_applications_delay() -> float:
        settings = get_settings()
        low = settings.browser_between_applications_min_s
        high = max(low, settings.browser_between_applications_max_s)
        return random.uniform(low, high) if high > 0 else 0.0

    def _next_attempt_id(
        self,
        session: Session,
        run_id: int,
        max_attempts: int,
        skipped: set[int] | None = None,
    ) -> tuple[int | None, float | None]:
        """The next attempt to carry, or ``(None, seconds)`` when only backoffs remain.

        A failed attempt comes back only if its failure is transient, its backoff has
        passed and its retry budget is not spent. An attempt caught mid-dispatch is never
        picked up: it is settled by recovery, from its checkpoint.
        """
        now = utcnow()
        statement = (
            select(SubmissionAttempt)
            .where(
                SubmissionAttempt.autoapply_run_id == run_id,
                SubmissionAttempt.state.notin_(sorted(_NOT_PICKED_UP)),
                SubmissionAttempt.attempts < max_attempts,
                SubmissionAttempt.idempotency_key.notlike("%#retired-%"),
            )
            .order_by(SubmissionAttempt.id)
        )
        earliest: float | None = None
        for attempt in session.scalars(statement).all():
            if skipped and attempt.id in skipped:
                continue
            if attempt.state is SubmissionState.FAILED:
                if (attempt.failure_category or FailureCategory.TRANSIENT) not in (
                    TRANSIENT_FAILURES
                ):
                    continue
                due = attempt.next_retry_at
                if due is not None and due > now:
                    wait = (due - now).total_seconds()
                    earliest = wait if earliest is None else min(earliest, wait)
                    continue
            return int(attempt.id), None
        return None, earliest

    def _run_one(
        self,
        run_id: int,
        attempt_id: int,
        targets: AutoApplyTargets,
        run_state: _RunState | None = None,
    ) -> bool:
        """Carry one attempt as far as it can go. Returns whether a dispatch happened."""
        settings = get_settings()
        run_state = run_state or _RunState()
        owner = f"run-{run_id}-{os.getpid()}"

        # Phase 0, in its own committed transaction before anything else writes: count the
        # attempt and take the job's lock. Counting first means a crash below can never
        # make an attempt free to retry forever.
        with self._session() as session:
            attempt = session.get(SubmissionAttempt, attempt_id)
            if attempt is None:
                return False
            job_id = attempt.job_id
            if not acquire_job_lock(session, job_id, owner, settings.job_lock_ttl_s):
                holder = lock_holder(session, job_id)
                attempt.failure_category = FailureCategory.LOCKED_ELSEWHERE
                attempt.detail = (
                    f"another worker ({holder.owner if holder else 'unknown'}) is applying to "
                    "this job right now; left for a later run"
                )
                record_event(attempt, "checkpoint", "lock_busy", attempt.detail)
                run_state.skipped.add(attempt_id)
                return False
            attempt.attempts += 1
            attempt.started_at = attempt.started_at or utcnow()
            attempt.next_retry_at = None
            if attempt.attempts > 1:
                record_event(attempt, "checkpoint", "retry", f"attempt {attempt.attempts}")

        started = time.monotonic()
        try:
            return self._run_locked(attempt_id, targets, run_state, started)
        finally:
            with self._session() as session:
                release_job_lock(session, job_id, owner)

    def _run_locked(
        self, attempt_id: int, targets: AutoApplyTargets, run_state: _RunState, started: float
    ) -> bool:
        settings = get_settings()
        with self._session() as session:
            attempt = session.get(SubmissionAttempt, attempt_id)
            if attempt is None:
                return False
            job = session.get(Job, attempt.job_id)
            profile = ProfileRepository(session).get_or_create_default()
            if job is None:
                attempt.state = SubmissionState.FAILED
                attempt.failure_category = FailureCategory.FORM_CHANGED
                attempt.detail = "the job row disappeared"
                attempt.finished_at = utcnow()
                return False

            adapter = adapter_for_job(job)
            attempt.target_key = adapter.target.key
            self._last_target = adapter.target.key
            if adapter.target.key in BROWSER_TARGET_KEYS:
                breaker = breaker_state(session, adapter.target.key)
                if breaker.open:
                    attempt.failure_category = FailureCategory.CIRCUIT_OPEN
                    attempt.detail = (
                        f"{adapter.target.display_name} is paused by its circuit breaker "
                        f"({breaker.reason}); this job stays prepared for a later run"
                    )
                    record_event(attempt, "checkpoint", "circuit_open", breaker.reason)
                    run_state.skipped.add(attempt_id)
                    attempt.attempts = max(0, attempt.attempts - 1)
                    return False
            dispatched = False
            try:
                dispatched = self._carry(session, attempt, job, profile, adapter, targets)
                return dispatched
            except Exception as error:  # noqa: BLE001 - one job must never end the run
                self._settle_exception(session, attempt, error)
                return attempt.state in _DISPATCHED
            finally:
                attempt.duration_ms = int((time.monotonic() - started) * 1000)
                self._after_attempt(session, attempt, adapter, settings)
                release = getattr(adapter, "release", None)
                if callable(release):
                    release(
                        job,
                        keep_open=attempt.state
                        in {SubmissionState.REQUIRES_USER_ACTION, SubmissionState.OUTCOME_UNKNOWN},
                    )

    def _settle_exception(
        self, session: Session, attempt: SubmissionAttempt, error: BaseException
    ) -> None:
        """Record an attempt that raised. Whether Submit may have been pressed decides it."""
        logger.warning(
            "autoapply_attempt_error",
            extra={"attempt_id": attempt.id, "reason": f"{type(error).__name__}: {error}"},
        )
        try:
            session.flush()
        except Exception:  # noqa: BLE001 - a broken transaction is rolled back to the checkpoint
            session.rollback()
            reloaded = session.get(SubmissionAttempt, attempt.id)
            if reloaded is not None:
                attempt = reloaded
        category = _category_for(error)
        record_event(attempt, "error", type(error).__name__, str(error)[:500])
        if attempt.state is SubmissionState.SUBMISSION_IN_PROGRESS and submit_may_have_happened(
            attempt.checkpoint
        ):
            attempt.state = SubmissionState.OUTCOME_UNKNOWN
            attempt.failure_category = FailureCategory.UNKNOWN_OUTCOME
            attempt.detail = (
                f"Submit may have been pressed when an error occurred ({type(error).__name__}). "
                "Not retried: check the employer's page or your email first."
            )
        elif attempt.state not in _DISPATCHED or (
            attempt.state is SubmissionState.SUBMISSION_IN_PROGRESS
        ):
            attempt.state = SubmissionState.FAILED
            attempt.failure_category = category
            attempt.detail = f"not submitted: {error}"
        attempt.finished_at = utcnow()
        if attempt.state is SubmissionState.OUTCOME_UNKNOWN and attempt.application_id:
            application = session.get(Application, attempt.application_id)
            if application is not None and application.status not in (
                ApplicationStatus.SUBMISSION_UNKNOWN,
                ApplicationStatus.SUBMITTED,
                ApplicationStatus.CONFIRMED,
            ):
                self._mark_application(
                    ApplicationTracker(session),
                    application,
                    ApplicationStatus.SUBMISSION_UNKNOWN,
                    attempt.target_key,
                    attempt.detail,
                    attempt,
                )

    def _after_attempt(
        self,
        session: Session,
        attempt: SubmissionAttempt,
        adapter: SubmissionAdapter,
        settings: Settings,
    ) -> None:
        """Backoff for transient failures, and the platform's circuit breaker."""
        if attempt.state is SubmissionState.FAILED and not attempt.failure_category:
            attempt.failure_category = FailureCategory.TRANSIENT
        if (
            attempt.state is SubmissionState.FAILED
            and attempt.failure_category in TRANSIENT_FAILURES
        ):
            delay = settings.retry_backoff_s * (2 ** max(0, attempt.attempts - 1))
            attempt.next_retry_at = utcnow() + timedelta(seconds=delay)
        if adapter.target.key not in BROWSER_TARGET_KEYS:
            return
        if attempt.state in (SubmissionState.ELIGIBLE, SubmissionState.BLOCKED_MISSING_INFO):
            return
        category = attempt.failure_category
        if attempt.state is SubmissionState.OUTCOME_UNKNOWN:
            category = FailureCategory.UNKNOWN_OUTCOME
        breaker = record_breaker_outcome(
            session,
            adapter.target.key,
            failure_category=category,
            succeeded=attempt.state is SubmissionState.SUBMITTED_CONFIRMED,
            threshold=settings.circuit_breaker_threshold,
        )
        if breaker.open:
            record_event(attempt, "checkpoint", "circuit_opened", breaker.reason)

    def _checkpoint(
        self, session: Session, attempt: SubmissionAttempt, name: str, detail: str = ""
    ) -> None:
        """Record and commit a milestone, so it survives the process dying right after."""
        if name == "submit_requested":
            # The last moment anything can still be stopped without ambiguity.
            if is_emergency_stopped(session):
                raise EmergencyStopActive("the emergency stop is on; Submit was not pressed")
            run = session.get(AutoApplyRun, attempt.autoapply_run_id)
            if run is not None:
                session.refresh(run, attribute_names=["cancel_requested", "pause_requested"])
                if run.cancel_requested:
                    raise EmergencyStopActive("the run was cancelled; Submit was not pressed")
        attempt.checkpoint = name
        record_event(attempt, "checkpoint", name, detail)
        run = session.get(AutoApplyRun, attempt.autoapply_run_id)
        if run is not None:
            run.heartbeat_at = utcnow()
        session.commit()

    def _carry(
        self,
        session: Session,
        attempt: SubmissionAttempt,
        job: Job,
        profile: CandidateProfile,
        adapter: SubmissionAdapter,
        targets: AutoApplyTargets,
    ) -> bool:
        """The attempt's phases, from capability check to dispatch."""
        report = adapter.check_capability(job)
        if not report.supported:
            attempt.state = SubmissionState.UNSUPPORTED_PLATFORM
            attempt.detail = report.reason
            attempt.submitted_url = job.url or ""
            attempt.finished_at = utcnow()
            return False
        attempt.checkpoint = "capability_checked"

        application = self._prepare(session, job, profile, targets)
        if application is None:
            attempt.state = SubmissionState.FAILED
            attempt.failure_category = FailureCategory.TRANSIENT
            attempt.detail = "the application could not be prepared"
            attempt.finished_at = utcnow()
            return False

        attempt.application_id = application.id
        attempt.state = SubmissionState.PREPARED
        attempt.checkpoint = "prepared"

        # An application the review queue says is incomplete is not sent, even if the
        # provider's own form happens not to ask for the missing answer. Otherwise a
        # confirmed submission would exist for an application the tracker still shows
        # as awaiting the user, and the two records would disagree about what went out.
        outstanding = blocking_questions(application)
        if outstanding:
            attempt.state = SubmissionState.BLOCKED_MISSING_INFO
            attempt.failure_category = FailureCategory.MISSING_ANSWERS
            attempt.detail = f"{len(outstanding)} question(s) still need your answer: " + "; ".join(
                outstanding[:3]
            )
            attempt.finished_at = utcnow()
            return False

        identity = CandidateIdentity.from_profile(profile)
        problems = adapter.validate_candidate(job, identity)
        if problems:
            attempt.state = SubmissionState.BLOCKED_MISSING_INFO
            attempt.failure_category = FailureCategory.MISSING_ANSWERS
            attempt.detail = "; ".join(problems)
            attempt.finished_at = utcnow()
            return False

        form = adapter.prepare_fields(job, identity, _answers_for(session, application))
        blocked = getattr(adapter, "blocked_condition", None)
        condition = blocked(job) if callable(blocked) else None
        if condition is not None:
            category, reason = condition
            attempt.failure_category = category
            attempt.detail = reason
            attempt.finished_at = utcnow()
            if category in USER_ACTION_FAILURES:
                attempt.state = SubmissionState.REQUIRES_USER_ACTION
                record_event(attempt, "user_action", category, reason)
            else:
                attempt.state = SubmissionState.FAILED
                record_event(attempt, "browser", "form_unavailable", reason)
            return False
        attempt.checkpoint = "form_inspected"
        if form.questions:
            # Questions the employer's own form asks that nothing on file answers. Each is
            # raised into the Action inbox once; answering it there fills this
            # application and every later form asking the same thing.
            _raise_form_questions(application, form.questions, adapter.target.display_name)
        if not form.is_complete:
            attempt.state = SubmissionState.BLOCKED_MISSING_INFO
            attempt.failure_category = FailureCategory.MISSING_ANSWERS
            attempt.detail = "; ".join(form.blocking)
            attempt.finished_at = utcnow()
            return False

        document = _resume_document(
            session, application, prefer_original=adapter.target.key in BROWSER_TARGET_KEYS
        )
        attachment = adapter.attach_resume(job, document)
        if not attachment.ok and report.accepts_resume_upload:
            attempt.state = SubmissionState.BLOCKED_MISSING_INFO
            attempt.failure_category = FailureCategory.UPLOAD_FAILED
            attempt.detail = attachment.reason
            attempt.finished_at = utcnow()
            return False

        attempt.state = SubmissionState.READY_TO_SUBMIT
        attempt.answers_sent = _answers_sent(adapter, job, form)
        if targets.dry_run:
            attempt.detail = "ready to submit; this was a dry run, so nothing was sent"
            preview_fill = getattr(adapter, "preview_fill", None)
            if callable(preview_fill):
                shot = preview_fill(
                    job, form, attachment, label=f"run{attempt.autoapply_run_id}-job{job.id}"
                )
                if shot:
                    attempt.detail += f". The form was filled without submitting: {shot}"
                    if shot.endswith(".png"):
                        attempt.evidence_path = shot
            attempt.finished_at = utcnow()
            return False

        duplicate = _already_dispatched_elsewhere(session, attempt, application)
        if duplicate:
            attempt.state = SubmissionState.FAILED
            attempt.failure_category = FailureCategory.DUPLICATE_PREVENTED
            attempt.detail = f"not submitted: {duplicate}"
            attempt.finished_at = utcnow()
            record_event(attempt, "checkpoint", "duplicate_prevented", duplicate)
            return False

        key = attempt.idempotency_key or idempotency_key(profile.id, job.id)
        attempt.artifacts = _snapshot_sent(session, application, profile, document, form)
        slot = (
            platform_slot(adapter.target.key, get_settings().browser_max_concurrent_per_platform)
            if adapter.target.key in BROWSER_TARGET_KEYS
            else None
        )
        if slot is not None and not slot.acquire(timeout=300):
            attempt.state = SubmissionState.FAILED
            attempt.failure_category = FailureCategory.TRANSIENT
            attempt.detail = f"not submitted: {adapter.target.display_name} was busy for 5 minutes"
            attempt.finished_at = utcnow()
            return False
        try:
            attempt.state = SubmissionState.SUBMISSION_IN_PROGRESS
            hooked = hasattr(adapter, "checkpoint_hook")
            if hooked:
                session.commit()
                adapter.checkpoint_hook = (  # type: ignore[attr-defined]
                    lambda name, detail: self._checkpoint(session, attempt, name, detail)
                )
            else:
                # One request is the whole submission, so it may have arrived the moment
                # it is sent: the checkpoint says so before it is.
                self._checkpoint(session, attempt, "submit_requested", "sending the request")
            try:
                result = self._dispatch(adapter, job, form, attachment, key)
            finally:
                if hooked:
                    adapter.checkpoint_hook = None  # type: ignore[attr-defined]
        finally:
            if slot is not None:
                slot.release()
        self._record(session, attempt, application, adapter, result)
        return True

    def _dispatch(
        self,
        adapter: SubmissionAdapter,
        job: Job,
        form: FilledForm,
        attachment: Attachment,
        key: str,
    ) -> SubmissionResult:
        try:
            result = adapter.submit(job, form, attachment, idempotency_key=key)
        except _RETRYABLE_EXCEPTIONS as error:
            if hasattr(adapter, "checkpoint_hook"):
                # A browser adapter's own steps decide; the checkpoint tells the handler
                # whether Submit may have been pressed.
                raise
            return SubmissionResult(
                state=SubmissionState.FAILED,
                reason=f"the provider could not be reached: {error}",
                completed_at=utcnow(),
                response_metadata={"failure_category": FailureCategory.TRANSIENT},
            )
        if result.state is SubmissionState.SUBMISSION_IN_PROGRESS:
            return adapter.verify_submission(result)
        return result

    def _record(
        self,
        session: Session,
        attempt: SubmissionAttempt,
        application: Application,
        adapter: SubmissionAdapter,
        result: SubmissionResult,
    ) -> None:
        metadata = dict(result.response_metadata)
        attempt.state = result.state
        attempt.detail = result.reason
        attempt.confirmation_id = result.confirmation_id
        attempt.provider_reference = result.provider_reference
        attempt.submitted_url = result.submitted_url
        attempt.resume_sha256 = result.resume_sha256 or attempt.resume_sha256
        attempt.response_metadata = metadata
        attempt.finished_at = result.completed_at or utcnow()
        attempt.failure_category = str(metadata.get("failure_category") or "")
        screenshot = str(metadata.get("screenshot") or "")
        if screenshot:
            attempt.evidence_path = screenshot
            record_event(attempt, "evidence", "screenshot", Path(screenshot).name)
        if result.is_confirmed:
            evidence = str(metadata.get("evidence") or result.reason)
            final_url = str(metadata.get("final_url") or result.submitted_url)
            attempt.confirmation_evidence = f"{evidence} — {final_url}".strip(" —")
        if submit_may_have_happened(attempt.checkpoint) or result.state in (
            SubmissionState.SUBMITTED_CONFIRMED,
            SubmissionState.OUTCOME_UNKNOWN,
        ):
            attempt.checkpoint = "outcome_read"
        record_event(attempt, "checkpoint", f"outcome:{result.state.value}", result.reason)
        if result.state is SubmissionState.REQUIRES_USER_ACTION:
            record_event(
                attempt, "user_action", attempt.failure_category or "needs_you", result.reason
            )

        tracker = ApplicationTracker(session)
        if result.state is SubmissionState.OUTCOME_UNKNOWN or (
            result.state is SubmissionState.REQUIRES_USER_ACTION
            and submit_may_have_happened(attempt.checkpoint)
        ):
            # The employer may hold this application. The tracker says so, which also keeps
            # every later run and the preflight from treating the job as untouched.
            self._mark_application(
                tracker,
                application,
                ApplicationStatus.SUBMISSION_UNKNOWN,
                adapter.target.key,
                result.reason,
                attempt,
            )
            return
        if not result.is_confirmed:
            return

        evidence = f"{adapter.target.display_name} confirmation {result.confirmation_id}"
        for target in (ApplicationStatus.APPROVED, ApplicationStatus.SUBMITTED):
            try:
                application.user_approved = True
                tracker.transition(
                    application,
                    TransitionRequest(
                        target,
                        actor="agent",
                        submitted_by=f"joborbit-autoapply/{adapter.target.key}",
                        detail=result.reason,
                        confirmation_evidence=evidence,
                        submission_target=adapter.target.key,
                        confirmation_id=result.confirmation_id,
                    ),
                )
            except (InvalidTransition, AutomatedSubmissionBlocked) as error:
                attempt.detail = f"{result.reason} (tracker: {error})"
                return
        try:
            tracker.transition(
                application,
                TransitionRequest(
                    ApplicationStatus.CONFIRMED,
                    actor="agent",
                    submitted_by=f"joborbit-autoapply/{adapter.target.key}",
                    confirmation_evidence=attempt.confirmation_evidence or evidence,
                    submission_target=adapter.target.key,
                    confirmation_id=result.confirmation_id,
                ),
            )
        except (InvalidTransition, AutomatedSubmissionBlocked) as error:
            attempt.detail = f"{result.reason} (tracker: {error})"

    @staticmethod
    def _mark_application(
        tracker: ApplicationTracker,
        application: Application,
        status: ApplicationStatus,
        target_key: str,
        reason: str,
        attempt: SubmissionAttempt,
    ) -> None:
        path = [ApplicationStatus.APPROVED, status]
        if application.status is ApplicationStatus.APPROVED:
            path = [status]
        try:
            application.user_approved = True
            for target in path:
                tracker.transition(
                    application,
                    TransitionRequest(
                        target,
                        actor="agent",
                        detail=f"{target_key}: {reason}"[:500],
                    ),
                )
        except (InvalidTransition, AutomatedSubmissionBlocked) as error:
            attempt.detail = f"{reason} (tracker: {error})"

    def _prepare(
        self,
        session: Session,
        job: Job,
        profile: CandidateProfile,
        targets: AutoApplyTargets,
    ) -> Application | None:
        service = ApplicationPreparationService(session, self._provider)
        try:
            prepared = service.prepare(
                job, profile, include_cover_letter=targets.include_cover_letter
            )
        except Exception as error:  # noqa: BLE001 - one job must not end the run
            logger.warning(
                "autoapply_prepare_failed",
                extra={"job_id": job.id, "reason": str(error)},
            )
            return None
        return prepared.application

    def _finalise(self, session: Session, run: AutoApplyRun) -> None:
        counts: dict[SubmissionState, int] = {}
        for attempt in session.scalars(
            select(SubmissionAttempt).where(SubmissionAttempt.autoapply_run_id == run.id)
        ).all():
            counts[attempt.state] = counts.get(attempt.state, 0) + 1

        run.prepared_count = sum(
            counts.get(state, 0)
            for state in (
                SubmissionState.PREPARED,
                SubmissionState.READY_TO_SUBMIT,
                SubmissionState.SUBMISSION_IN_PROGRESS,
                SubmissionState.SUBMITTED_CONFIRMED,
                SubmissionState.OUTCOME_UNKNOWN,
            )
        )
        run.confirmed_count = counts.get(SubmissionState.SUBMITTED_CONFIRMED, 0)
        run.blocked_count = counts.get(SubmissionState.BLOCKED_MISSING_INFO, 0)
        run.needs_user_count = counts.get(SubmissionState.REQUIRES_USER_ACTION, 0)
        run.unsupported_count = counts.get(SubmissionState.UNSUPPORTED_PLATFORM, 0)
        run.failed_count = counts.get(SubmissionState.FAILED, 0)
        run.unknown_count = counts.get(SubmissionState.OUTCOME_UNKNOWN, 0)
        run.heartbeat_at = utcnow()

        if run.cancel_requested:
            run.status = BatchStatus.CANCELLED
        elif run.pause_requested:
            run.status = BatchStatus.PAUSED
        elif run.failed_count:
            run.status = BatchStatus.COMPLETED_WITH_ERRORS
        else:
            run.status = BatchStatus.COMPLETED

        if run.status in {
            BatchStatus.COMPLETED,
            BatchStatus.COMPLETED_WITH_ERRORS,
            BatchStatus.CANCELLED,
        }:
            run.finished_at = run.finished_at or utcnow()
        stopped = (
            " Stopped by the emergency stop." if "emergency stop" in (run.message or "") else ""
        )
        run.message = (
            f"{run.confirmed_count} confirmed, {run.prepared_count} prepared, "
            f"{run.unsupported_count} on platforms that permit no automated submission, "
            f"{run.blocked_count} waiting on an answer, {run.unknown_count} unverified" + stopped
        )


def _may_requeue(earlier: SubmissionAttempt) -> bool:
    """Whether a job's earlier attempt proves nothing reached the employer."""
    if earlier.state in _RETRY_IN_NEW_RUN:
        return True
    # Handed to the user before anything was typed (a CAPTCHA on arrival, a sign-in page)
    # is also provably unsent, so a later run may try again.
    return earlier.state is SubmissionState.REQUIRES_USER_ACTION and not (
        submit_may_have_happened(earlier.checkpoint)
    )


def _already_dispatched_elsewhere(
    session: Session, attempt: SubmissionAttempt, application: Application
) -> str:
    """Why this job must not be submitted now because it already was, or ``""``.

    Checked immediately before dispatch, after the job lock is held, so it sees anything
    another run or the user recorded since this run was planned.
    """
    # Re-read, not trusted from memory: the user may have recorded a submission from
    # another screen while this attempt was being prepared.
    session.refresh(application, attribute_names=["status"])
    if application.status in (
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.CONFIRMED,
        ApplicationStatus.SUBMISSION_UNKNOWN,
    ):
        return f"the application is already recorded as {application.status.value.lower()}"
    others = session.scalars(
        select(SubmissionAttempt).where(
            SubmissionAttempt.job_id == attempt.job_id,
            SubmissionAttempt.id != attempt.id,
        )
    ).all()
    for other in others:
        if other.state in (
            SubmissionState.SUBMITTED_CONFIRMED,
            SubmissionState.OUTCOME_UNKNOWN,
            SubmissionState.SUBMISSION_IN_PROGRESS,
        ) or (
            other.state is SubmissionState.REQUIRES_USER_ACTION
            and submit_may_have_happened(other.checkpoint)
        ):
            return (
                f"attempt {other.id} in run {other.autoapply_run_id} already reached "
                f"{other.state.value}"
            )
    return ""


def _answers_sent(adapter: SubmissionAdapter, job: Job, form: FilledForm) -> dict[str, object]:
    """What will be typed, keyed by the question as the form words it. Sensitive values
    are masked here; the exact values are kept in the locked answers artifact."""
    labels: dict[str, tuple[str, bool]] = {}
    try:
        spec = adapter.inspect_application(job)
        for item in spec.fields:
            labels[item.name] = (item.label or item.name, bool(item.sensitive))
    except Exception:  # noqa: BLE001 - labels are a nicety; the values are what matter
        labels = {}
    sent: dict[str, object] = {}
    for name, value in form.values.items():
        label, sensitive = labels.get(name, (name, False))
        sent[label[:200]] = mask_value(value) if sensitive else value[:500]
    for name, ticked in form.checked.items():
        label, _sensitive = labels.get(name, (name, False))
        sent[label[:200]] = "ticked" if ticked else "left unticked"
    return sent


def _snapshot_sent(
    session: Session,
    application: Application,
    profile: CandidateProfile,
    document: ResumeDocument,
    form: FilledForm,
) -> dict[str, object]:
    """Lock the exact material this dispatch sends, and return the artifact ids.

    The resume file itself stays where the user uploaded it; its name, size and hash are
    recorded so the bytes sent can be matched later. Answers and the profile facts used
    are stored verbatim. Every artifact is locked: from here on it is the record of what
    an employer received, and the model refuses to change or delete it.
    """
    now = utcnow()
    entries: list[tuple[str, str, str]] = [
        (
            "resume_file",
            document.filename,
            json.dumps(
                {
                    "filename": document.filename,
                    "bytes": document.byte_size,
                    "sha256": document.content_sha256
                    or hashlib.sha256(document.content).hexdigest(),
                },
                sort_keys=True,
            ),
        ),
        (
            "screening_answers",
            f"{len(form.values) + len(form.checked)} answers",
            json.dumps({"values": form.values, "checked": form.checked}, sort_keys=True),
        ),
        (
            "profile_snapshot",
            "profile facts used",
            json.dumps(profile_facts(profile), sort_keys=True),
        ),
    ]
    ids: dict[str, object] = {}
    for kind, label, content in entries:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        artifact = session.scalars(
            select(ApplicationArtifact).where(
                ApplicationArtifact.application_id == application.id,
                ApplicationArtifact.kind == kind,
                ApplicationArtifact.content_sha256 == digest,
            )
        ).first()
        if artifact is None:
            artifact = ApplicationArtifact(
                application_id=application.id,
                kind=kind,
                label=label[:200],
                content=content,
                content_sha256=digest,
                byte_size=len(content.encode("utf-8")),
            )
            session.add(artifact)
            session.flush()
        if artifact.locked_at is None:
            artifact.locked_at = now
        ids[kind] = artifact.id
    for kind in ("cover_letter", "resume_variant"):
        latest = session.scalars(
            select(ApplicationArtifact)
            .where(
                ApplicationArtifact.application_id == application.id,
                ApplicationArtifact.kind == kind,
            )
            .order_by(ApplicationArtifact.id.desc())
            .limit(1)
        ).first()
        if latest is not None:
            if latest.locked_at is None:
                latest.locked_at = now
            ids[kind] = latest.id
    session.flush()
    return ids


def _answers_for(session: Session, application: Application) -> dict[str, AnswerValue]:
    """Everything available to fill a provider's form, for this one application.

    Two sources, in increasing precedence. The **answer bank** comes first, because a
    provider asks for fields no application question covers — an attestation tick box, or
    a work-authorization question whose wording is its own. Answering such a field once
    should fill it on every later application, which is what the bank is for. The
    **application's own answers** then override, because they were prepared against this
    specific job.

    Provenance travels with every value, so the form engine still refuses a generated
    answer for a sensitive field regardless of which source supplied it.
    """
    values: dict[str, AnswerValue] = {}
    banked: dict[str, str] = {}
    for entry in SavedAnswerRepository(session).list(application.profile_id):
        banked[entry.question_key] = entry.answer or ""
        values[entry.question_key] = AnswerValue(
            value=entry.answer or "",
            provenance=entry.provenance,
            requires_user_input=False,
        )
    for answer in application.answers:
        key = answer.question_key
        alternative = banked.get(key, "")
        value = AnswerValue(
            value=answer.answer or "",
            provenance=answer.provenance,
            requires_user_input=answer.requires_user_input,
            alternatives=(alternative,) if alternative else (),
        )
        if key and not value.value.strip() and key in values:
            # An application answer still awaiting the user must not overwrite a banked
            # one: the bank is where the user already answered this exact question.
            continue
        if key:
            values[key] = value
        values.setdefault(answer.question, value)
    if (application.cover_letter or "").strip() and "cover_letter" not in values:
        # Prepared for this job from the profile; never sensitive, so a form's cover-letter
        # box may take it whichever way it was drafted.
        generated = (application.cover_letter_generated_by or "").casefold()
        values["cover_letter"] = AnswerValue(
            value=application.cover_letter,
            provenance=AnswerProvenance.AI_DRAFT
            if "llm" in generated or "ai" in generated
            else AnswerProvenance.RESUME_EXTRACTED,
        )
    return values


def _resume_document(
    session: Session, application: Application, *, prefer_original: bool = False
) -> ResumeDocument:
    """Build the upload for this application.

    A real employer form gets the **resume file the user uploaded** (their PDF or DOCX),
    because that is the document a recruiter expects to open; ``prefer_original`` selects
    it. Otherwise the resume variant snapshotted for this application is used, which is
    what the local test server receives. Either way the hash recorded on the attempt is of
    the exact bytes sent.
    """
    if prefer_original:
        original = _original_resume(session, application.profile_id)
        if original is not None:
            return original
    artifact = session.scalars(
        select(ApplicationArtifact)
        .where(
            ApplicationArtifact.application_id == application.id,
            ApplicationArtifact.kind == "resume_variant",
        )
        .order_by(ApplicationArtifact.id.desc())
        .limit(1)
    ).first()
    if artifact is None:
        return ResumeDocument(filename="resume.txt", content=b"", content_sha256="")
    content = (artifact.content or "").encode("utf-8")
    return ResumeDocument(
        filename=f"{(artifact.label or 'resume').replace(' ', '_')}.txt",
        content=content,
        content_sha256=artifact.content_sha256 or hashlib.sha256(content).hexdigest(),
    )


def _original_resume(session: Session, profile_id: int) -> ResumeDocument | None:
    """The primary uploaded resume file, or the newest one, if it is still on disk."""
    rows = session.scalars(
        select(Resume)
        .where(Resume.profile_id == profile_id)
        .order_by(Resume.is_primary.desc(), Resume.id.desc())
    ).all()
    for row in rows:
        path = Path(row.stored_path or "")
        if path.suffix.lower() not in {".pdf", ".docx", ".doc"} or not path.is_file():
            continue
        content = path.read_bytes()
        return ResumeDocument(
            filename=row.original_filename or path.name,
            content=content,
            content_sha256=hashlib.sha256(content).hexdigest(),
        )
    return None


def _raise_form_questions(
    application: Application, questions: Sequence[PendingQuestion], provider: str
) -> None:
    """Add each unanswered form question to the application, which puts it in the inbox."""
    present = {answer.question_key for answer in application.answers if answer.question_key}
    for question in questions:
        if question.question_key in present:
            continue
        present.add(question.question_key)
        application.answers.append(
            ApplicationAnswer(
                question=question.question,
                question_key=question.question_key,
                answer="",
                provenance=AnswerProvenance.NEEDS_USER_INPUT,
                is_sensitive=question.sensitive,
                requires_user_input=True,
                flag_reason=f"asked by the employer's {provider} application form"[:300],
                source_field=f"form:{provider}"[:100],
            )
        )


__all__ = [
    "ALLOWED_AGE_HOURS",
    "signal_all_runs",
    "AutoApplyService",
    "AutoApplyTargets",
    "RunPreview",
    "idempotency_key",
    "preview",
]
