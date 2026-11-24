"""Settling an attempt whose outcome JobOrbit could not read.

``OUTCOME_UNKNOWN`` is never retried automatically: pressing Submit a second time is how
one application becomes two. Instead the outcome is settled from evidence, in one of
three ways:

* :func:`recheck` looks again at the tab left open after the attempt. A confirmation
  that appeared since is the same evidence ``verify_submission`` accepts, so it confirms
  the attempt. It also reports any confirmation email already linked to the application.
* The user checks themselves and calls :func:`resolve` with ``submitted`` — which needs
  their evidence in words — or ``not_submitted``, which makes the job eligible for a later
  run because a person has established that nothing arrived.
* An email accepted from the review inbox (see the email tracking service).

Nothing here presses Submit.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Application,
    ApplicationStatus,
    Job,
    SubmissionAttempt,
    SubmissionState,
    utcnow,
)
from app.services.autoapply_control import record_event
from app.services.redaction import redact
from app.services.tracking import ApplicationTracker, InvalidTransition, TransitionRequest
from app.submission.states import FailureCategory

_UNCLEAR = (SubmissionState.OUTCOME_UNKNOWN, SubmissionState.REQUIRES_USER_ACTION)


class ResolutionError(ValueError):
    """The attempt cannot be settled that way from its current state."""


def _confirm(
    session: Session, attempt: SubmissionAttempt, evidence: str, *, source: str, actor: str
) -> None:
    digest = hashlib.sha256(f"{attempt.id}|{source}|{evidence}".encode()).hexdigest()[:16]
    attempt.state = SubmissionState.SUBMITTED_CONFIRMED
    attempt.confirmation_id = f"{source}-{digest}"
    attempt.confirmation_evidence = redact(evidence)[:2000]
    attempt.failure_category = ""
    attempt.checkpoint = "outcome_read"
    attempt.finished_at = utcnow()
    record_event(
        attempt,
        "user_action" if actor == "user" else "recovery",
        f"confirmed_by_{source}",
        evidence,
    )
    application = (
        session.get(Application, attempt.application_id) if attempt.application_id else None
    )
    if application is None:
        return
    tracker = ApplicationTracker(session)
    application.user_approved = True
    path = {
        ApplicationStatus.SUBMISSION_UNKNOWN: [ApplicationStatus.CONFIRMED],
        ApplicationStatus.SUBMITTED: [ApplicationStatus.CONFIRMED],
        ApplicationStatus.APPROVED: [ApplicationStatus.SUBMITTED, ApplicationStatus.CONFIRMED],
    }.get(
        application.status,
        [ApplicationStatus.APPROVED, ApplicationStatus.SUBMITTED, ApplicationStatus.CONFIRMED],
    )
    for target in path:
        try:
            tracker.transition(
                application,
                TransitionRequest(
                    target,
                    actor=actor,
                    # Recorded as the user's submission: they either pressed Submit after
                    # a CAPTCHA, or confirmed that JobOrbit's press went through.
                    submitted_by="you" if target is ApplicationStatus.SUBMITTED else "",
                    detail=f"settled from {source}",
                    confirmation_evidence=attempt.confirmation_evidence,
                ),
            )
        except InvalidTransition as error:
            record_event(attempt, "error", "tracker_transition_refused", str(error))
            return


def recheck(session: Session, attempt: SubmissionAttempt) -> str:
    """Look for confirmation of an unclear attempt. Returns what was found, or ``""``."""
    if attempt.state not in _UNCLEAR:
        return ""
    job = session.get(Job, attempt.job_id)
    found = ""
    if job is not None:
        from app.submission.registry import get_submission_adapter

        adapter = get_submission_adapter(attempt.target_key)
        recheck_page = getattr(adapter, "recheck", None)
        if callable(recheck_page):
            before = str((attempt.response_metadata or {}).get("before_url") or "")
            found = str(recheck_page(job, before) or "")
    if found:
        _confirm(
            session, attempt, f"rechecked the open tab: {found}", source="recheck", actor="agent"
        )
        return found

    if attempt.application_id is not None:
        from app.db.models import EmailMessage

        email = session.scalars(
            select(EmailMessage)
            .where(
                EmailMessage.application_id == attempt.application_id,
                EmailMessage.category == "application_confirmation",
            )
            .order_by(EmailMessage.received_at.desc())
            .limit(1)
        ).first()
        if email is not None and (
            attempt.started_at is None
            or email.received_at is None
            or email.received_at >= attempt.started_at
        ):
            note = (
                f"a confirmation email from {email.sender_domain or 'the employer'} "
                f"({email.subject[:120]}) is linked to this application; accept its "
                "suggestion in the Email page, or resolve this attempt as submitted"
            )
            record_event(attempt, "recovery", "confirmation_email_found", note)
            return note
    record_event(
        attempt,
        "recovery",
        "recheck_found_nothing",
        "no confirmation on the page or in linked email",
    )
    return ""


def resolve(session: Session, attempt: SubmissionAttempt, *, outcome: str, evidence: str) -> None:
    """Record the user's own finding about an unclear attempt."""
    if attempt.state not in _UNCLEAR:
        raise ResolutionError(
            f"attempt {attempt.id} is {attempt.state.value}; only an unknown outcome or one "
            "waiting for you can be resolved"
        )
    if outcome == "submitted":
        text = (evidence or "").strip()
        if len(text) < 4:
            raise ResolutionError(
                "say what showed it was submitted (a confirmation email, a reference number, "
                "the confirmation page)"
            )
        _confirm(session, attempt, f"confirmed by you: {text}", source="user", actor="user")
        return
    if outcome != "not_submitted":
        raise ResolutionError("outcome must be 'submitted' or 'not_submitted'")
    attempt.state = SubmissionState.FAILED
    attempt.failure_category = FailureCategory.USER_VERIFIED_NOT_SENT
    attempt.detail = "you checked and the application did not go through; a later run may retry it"
    attempt.finished_at = utcnow()
    record_event(attempt, "user_action", "verified_not_submitted", evidence)
    application = (
        session.get(Application, attempt.application_id) if attempt.application_id else None
    )
    if application is not None and application.status is ApplicationStatus.SUBMISSION_UNKNOWN:
        try:
            ApplicationTracker(session).transition(
                application,
                TransitionRequest(
                    ApplicationStatus.FAILED,
                    actor="user",
                    detail="you checked: the submission did not arrive",
                ),
            )
        except InvalidTransition as error:
            record_event(attempt, "error", "tracker_transition_refused", str(error))


__all__ = ["ResolutionError", "recheck", "resolve"]
