"""Application lifecycle.

The allowed-transition table below is the single place application state can change, and
every change appends an :class:`ApplicationEvent`. Three rules are enforced structurally:

* ``APPROVED`` requires the user to have approved and every blocking question answered.
* ``SUBMITTED`` requires a named human submitter. Nothing in this codebase can supply one
  automatically, because no code path submits an application.
* ``CONFIRMED`` requires confirmation evidence. A click is not a confirmation, so an
  application whose outcome is unclear goes to ``SUBMISSION_UNKNOWN`` instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import (
    AnswerProvenance,
    Application,
    ApplicationEvent,
    ApplicationStatus,
    utcnow,
)
from app.db.repositories import ApplicationRepository, AuditRepository

S = ApplicationStatus

ALLOWED_TRANSITIONS: dict[ApplicationStatus, frozenset[ApplicationStatus]] = {
    S.DISCOVERED: frozenset({S.SCORED, S.SHORTLISTED, S.SKIPPED}),
    S.SCORED: frozenset({S.SHORTLISTED, S.SKIPPED}),
    S.SHORTLISTED: frozenset({S.READY_FOR_REVIEW, S.SKIPPED, S.FAILED}),
    S.READY_FOR_REVIEW: frozenset({S.APPROVED, S.SHORTLISTED, S.SKIPPED, S.FAILED}),
    S.APPROVED: frozenset(
        {S.SUBMITTED, S.SUBMISSION_UNKNOWN, S.READY_FOR_REVIEW, S.SKIPPED, S.FAILED}
    ),
    S.SUBMITTED: frozenset({S.CONFIRMED, S.SUBMISSION_UNKNOWN, S.FAILED}),
    S.SUBMISSION_UNKNOWN: frozenset({S.CONFIRMED, S.SUBMITTED, S.FAILED, S.SKIPPED}),
    S.CONFIRMED: frozenset(),
    S.SKIPPED: frozenset({S.SHORTLISTED}),
    S.FAILED: frozenset({S.SHORTLISTED, S.READY_FOR_REVIEW, S.SKIPPED}),
}

TERMINAL_STATUSES = frozenset({S.CONFIRMED})


class InvalidTransition(ValueError):
    def __init__(
        self, current: ApplicationStatus, target: ApplicationStatus, reason: str = ""
    ) -> None:
        allowed = sorted(status.value for status in ALLOWED_TRANSITIONS.get(current, frozenset()))
        detail = reason or (
            f"cannot move from {current.value} to {target.value}; "
            f"allowed next states are {allowed or ['none, this state is final']}"
        )
        super().__init__(detail)
        self.current = current
        self.target = target


class AutomatedSubmissionBlocked(PermissionError):
    """Raised if a non-human actor ever tries to record a submission.

    This is a defence-in-depth assertion: no caller in this codebase passes a non-human
    actor, and the guard exists so that a future one cannot.
    """


@dataclass(frozen=True, slots=True)
class TransitionRequest:
    target: ApplicationStatus
    actor: str = "user"
    detail: str = ""
    submitted_by: str = ""
    confirmation_evidence: str = ""
    at: datetime | None = None


_NON_HUMAN_ACTORS = frozenset({"scheduler", "system", "bot", "agent", "automation", "cron"})


def blocking_questions(application: Application) -> list[str]:
    """Questions that must be answered by the user before approval."""
    blocking: list[str] = []
    for answer in application.answers:
        unanswered = not (answer.answer or "").strip()
        if (
            answer.requires_user_input
            and unanswered
            or answer.is_sensitive
            and (unanswered or answer.provenance is AnswerProvenance.AI_DRAFT)
        ):
            blocking.append(answer.question)
    return blocking


def can_transition(current: ApplicationStatus, target: ApplicationStatus) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


class ApplicationTracker:
    """Applies validated status transitions and records the audit trail."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._applications = ApplicationRepository(session)
        self._audit = AuditRepository(session)

    def transition(self, application: Application, request: TransitionRequest) -> Application:
        current = application.status
        target = request.target
        moment = request.at or utcnow()

        if current is target:
            return application
        if not can_transition(current, target):
            raise InvalidTransition(current, target)

        if target is S.APPROVED:
            if not application.user_approved:
                raise InvalidTransition(
                    current, target, "approval requires an explicit user approval first"
                )
            pending = blocking_questions(application)
            if pending:
                raise InvalidTransition(
                    current,
                    target,
                    f"{len(pending)} question(s) still need your input: " + "; ".join(pending[:3]),
                )

        if target is S.SUBMITTED:
            submitter = (request.submitted_by or "").strip()
            if not submitter:
                raise InvalidTransition(
                    current, target, "recording a submission requires the name of who submitted it"
                )
            if submitter.lower() in _NON_HUMAN_ACTORS or request.actor.lower() in _NON_HUMAN_ACTORS:
                raise AutomatedSubmissionBlocked(
                    "applications must be submitted by you on the employer's own site; "
                    "this application never submits one"
                )
            application.submitted_by = submitter
            application.submitted_at = moment

        if target is S.CONFIRMED:
            evidence = (
                request.confirmation_evidence or application.confirmation_evidence or ""
            ).strip()
            if not evidence:
                raise InvalidTransition(
                    current,
                    target,
                    "confirmation requires evidence such as a confirmation email or a "
                    "reference number; use SUBMISSION_UNKNOWN if you do not have one",
                )
            application.confirmation_evidence = evidence
            application.confirmed_at = moment

        if target is S.READY_FOR_REVIEW:
            application.prepared_at = application.prepared_at or moment
        if target in (S.APPROVED, S.READY_FOR_REVIEW):
            application.reviewed_at = moment
        if target is S.APPROVED:
            application.approved_at = moment

        application.status = target
        # Appended through the relationship, not inserted by foreign key: the collection
        # is eagerly loaded, so a bare INSERT would leave the caller's in-memory
        # application with an empty event history until it was refreshed.
        application.events.append(
            ApplicationEvent(
                from_status=current,
                to_status=target,
                actor=request.actor,
                detail=request.detail,
                created_at=moment,
            )
        )
        self._audit.record(
            "application.status_changed",
            entity_type="application",
            entity_id=application.id,
            actor=request.actor,
            detail={"from": current.value, "to": target.value, "note": request.detail[:200]},
        )
        self._session.flush()
        return application
