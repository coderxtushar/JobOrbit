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
    """Raised when an automated actor tries to record a submission it cannot evidence.

    The auto-apply orchestrator is the only non-human caller, and it gets past this guard
    only for a provider whose own adapter reports candidate submission as authorized,
    carrying a confirmation identifier that provider returned. No real job platform
    qualifies, so this remains the mechanism that stops a LinkedIn, Indeed, Naukri or
    Wellfound application being claimed as sent.
    """


@dataclass(frozen=True, slots=True)
class TransitionRequest:
    target: ApplicationStatus
    actor: str = "user"
    detail: str = ""
    submitted_by: str = ""
    confirmation_evidence: str = ""
    at: datetime | None = None
    #: Submission provider key, when the application was dispatched programmatically.
    #: Checked against that provider's own capability report, so naming a target here
    #: cannot authorise anything the adapter does not already permit.
    submission_target: str = ""
    #: Identifier the provider returned on verification. Required alongside
    #: ``submission_target`` before an automated actor may record a submission at all.
    confirmation_id: str = ""


_NON_HUMAN_ACTORS = frozenset({"scheduler", "system", "bot", "agent", "automation", "cron"})


def _automated_submission_permitted(request: TransitionRequest) -> bool:
    """Whether an automated actor may record this particular submission.

    False for every real job platform, because none of their adapters reports submission
    as supported — so this cannot become a route to claiming a LinkedIn or Indeed
    application was sent. It returns True only for a provider that authorises candidate
    submission *and* has returned a verified confirmation identifier.

    The capability is read from the adapter rather than taken from the caller, which is
    what stops a future caller unlocking the guard by passing a chosen string.
    """
    if not request.submission_target or not request.confirmation_id.strip():
        return False

    from app.db.models import Job
    from app.submission.registry import get_submission_adapter

    adapter = get_submission_adapter(request.submission_target)
    return adapter.check_capability(Job(title="", company="", url="")).supported


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


#: Recorded when the user opens the employer's own application page. It is an event and
#: never a status, because opening a page is not submitting a form - inferring a submission
#: from a click is the exact mistake this project refuses to make.
OPENED_EVENT_DETAIL = "user opened the employer's application page"


def was_opened(application: Application) -> bool:
    return any(event.detail == OPENED_EVENT_DETAIL for event in application.events)


def next_action(application: Application) -> str:
    """The one thing the user should do next, in their words.

    Derived from the status, the blocking questions and whether the employer's page has
    been opened, so the screen never shows a bare state name and leave the user to
    work out what it implies.
    """
    status = application.status
    if status in (S.DISCOVERED, S.SCORED, S.SHORTLISTED):
        return "Prepare this application to generate its letter and answers."
    if status is S.READY_FOR_REVIEW:
        pending = blocking_questions(application)
        if pending:
            return (
                f"Answer {len(pending)} outstanding question(s). Sensitive and legal "
                "questions are never drafted for you."
            )
        if not application.user_approved:
            return "Review the letter and answers, then mark this approved."
        return "Mark this approved to move it on."
    if status is S.APPROVED:
        if not was_opened(application):
            return "Open the employer's own page, paste your answers and submit it yourself."
        return "You opened the employer's page. Record whether you submitted it."
    if status is S.SUBMITTED:
        return (
            "Add the confirmation evidence when it arrives, or record the outcome as "
            "unknown. A click is not a confirmation."
        )
    if status is S.SUBMISSION_UNKNOWN:
        return "The outcome is unrecorded. Add evidence if a confirmation arrives."
    if status is S.CONFIRMED:
        return "Confirmed. Record the outcome and any interview stage as it happens."
    if status is S.SKIPPED:
        return "Skipped. Shortlist the job again if you change your mind."
    return "This application failed. Shortlist the job again to retry."


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
            if (
                submitter.lower() in _NON_HUMAN_ACTORS or request.actor.lower() in _NON_HUMAN_ACTORS
            ) and not _automated_submission_permitted(request):
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
