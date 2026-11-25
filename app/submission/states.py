"""State sets and predicates for submission attempts.

:class:`~app.db.models.SubmissionState` itself lives with the other enums in the models
module, because it is persisted on ``submission_attempt``. What lives here is the policy
built on top of it: which states the orchestrator treats as finished, which it may retry,
and which single state may be reported to the user as an application actually sent.
"""

from __future__ import annotations

from app.db.models import SubmissionState

#: Attempts in these states are finished. The orchestrator will not pick them up again,
#: which is what makes an interrupted run resumable without re-sending anything.
TERMINAL_STATES: frozenset[SubmissionState] = frozenset(
    {
        SubmissionState.SUBMITTED_CONFIRMED,
        SubmissionState.UNSUPPORTED_PLATFORM,
        SubmissionState.OUTCOME_UNKNOWN,
    }
)

#: Attempts that may be retried within the run's retry budget. ``OUTCOME_UNKNOWN`` is
#: pointedly absent: it is the one failure mode where retrying risks a duplicate
#: application, so it stays terminal and is surfaced for the user to check by hand.
RETRYABLE_STATES: frozenset[SubmissionState] = frozenset({SubmissionState.FAILED})

#: Attempts waiting on the user. Not failures, and not retried until the user acts.
NEEDS_USER_STATES: frozenset[SubmissionState] = frozenset(
    {
        SubmissionState.BLOCKED_MISSING_INFO,
        SubmissionState.REQUIRES_USER_ACTION,
    }
)


#: Milestones of one attempt, in order. ``SubmissionAttempt.checkpoint`` holds the furthest
#: one reached and is committed *before* the step it names is risky — in particular
#: ``submit_requested`` is durable before Submit is pressed, so a worker that dies at that
#: moment leaves a record that says "this may have been sent".
CHECKPOINTS: tuple[str, ...] = (
    "queued",
    "capability_checked",
    "prepared",
    "form_inspected",
    "form_filled",
    "submit_requested",
    "submit_clicked",
    "outcome_read",
)

#: Checkpoints after which the employer may have received the application. An attempt
#: interrupted at or beyond one of these becomes ``OUTCOME_UNKNOWN``, never a retry.
SUBMIT_REACHED: frozenset[str] = frozenset({"submit_requested", "submit_clicked", "outcome_read"})


def checkpoint_index(name: str) -> int:
    """Position of a checkpoint in :data:`CHECKPOINTS`; -1 for none or an unknown name."""
    return CHECKPOINTS.index(name) if name in CHECKPOINTS else -1


def submit_may_have_happened(checkpoint: str) -> bool:
    return checkpoint in SUBMIT_REACHED


#: Why an attempt did not end confirmed. The category, not the message, drives the retry
#: policy, so a new message cannot accidentally make a failure retryable.
class FailureCategory:
    TRANSIENT = "transient"
    BROWSER_CRASH = "browser_crash"
    TIMEOUT = "timeout"
    UPLOAD_FAILED = "upload_failed"
    FORM_CHANGED = "form_changed"
    WRONG_PAGE = "wrong_page"
    POSTING_CLOSED = "posting_closed"
    VALIDATION_REJECTED = "validation_rejected"
    CAPTCHA = "captcha"
    MFA = "mfa"
    SIGN_IN_REQUIRED = "sign_in_required"
    MISSING_ANSWERS = "missing_answers"
    DUPLICATE_PREVENTED = "duplicate_prevented"
    LOCKED_ELSEWHERE = "locked_elsewhere"
    CIRCUIT_OPEN = "circuit_open"
    EMERGENCY_STOP = "emergency_stop"
    USER_VERIFIED_NOT_SENT = "user_verified_not_sent"
    UNKNOWN_OUTCOME = "unknown_outcome"
    #: The user's saved answer is not one of the choices the form offers. A data problem
    #: for the user to fix, not a sign the platform is failing, so it never trips a breaker.
    ANSWER_NOT_OFFERED = "answer_not_offered"


_ANSWER_NOT_OFFERED_MARKERS = (
    "no choice matching",
    "none of the suggestions matches",
    "is not one of the options",
)


def category_for_fill_error(message: str) -> str:
    """Classify a fill failure: the user's answer not offered, or the form itself changed."""
    lowered = message.casefold()
    if any(marker in lowered for marker in _ANSWER_NOT_OFFERED_MARKERS):
        return FailureCategory.ANSWER_NOT_OFFERED
    return FailureCategory.FORM_CHANGED


#: Failures worth retrying inside the same run, with backoff, because nothing about the
#: application itself was wrong. Everything else either needs the user or will fail the
#: same way again.
TRANSIENT_FAILURES: frozenset[str] = frozenset(
    {
        FailureCategory.TRANSIENT,
        FailureCategory.BROWSER_CRASH,
        FailureCategory.TIMEOUT,
        FailureCategory.UPLOAD_FAILED,
    }
)

#: Failures that need a person: the provider wants proof that one is present.
USER_ACTION_FAILURES: frozenset[str] = frozenset(
    {FailureCategory.CAPTCHA, FailureCategory.MFA, FailureCategory.SIGN_IN_REQUIRED}
)


def is_terminal(state: SubmissionState) -> bool:
    return state in TERMINAL_STATES


def counts_as_sent(state: SubmissionState) -> bool:
    """Whether this attempt may be reported to the user as a submitted application.

    Exactly one state qualifies. Every "submitted" statistic the dashboard shows routes
    through this function, so no screen can quietly widen the definition.
    """
    return state is SubmissionState.SUBMITTED_CONFIRMED


__all__ = [
    "CHECKPOINTS",
    "SUBMIT_REACHED",
    "TRANSIENT_FAILURES",
    "USER_ACTION_FAILURES",
    "FailureCategory",
    "category_for_fill_error",
    "checkpoint_index",
    "submit_may_have_happened",
    "NEEDS_USER_STATES",
    "RETRYABLE_STATES",
    "TERMINAL_STATES",
    "SubmissionState",
    "counts_as_sent",
    "is_terminal",
]
