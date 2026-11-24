"""Safety controls around auto-apply runs.

Five mechanisms, each small, each durable in the database so they survive a restart:

**Job locks.** At most one worker may be submitting to a given job at a time, across runs
and processes. The lock is a row keyed by the job, so a second insert fails in the
database rather than relying on two threads agreeing. A lock carries a lease; one held by
a worker that died can be taken over once the lease has run out, never before.

**Circuit breakers.** Repeated failures on one platform (pages failing to load, CAPTCHAs
appearing, outcomes that cannot be read) usually mean something changed on the platform's
side. After ``JA_CIRCUIT_BREAKER_THRESHOLD`` consecutive failures the platform's breaker
opens and its remaining jobs are left prepared instead of attempted. It closes after a
cooldown or when the user resets it.

**Emergency stop.** One switch that cancels every active run, refuses new ones, and is
checked between browser steps — including immediately before Submit is pressed — until
the user clears it.

**Crash recovery.** A run whose worker stopped heartbeating is marked interrupted. Any of
its attempts caught mid-dispatch is resolved from its checkpoint: if Submit may have been
pressed it becomes ``OUTCOME_UNKNOWN`` (never retried); if not, it is a transient failure
that may be retried safely.

**Evidence retention.** Screenshots, staged resume copies and browser events older than
``JA_EVIDENCE_RETENTION_DAYS`` are deleted.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    AutoApplyRun,
    BatchStatus,
    JobLock,
    RuntimeFlag,
    SubmissionAttempt,
    SubmissionEvent,
    SubmissionState,
    utcnow,
)
from app.logging_conf import get_logger
from app.services.redaction import redact
from app.submission.states import FailureCategory, submit_may_have_happened

logger = get_logger(__name__)

EMERGENCY_STOP_KEY = "emergency_stop"
CIRCUIT_PREFIX = "circuit:"
#: How long an open breaker stays open before the platform is tried again.
CIRCUIT_COOLDOWN = timedelta(minutes=30)

#: Outcomes that count against a platform's breaker. Job-specific outcomes (a closed
#: posting, a wrong page, a missing answer) say nothing about the platform and are neutral.
_BREAKER_FAILURES = frozenset(
    {
        FailureCategory.TRANSIENT,
        FailureCategory.BROWSER_CRASH,
        FailureCategory.TIMEOUT,
        FailureCategory.UPLOAD_FAILED,
        FailureCategory.FORM_CHANGED,
        FailureCategory.VALIDATION_REJECTED,
        FailureCategory.CAPTCHA,
        FailureCategory.MFA,
        FailureCategory.UNKNOWN_OUTCOME,
    }
)

_ACTIVE = (BatchStatus.PENDING, BatchStatus.RUNNING, BatchStatus.PAUSED, BatchStatus.CANCELLING)


class EmergencyStopActive(RuntimeError):
    """Raised at a checkpoint when the emergency stop is on. Submit is never pressed."""


# --------------------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------------------


def record_event(attempt: SubmissionAttempt, kind: str, name: str, detail: str = "") -> None:
    """Append one redacted event to an attempt's history."""
    attempt.events.append(
        SubmissionEvent(kind=kind[:40], name=name[:80], detail=redact(detail)[:2000])
    )


# --------------------------------------------------------------------------------------
# Runtime flags
# --------------------------------------------------------------------------------------


def _flag(session: Session, key: str) -> RuntimeFlag | None:
    return session.get(RuntimeFlag, key)


def _set_flag(session: Session, key: str, value: dict[str, Any]) -> None:
    row = _flag(session, key)
    if row is None:
        session.add(RuntimeFlag(key=key, value=value))
    else:
        row.value = value
        row.updated_at = utcnow()
    session.flush()


def emergency_stop_state(session: Session) -> dict[str, Any] | None:
    row = _flag(session, EMERGENCY_STOP_KEY)
    if row is None or not (row.value or {}).get("active"):
        return None
    return dict(row.value)


def is_emergency_stopped(session: Session) -> bool:
    return emergency_stop_state(session) is not None


def engage_emergency_stop(session: Session, reason: str = "") -> list[int]:
    """Turn the stop on and cancel every active run. Returns the cancelled run ids."""
    _set_flag(
        session,
        EMERGENCY_STOP_KEY,
        {"active": True, "at": utcnow().isoformat(), "reason": redact(reason)[:300]},
    )
    cancelled: list[int] = []
    for run in session.scalars(select(AutoApplyRun).where(AutoApplyRun.status.in_(_ACTIVE))).all():
        run.cancel_requested = True
        run.status = (
            BatchStatus.CANCELLING if run.status is BatchStatus.RUNNING else (BatchStatus.CANCELLED)
        )
        cancelled.append(run.id)
    session.flush()
    logger.warning("autoapply_emergency_stop", extra={"runs": cancelled})
    return cancelled


def clear_emergency_stop(session: Session) -> None:
    _set_flag(session, EMERGENCY_STOP_KEY, {"active": False, "cleared_at": utcnow().isoformat()})


# --------------------------------------------------------------------------------------
# Circuit breakers
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class BreakerState:
    target: str
    consecutive_failures: int = 0
    open: bool = False
    opened_at: datetime | None = None
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "consecutive_failures": self.consecutive_failures,
            "open": self.open,
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
            "reason": self.reason,
        }


def breaker_state(session: Session, target: str, *, now: datetime | None = None) -> BreakerState:
    row = _flag(session, CIRCUIT_PREFIX + target)
    value = dict(row.value) if row is not None else {}
    opened_raw = value.get("opened_at")
    opened_at = datetime.fromisoformat(opened_raw) if isinstance(opened_raw, str) else None
    state = BreakerState(
        target=target,
        consecutive_failures=int(value.get("consecutive_failures") or 0),
        open=bool(value.get("open")),
        opened_at=opened_at,
        reason=str(value.get("reason") or ""),
    )
    if state.open and opened_at is not None and (now or utcnow()) - opened_at > CIRCUIT_COOLDOWN:
        # Half-open: the cooldown passed, so the next attempt is allowed; one more failure
        # opens it again straight away because the counter is kept at the threshold.
        state.open = False
    return state


def record_breaker_outcome(
    session: Session, target: str, *, failure_category: str, succeeded: bool, threshold: int
) -> BreakerState:
    """Update a platform's breaker after one attempt. Neutral outcomes leave it alone."""
    state = breaker_state(session, target)
    if succeeded:
        state = BreakerState(target=target)
    elif failure_category in _BREAKER_FAILURES:
        state.consecutive_failures += 1
        if state.consecutive_failures >= threshold and not state.open:
            state.open = True
            state.opened_at = utcnow()
            state.reason = (
                f"{state.consecutive_failures} consecutive failures "
                f"(last: {failure_category}); paused for "
                f"{int(CIRCUIT_COOLDOWN.total_seconds() // 60)} minutes"
            )
            logger.warning(
                "autoapply_circuit_opened", extra={"target": target, "reason": state.reason}
            )
    else:
        return state
    _set_flag(session, CIRCUIT_PREFIX + target, state.as_dict())
    return state


def reset_breaker(session: Session, target: str) -> None:
    _set_flag(session, CIRCUIT_PREFIX + target, BreakerState(target=target).as_dict())


def all_breakers(session: Session) -> list[BreakerState]:
    rows = session.scalars(
        select(RuntimeFlag).where(RuntimeFlag.key.like(f"{CIRCUIT_PREFIX}%"))
    ).all()
    return [breaker_state(session, row.key[len(CIRCUIT_PREFIX) :]) for row in rows]


# --------------------------------------------------------------------------------------
# Job locks and per-platform concurrency
# --------------------------------------------------------------------------------------


def acquire_job_lock(session: Session, job_id: int, owner: str, ttl_s: int) -> bool:
    """Take the lock for ``job_id``. Must be called in a session that commits at once."""
    now = utcnow()
    expires = now + timedelta(seconds=ttl_s)
    try:
        with session.begin_nested():
            session.add(JobLock(job_id=job_id, owner=owner, acquired_at=now, expires_at=expires))
        return True
    except IntegrityError:
        pass
    taken = session.execute(
        update(JobLock)
        .where(JobLock.job_id == job_id, (JobLock.expires_at < now) | (JobLock.owner == owner))
        .values(owner=owner, acquired_at=now, expires_at=expires)
    )
    return bool(getattr(taken, "rowcount", 0))


def release_job_lock(session: Session, job_id: int, owner: str) -> None:
    session.execute(delete(JobLock).where(JobLock.job_id == job_id, JobLock.owner == owner))


def lock_holder(session: Session, job_id: int) -> JobLock | None:
    return session.get(JobLock, job_id)


_platform_lock = threading.Lock()
_platform_slots: dict[str, threading.BoundedSemaphore] = {}


def platform_slot(target: str, size: int) -> threading.BoundedSemaphore:
    """The in-process semaphore limiting concurrent submissions to one platform."""
    with _platform_lock:
        slot = _platform_slots.get(target)
        if slot is None:
            slot = threading.BoundedSemaphore(max(1, size))
            _platform_slots[target] = slot
        return slot


# --------------------------------------------------------------------------------------
# Crash recovery
# --------------------------------------------------------------------------------------


def resolve_interrupted_attempt(attempt: SubmissionAttempt, why: str) -> None:
    """Settle an attempt whose worker stopped mid-dispatch, from its checkpoint alone."""
    if attempt.state is not SubmissionState.SUBMISSION_IN_PROGRESS:
        return
    if submit_may_have_happened(attempt.checkpoint):
        attempt.state = SubmissionState.OUTCOME_UNKNOWN
        attempt.failure_category = FailureCategory.UNKNOWN_OUTCOME
        attempt.detail = (
            f"{why} after Submit may have been pressed. It will not be retried: check the "
            "employer's page or your email, then record what happened."
        )
        record_event(attempt, "recovery", "marked_outcome_unknown", why)
    else:
        attempt.state = SubmissionState.FAILED
        attempt.failure_category = FailureCategory.BROWSER_CRASH
        attempt.detail = f"{why} before Submit was pressed; nothing was sent, so it can be retried"
        attempt.next_retry_at = utcnow()
        record_event(attempt, "recovery", "marked_retryable", why)
    attempt.finished_at = attempt.finished_at or utcnow()


def recover_interrupted_runs(session: Session, *, stale_after_s: int) -> list[int]:
    """Mark runs whose worker stopped heartbeating as interrupted and settle their attempts."""
    cutoff = utcnow() - timedelta(seconds=stale_after_s)
    recovered: list[int] = []
    for run in session.scalars(
        select(AutoApplyRun).where(
            AutoApplyRun.status.in_((BatchStatus.RUNNING, BatchStatus.CANCELLING))
        )
    ).all():
        beat = run.heartbeat_at or run.started_at
        if beat is not None and beat > cutoff:
            continue
        for attempt in run.attempts:
            resolve_interrupted_attempt(attempt, "the worker running this application stopped")
        run.status = BatchStatus.CANCELLED if run.cancel_requested else BatchStatus.INTERRUPTED
        run.message = (run.message + " " if run.message else "") + (
            "Interrupted: the process running it stopped. Resume it to continue."
        )
        session.execute(delete(JobLock).where(JobLock.owner.like(f"run-{run.id}-%")))
        recovered.append(run.id)
    session.flush()
    if recovered:
        logger.warning("autoapply_runs_recovered", extra={"runs": recovered})
    return recovered


# --------------------------------------------------------------------------------------
# Evidence retention
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class CleanupReport:
    screenshots_deleted: int = 0
    staged_uploads_deleted: int = 0
    events_deleted: int = 0
    attempts_cleared: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "screenshots_deleted": self.screenshots_deleted,
            "staged_uploads_deleted": self.staged_uploads_deleted,
            "events_deleted": self.events_deleted,
            "attempts_cleared": self.attempts_cleared,
        }


def _delete_older_than(folder: Path, cutoff_epoch: float) -> int:
    if not folder.is_dir():
        return 0
    removed = 0
    for path in sorted(folder.rglob("*"), reverse=True):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff_epoch:
                path.unlink()
                removed += 1
            elif path.is_dir() and not any(path.iterdir()):
                path.rmdir()
        except OSError:  # pragma: no cover - a file vanishing mid-scan is fine
            continue
    return removed


def cleanup_evidence(
    session: Session, *, data_dir: Path, retention_days: int, now: datetime | None = None
) -> CleanupReport:
    """Delete evidence past its retention period. Attempt outcomes themselves are kept."""
    moment = now or utcnow()
    cutoff = moment - timedelta(days=retention_days)
    report = CleanupReport()
    report.screenshots_deleted = _delete_older_than(data_dir / "screenshots", cutoff.timestamp())
    # Staged resume copies exist only for the upload; a day is generous.
    report.staged_uploads_deleted = _delete_older_than(
        data_dir / "uploads", min(cutoff.timestamp(), time.time() - 86400)
    )
    result = session.execute(delete(SubmissionEvent).where(SubmissionEvent.created_at < cutoff))
    report.events_deleted = int(getattr(result, "rowcount", 0) or 0)
    for attempt in session.scalars(
        select(SubmissionAttempt).where(SubmissionAttempt.evidence_path != "")
    ).all():
        if not os.path.exists(attempt.evidence_path):
            attempt.evidence_path = ""
            report.attempts_cleared += 1
    session.flush()
    return report


def evidence_file(attempt: SubmissionAttempt, data_dir: Path) -> Path | None:
    """The attempt's screenshot, only if it really lives inside the private evidence folder."""
    if not attempt.evidence_path:
        return None
    root = (data_dir / "screenshots").resolve()
    path = Path(attempt.evidence_path).resolve()
    if root not in path.parents or not path.is_file():
        return None
    return path


__all__ = [
    "CIRCUIT_COOLDOWN",
    "BreakerState",
    "CleanupReport",
    "EmergencyStopActive",
    "acquire_job_lock",
    "all_breakers",
    "breaker_state",
    "cleanup_evidence",
    "clear_emergency_stop",
    "emergency_stop_state",
    "engage_emergency_stop",
    "evidence_file",
    "is_emergency_stopped",
    "lock_holder",
    "platform_slot",
    "record_breaker_outcome",
    "record_event",
    "recover_interrupted_runs",
    "release_job_lock",
    "reset_breaker",
    "resolve_interrupted_attempt",
]
