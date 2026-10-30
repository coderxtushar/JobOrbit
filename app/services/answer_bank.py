"""Answer bank and action inbox.

Answering a screening question once and reusing it is the single biggest time saving in a
bulk run, and it is also the easiest place to introduce a lie. Two rules keep it honest:

* Only an answer you typed, or one read from a verified profile field, may enter the bank.
  An ``ai_draft`` is rejected outright, because reuse would repeat one unreviewed sentence
  to a hundred employers.
* A reused answer keeps its original provenance. It is recorded as ``user_entered``
  because that is what it is — your words, applied again — never promoted to
  ``profile_verified``.

Backfill only touches applications that are still open. An application already submitted
or confirmed is a record of what an employer actually received and is never rewritten.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import (
    AnswerProvenance,
    ApplicationAnswer,
    CandidateProfile,
    SavedAnswer,
)
from app.db.repositories import (
    AuditRepository,
    SavedAnswerRepository,
)
from app.db.repositories.answers import InboxList, SavedAnswerList
from app.logging_conf import get_logger
from app.services.questions import SENSITIVE_KEYS

logger = get_logger(__name__)


@dataclass(slots=True)
class ResolveResult:
    question_key: str
    saved: SavedAnswer
    applications_updated: int
    skipped_closed: int


class AnswerBankService:
    """Reads and writes reusable screening answers."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._answers = SavedAnswerRepository(session)
        self._audit = AuditRepository(session)

    def list(self, profile: CandidateProfile) -> SavedAnswerList:
        return self._answers.list(profile.id)

    def inbox(self, profile: CandidateProfile, *, limit: int = 100) -> InboxList:
        return self._answers.inbox(profile.id, limit=limit)

    def bank_map(self, profile_id: int) -> dict[str, SavedAnswer]:
        return self._answers.as_map(profile_id)

    def save(
        self,
        profile: CandidateProfile,
        *,
        question_key: str,
        answer: str,
        question: str = "",
        provenance: AnswerProvenance = AnswerProvenance.USER_ENTERED,
    ) -> SavedAnswer:
        entry = self._answers.upsert(
            profile_id=profile.id,
            question_key=question_key,
            question=question,
            answer=answer,
            provenance=provenance,
            is_sensitive=question_key in SENSITIVE_KEYS,
        )
        self._audit.record(
            "answer_bank.saved",
            entity_type="saved_answer",
            entity_id=entry.id,
            detail={"question_key": question_key, "provenance": provenance.value},
        )
        return entry

    def delete(self, profile: CandidateProfile, question_key: str) -> bool:
        removed = self._answers.delete(profile.id, question_key)
        if removed:
            self._audit.record(
                "answer_bank.deleted",
                entity_type="saved_answer",
                detail={"question_key": question_key},
            )
        return removed

    def resolve_from_inbox(
        self,
        profile: CandidateProfile,
        *,
        question_key: str,
        answer: str,
        question: str = "",
        apply_to_open_applications: bool = True,
    ) -> ResolveResult:
        """Save one answer and push it onto every open application that still needs it."""
        text = answer.strip()
        if not text:
            raise ValueError("an answer cannot be blank; delete the entry instead")

        saved = self.save(
            profile,
            question_key=question_key,
            answer=text,
            question=question,
        )

        updated = 0
        if apply_to_open_applications:
            for row in self._answers.open_answers_for_key(profile.id, question_key):
                if not row.requires_user_input and row.answer.strip():
                    continue
                apply_saved_answer(row, saved)
                updated += 1
            self._session.flush()
            if updated:
                self._answers.record_use(saved, updated)

        self._audit.record(
            "answer_bank.resolved",
            entity_type="saved_answer",
            entity_id=saved.id,
            detail={"question_key": question_key, "applications_updated": updated},
        )
        logger.info(
            "answer bank entry applied",
            extra={"question_key": question_key, "applications_updated": updated},
        )
        return ResolveResult(
            question_key=question_key,
            saved=saved,
            applications_updated=updated,
            skipped_closed=0,
        )


def apply_saved_answer(row: ApplicationAnswer, saved: SavedAnswer) -> ApplicationAnswer:
    """Copy a banked answer onto an application answer, preserving its provenance."""
    row.answer = saved.answer
    row.provenance = saved.provenance
    row.requires_user_input = False
    row.flag_reason = ""
    row.source_field = f"answer_bank:{saved.question_key}"
    return row
