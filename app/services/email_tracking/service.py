"""Turning a job-related email into a reviewable suggestion.

One entry point, :meth:`EmailTrackingService.process_message`, serves both the Gmail sync
and a pasted ``.eml``, so the whole pipeline works (and is tested) without Google.

The rules this module exists to enforce:

* **Only job-related mail is kept**, and of that only the subject, addresses, received
  time, a redacted snippet of at most 500 characters and the extracted facts. The body is
  read in memory to classify and match, then dropped.
* **Nothing changes an application by itself.** A message produces at most one
  :class:`StatusSuggestion` in ``pending``; only :meth:`accept_suggestion`, called because
  the user pressed Accept, applies it — and it goes through
  :class:`~app.services.tracking.ApplicationTracker`, so the legal-transition table and the
  evidence requirement for ``CONFIRMED`` apply exactly as they do for a manual edit.
* **An illegal change is reported, not forced.** The suggestion stays pending and the
  caller gets the reason.
"""

from __future__ import annotations

import email
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from email.message import Message
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import (
    Application,
    ApplicationStatus,
    AutoApplyRun,
    CandidateProfile,
    EmailMessage,
    Outcome,
    StatusSuggestion,
    SubmissionAttempt,
    SubmissionEvent,
    SubmissionState,
    utcnow,
)
from app.db.repositories import AuditRepository, ProfileRepository
from app.logging_conf import get_logger
from app.services.email_tracking import classifier as categories
from app.services.email_tracking.classifier import Classification, classify, sender_domain
from app.services.email_tracking.extract import extract
from app.services.email_tracking.matching import (
    AUTO_LINKED,
    DISMISSED,
    NEEDS_REVIEW,
    USER_LINKED,
    EmailEvidence,
    match_email,
)
from app.services.redaction import redact
from app.services.text import collapse_whitespace
from app.services.tracking import ApplicationTracker, TransitionRequest
from app.sources.email_alerts import _decode, _message_date, _message_text

logger = get_logger(__name__)

SNIPPET_LIMIT = 500
MAX_RAW_BYTES = 5 * 1024 * 1024

PENDING = "pending"
ACCEPTED = "accepted"
SUGGESTION_DISMISSED = "dismissed"

S = ApplicationStatus

#: What each category suggests. Categories absent here (process updates, recruiter mail,
#: other) are kept for the user to read but never suggest a change.
SUGGESTION_FOR_CATEGORY: dict[str, tuple[str, str]] = {
    categories.REJECTION: ("outcome", Outcome.REJECTED.value),
    categories.INTERVIEW_INVITATION: ("outcome", Outcome.INTERVIEWING.value),
    categories.ASSESSMENT_INVITATION: ("outcome", Outcome.SCREENING.value),
    categories.OFFER: ("outcome", Outcome.OFFER.value),
    categories.APPLICATION_CONFIRMATION: ("status", ApplicationStatus.CONFIRMED.value),
}

_CATEGORY_LABEL = {
    categories.REJECTION: "Rejection",
    categories.INTERVIEW_INVITATION: "Interview invitation",
    categories.ASSESSMENT_INVITATION: "Assessment invitation",
    categories.OFFER: "Offer",
    categories.APPLICATION_CONFIRMATION: "Application confirmation",
}

#: How far along the employer's process each outcome is. Moving backwards (an offer back
#: to "screening") from an old email arriving late is refused rather than applied.
_OUTCOME_PROGRESS = {
    Outcome.PENDING: 0,
    Outcome.NO_RESPONSE: 0,
    Outcome.SCREENING: 1,
    Outcome.INTERVIEWING: 2,
    Outcome.OFFER: 3,
}


class EmailTrackingError(ValueError):
    """An expected, user-facing failure (unknown id, wrong state)."""


class SuggestionNotApplicable(EmailTrackingError):
    """The suggestion is legal to store but not to apply from the application's state."""


@dataclass(slots=True)
class ProcessResult:
    #: ``created``, ``duplicate`` or ``skipped_not_job_related``.
    outcome: str
    classification: Classification
    message: EmailMessage | None = None
    suggestion: StatusSuggestion | None = None


@dataclass(slots=True)
class AcceptResult:
    suggestion: StatusSuggestion
    message: str
    changes: list[str] = field(default_factory=list)


def short_hash(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def parse_raw_email(raw: bytes | str) -> Message:
    """Parse an RFC 822 payload. Size-capped because it is untrusted input."""
    data = raw.encode("utf-8", errors="replace") if isinstance(raw, str) else raw
    if len(data) > MAX_RAW_BYTES:
        raise EmailTrackingError(f"the email is larger than {MAX_RAW_BYTES // (1024 * 1024)} MB")
    if not data.strip():
        raise EmailTrackingError("the email is empty")
    return email.message_from_bytes(data)


class EmailTrackingService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._audit = AuditRepository(session)

    # ------------------------------------------------------------------ ingestion

    def _profile(self) -> CandidateProfile | None:
        return ProfileRepository(self._session).get_default()

    def find_existing(
        self, provider_message_id: str, account_id: int | None
    ) -> EmailMessage | None:
        statement = select(EmailMessage).where(
            EmailMessage.provider_message_id == provider_message_id
        )
        # NULL never equals NULL in a unique constraint, so manual ingests (no account)
        # are de-duplicated here rather than by the database.
        statement = statement.where(
            EmailMessage.account_id.is_(None)
            if account_id is None
            else EmailMessage.account_id == account_id
        )
        return self._session.scalars(statement.limit(1)).first()

    def ingest_message(
        self,
        message: Message,
        *,
        account_id: int | None = None,
        provider_message_id: str = "",
        thread_id: str = "",
        received_at: datetime | None = None,
    ) -> ProcessResult:
        """Process a parsed MIME message (from Gmail ``format=raw`` or a pasted .eml)."""
        message_id = provider_message_id or (_decode(message.get("Message-ID")) or "").strip()
        if not message_id:
            # Without a Message-ID the content itself is the identity, so pasting the
            # same file twice still de-duplicates.
            message_id = "sha256:" + short_hash(message.as_string(), 32)
        return self.process_message(
            provider_message_id=message_id[:200],
            subject=_decode(message.get("Subject")),
            body=_message_text(message),
            sender=_decode(message.get("From")),
            recipient=_decode(message.get("To")),
            received_at=received_at or _message_date(message),
            thread_id=thread_id,
            account_id=account_id,
        )

    def ingest_raw(self, raw: bytes | str, *, account_id: int | None = None) -> ProcessResult:
        return self.ingest_message(parse_raw_email(raw), account_id=account_id)

    def process_message(
        self,
        *,
        provider_message_id: str,
        subject: str,
        body: str,
        sender: str,
        recipient: str = "",
        received_at: datetime | None = None,
        thread_id: str = "",
        account_id: int | None = None,
    ) -> ProcessResult:
        """Classify, extract, match and store one message, and propose a change.

        ``body`` is used only inside this call. What is stored is listed in the module
        docstring; the body itself is not.
        """
        classification = classify(subject, body, sender)
        existing = self.find_existing(provider_message_id, account_id)
        if existing is not None:
            return ProcessResult("duplicate", classification, existing)
        if not classification.is_job_related:
            return ProcessResult("skipped_not_job_related", classification)

        profile = self._profile()
        facts = extract(subject, body, sender, received_at)
        domain = sender_domain(sender)
        evidence = EmailEvidence(
            facts=facts,
            subject=subject or "",
            body=body or "",
            sender_domain=domain,
            recipient=recipient or "",
            received_at=received_at,
            category=classification.category,
        )
        match = match_email(self._session, evidence, profile)

        extracted = facts.to_dict()
        extracted["reasons"] = classification.reasons[:12]
        row = EmailMessage(
            account_id=account_id,
            provider_message_id=provider_message_id,
            thread_id=thread_id[:200],
            received_at=received_at,
            sender=(facts.sender or "")[:320],
            sender_domain=domain[:200],
            recipient=collapse_whitespace(recipient or "")[:320],
            subject=redact(collapse_whitespace(subject or ""))[:400],
            snippet=make_snippet(body, profile),
            category=classification.category,
            confidence=classification.confidence,
            extracted=extracted,
            application_id=match.application_id,
            match_confidence=round(match.confidence, 3),
            match_state=match.state,
            match_candidates=match.candidate_dicts(),
        )
        self._session.add(row)
        self._session.flush()

        suggestion = None
        if match.state == AUTO_LINKED and match.application_id is not None:
            suggestion = self._suggest(row, match.application_id, match.confidence)
        self._audit.record(
            "email.processed",
            entity_type="email_message",
            entity_id=row.id,
            actor="system",
            detail={
                "category": row.category,
                "match_state": row.match_state,
                "sender_domain": row.sender_domain,
                "suggestion_id": suggestion.id if suggestion else None,
            },
        )
        return ProcessResult("created", classification, row, suggestion)

    # ------------------------------------------------------------------ suggestions

    def _evidence_text(self, message: EmailMessage) -> str:
        when = message.received_at.date().isoformat() if message.received_at else "unknown date"
        return redact(
            f"Email from {message.sender_domain or 'unknown sender'} received {when}: "
            f'"{message.subject}"'
        )

    def _latest_attempt(self, application_id: int) -> SubmissionAttempt | None:
        return self._session.scalars(
            select(SubmissionAttempt)
            .where(SubmissionAttempt.application_id == application_id)
            .order_by(SubmissionAttempt.id.desc())
            .limit(1)
        ).first()

    def _suggest(
        self, message: EmailMessage, application_id: int, match_confidence: float
    ) -> StatusSuggestion | None:
        mapping = SUGGESTION_FOR_CATEGORY.get(message.category)
        application = self._session.get(Application, application_id)
        if mapping is None or application is None:
            return None
        field_name, value = mapping
        if field_name == "outcome" and application.outcome.value == value:
            return None
        attempt = self._latest_attempt(application_id) if field_name == "status" else None
        attempt_unknown = attempt is not None and attempt.state is SubmissionState.OUTCOME_UNKNOWN
        if field_name == "status" and application.status.value == value and not attempt_unknown:
            return None
        duplicate = self._session.scalars(
            select(StatusSuggestion).where(
                StatusSuggestion.application_id == application_id,
                StatusSuggestion.field == field_name,
                StatusSuggestion.suggested_value == value,
                StatusSuggestion.state == PENDING,
            )
        ).first()
        if duplicate is not None:
            return duplicate

        reason = f"{_CATEGORY_LABEL[message.category]} — {self._evidence_text(message)}"
        if attempt_unknown and attempt is not None:
            reason += (
                f". Auto-apply attempt #{attempt.id} ended with an unknown outcome; accepting "
                "records it as confirmed by this email."
            )
        suggestion = StatusSuggestion(
            application_id=application_id,
            email_message_id=message.id,
            attempt_id=attempt.id if attempt_unknown and attempt is not None else None,
            field=field_name,
            suggested_value=value,
            reason=redact(reason)[:2000],
            confidence=round(message.confidence * max(match_confidence, 0.0), 3),
            state=PENDING,
        )
        self._session.add(suggestion)
        self._session.flush()
        return suggestion

    def _pending(self, suggestion_id: int) -> StatusSuggestion:
        suggestion = self._session.get(StatusSuggestion, suggestion_id)
        if suggestion is None:
            raise EmailTrackingError(f"suggestion {suggestion_id} was not found")
        if suggestion.state != PENDING:
            raise EmailTrackingError(f"suggestion {suggestion_id} is already {suggestion.state}")
        return suggestion

    def dismiss_suggestion(self, suggestion_id: int) -> StatusSuggestion:
        suggestion = self._pending(suggestion_id)
        suggestion.state = SUGGESTION_DISMISSED
        suggestion.resolved_at = utcnow()
        self._audit.record(
            "email.suggestion_dismissed",
            entity_type="status_suggestion",
            entity_id=suggestion.id,
        )
        self._session.flush()
        return suggestion

    def accept_suggestion(self, suggestion_id: int) -> AcceptResult:
        """Apply a suggestion the user accepted, through the legal transitions only.

        Raises :class:`SuggestionNotApplicable` with the reason when the application's
        current state does not allow the change; the suggestion then stays pending.
        """
        suggestion = self._pending(suggestion_id)
        application = self._session.get(Application, suggestion.application_id)
        if application is None:
            raise EmailTrackingError("the application this suggestion refers to no longer exists")
        message = (
            self._session.get(EmailMessage, suggestion.email_message_id)
            if suggestion.email_message_id
            else None
        )
        evidence = self._evidence_text(message) if message else redact(suggestion.reason)

        if suggestion.field == "outcome":
            changes = self._apply_outcome(
                application, Outcome(suggestion.suggested_value), evidence
            )
        elif suggestion.field == "status":
            changes = self._apply_confirmation(application, suggestion, message, evidence)
        else:  # pragma: no cover - the model only ever holds the two values above
            raise EmailTrackingError(f"unknown suggestion field {suggestion.field!r}")

        suggestion.state = ACCEPTED
        suggestion.resolved_at = utcnow()
        self._audit.record(
            "email.suggestion_accepted",
            entity_type="status_suggestion",
            entity_id=suggestion.id,
            detail={"application_id": application.id, "changes": changes},
        )
        self._session.flush()
        summary = "; ".join(changes) if changes else "already recorded, nothing changed"
        return AcceptResult(suggestion, summary, changes)

    def _apply_outcome(self, application: Application, target: Outcome, evidence: str) -> list[str]:
        current = application.outcome
        if current is target:
            return []
        if current in (Outcome.ACCEPTED, Outcome.WITHDRAWN):
            raise SuggestionNotApplicable(
                f"you recorded this application as {current.value}; an email cannot change "
                "that. Edit the application yourself if it is wrong."
            )
        if current is Outcome.REJECTED:
            raise SuggestionNotApplicable(
                f"this application is recorded as rejected. If the employer has re-engaged, "
                f"set the outcome to {target.value} on the application yourself."
            )
        if target is not Outcome.REJECTED and _OUTCOME_PROGRESS.get(
            target, 0
        ) < _OUTCOME_PROGRESS.get(current, 0):
            raise SuggestionNotApplicable(
                f"the application is already at {current.value}, further along than "
                f"{target.value}; this email is probably older than the last update."
            )
        application.outcome = target
        note = f"Outcome set to {target.value} from email evidence. {evidence}"
        application.notes = (f"{application.notes}\n{note}" if application.notes else note)[:20000]
        self._audit.record(
            "application.outcome_changed",
            entity_type="application",
            entity_id=application.id,
            actor="user",
            detail={"from": current.value, "to": target.value, "evidence": evidence[:300]},
        )
        changes = [f"outcome {current.value} -> {target.value}"]
        if application.status in (
            S.DISCOVERED,
            S.SCORED,
            S.SHORTLISTED,
            S.READY_FOR_REVIEW,
            S.APPROVED,
        ):
            changes.append(
                f"status left at {application.status.value}: record the submission on the "
                "application if you applied outside JobOrbit"
            )
        return changes

    def _status_path(self, application: Application) -> list[ApplicationStatus]:
        current = application.status
        if current is S.CONFIRMED:
            return []
        if current in (S.SUBMITTED, S.SUBMISSION_UNKNOWN):
            return [S.CONFIRMED]
        if current is S.APPROVED:
            # A confirmation from the employer is evidence the application was sent, so
            # the submission is recorded first and then confirmed: two legal steps.
            return [S.SUBMITTED, S.CONFIRMED]
        raise SuggestionNotApplicable(
            f"the application is {current.value}. CONFIRMED can only follow a recorded "
            "submission (SUBMITTED, SUBMISSION_UNKNOWN or APPROVED). Review and approve it, "
            "or record the submission yourself, then accept this suggestion."
        )

    def _apply_confirmation(
        self,
        application: Application,
        suggestion: StatusSuggestion,
        message: EmailMessage | None,
        evidence: str,
    ) -> list[str]:
        path = self._status_path(application)  # validated before anything is mutated
        changes: list[str] = []

        attempt = (
            self._session.get(SubmissionAttempt, suggestion.attempt_id)
            if suggestion.attempt_id
            else self._latest_attempt(application.id)
        )
        reconciled = False
        if attempt is not None and attempt.state is SubmissionState.OUTCOME_UNKNOWN:
            identity = message.provider_message_id if message else f"suggestion-{suggestion.id}"
            attempt.state = SubmissionState.SUBMITTED_CONFIRMED
            attempt.confirmation_id = f"email-{short_hash(identity)}"
            attempt.confirmation_evidence = evidence
            attempt.detail = redact(
                f"{attempt.detail} (confirmed by an email the user accepted)".strip()
            )[:4000]
            attempt.events.append(
                SubmissionEvent(kind="evidence", name="email_confirmation", detail=evidence)
            )
            run = self._session.get(AutoApplyRun, attempt.autoapply_run_id)
            if run is not None:
                run.unknown_count = max(0, run.unknown_count - 1)
                run.confirmed_count += 1
            reconciled = True
            changes.append(f"attempt #{attempt.id} outcome_unknown -> submitted_confirmed")

        tracker = ApplicationTracker(self._session)
        submitter = (
            f"joborbit-autoapply/{attempt.target_key}"
            if reconciled and attempt is not None and attempt.target_key
            else "user"
        )
        for target in path:
            before = application.status
            tracker.transition(
                application,
                TransitionRequest(
                    target=target,
                    actor="user",
                    detail=f"accepted email suggestion #{suggestion.id}: {evidence}"[:1000],
                    submitted_by=submitter,
                    confirmation_evidence=evidence,
                ),
            )
            changes.append(f"status {before.value} -> {target.value}")
        return changes

    # ------------------------------------------------------------------ review inbox

    def _message(self, message_id: int) -> EmailMessage:
        message = self._session.get(EmailMessage, message_id)
        if message is None:
            raise EmailTrackingError(f"email {message_id} was not found")
        return message

    def link_message(
        self, message_id: int, application_id: int
    ) -> tuple[EmailMessage, StatusSuggestion | None]:
        """Link a message to the application the user picked, and propose its change."""
        message = self._message(message_id)
        if self._session.get(Application, application_id) is None:
            raise EmailTrackingError(f"application {application_id} was not found")
        for stale in self._session.scalars(
            select(StatusSuggestion).where(
                StatusSuggestion.email_message_id == message.id,
                StatusSuggestion.state == PENDING,
                StatusSuggestion.application_id != application_id,
            )
        ):
            stale.state = SUGGESTION_DISMISSED
            stale.resolved_at = utcnow()
        message.application_id = application_id
        message.match_state = USER_LINKED
        message.match_confidence = 1.0
        self._session.flush()
        suggestion = self._suggest(message, application_id, 1.0)
        self._audit.record(
            "email.linked",
            entity_type="email_message",
            entity_id=message.id,
            detail={"application_id": application_id},
        )
        return message, suggestion

    def dismiss_message(self, message_id: int) -> EmailMessage:
        message = self._message(message_id)
        message.match_state = DISMISSED
        for pending in self._session.scalars(
            select(StatusSuggestion).where(
                StatusSuggestion.email_message_id == message.id, StatusSuggestion.state == PENDING
            )
        ):
            pending.state = SUGGESTION_DISMISSED
            pending.resolved_at = utcnow()
        self._session.flush()
        return message

    # ------------------------------------------------------------------ queries

    def list_messages(
        self,
        *,
        match_state: str | None = None,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[EmailMessage], int]:
        from sqlalchemy import func

        statement = select(EmailMessage)
        if match_state:
            statement = statement.where(EmailMessage.match_state == match_state)
        if category:
            statement = statement.where(EmailMessage.category == category)
        total = self._session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        rows = self._session.scalars(
            statement.order_by(EmailMessage.received_at.desc(), EmailMessage.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return list(rows), int(total)

    def list_suggestions(
        self, *, state: str | None = PENDING, limit: int = 100
    ) -> list[StatusSuggestion]:
        statement = select(StatusSuggestion).where(StatusSuggestion.email_message_id.is_not(None))
        if state:
            statement = statement.where(StatusSuggestion.state == state)
        return list(
            self._session.scalars(statement.order_by(StatusSuggestion.id.desc()).limit(limit))
        )

    def review_count(self) -> int:
        from sqlalchemy import func

        return int(
            self._session.scalar(
                select(func.count()).where(EmailMessage.match_state == NEEDS_REVIEW)
            )
            or 0
        )

    # ------------------------------------------------------------------ deletion

    def delete_data(
        self, account_id: int | None = None, *, everything: bool = False
    ) -> dict[str, int]:
        """Delete stored email messages and the suggestions made from them.

        ``everything`` removes all of it (every account and every pasted email); otherwise
        only the given account's messages, or the pasted ones when ``account_id`` is None.
        Changes the user already accepted stay on the application: they are the user's
        decision, not email data.
        """
        message_filter: Any
        if everything:
            message_filter = EmailMessage.id.is_not(None)
        elif account_id is None:
            message_filter = EmailMessage.account_id.is_(None)
        else:
            message_filter = EmailMessage.account_id == account_id
        message_ids = list(self._session.scalars(select(EmailMessage.id).where(message_filter)))
        suggestions = 0
        if message_ids:
            suggestions = self._session.execute(
                delete(StatusSuggestion).where(StatusSuggestion.email_message_id.in_(message_ids))
            ).rowcount
            self._session.execute(delete(EmailMessage).where(EmailMessage.id.in_(message_ids)))
        self._audit.record(
            "email.data_deleted",
            entity_type="email_account",
            entity_id=account_id,
            detail={"messages": len(message_ids), "suggestions": suggestions},
        )
        self._session.flush()
        self._session.expire_all()
        return {"messages": len(message_ids), "suggestions": int(suggestions or 0)}


def make_snippet(body: str, profile: CandidateProfile | None) -> str:
    """A redacted, whitespace-collapsed excerpt of at most 500 characters."""
    extra = [profile.full_name, profile.phone, profile.email] if profile is not None else []
    text = redact(collapse_whitespace(body or ""), extra=[value for value in extra if value])
    if len(text) <= SNIPPET_LIMIT:
        return text
    return text[: SNIPPET_LIMIT - 1].rstrip() + "…"


__all__ = [
    "AcceptResult",
    "EmailTrackingError",
    "EmailTrackingService",
    "ProcessResult",
    "SUGGESTION_FOR_CATEGORY",
    "SuggestionNotApplicable",
    "make_snippet",
    "parse_raw_email",
    "short_hash",
]
