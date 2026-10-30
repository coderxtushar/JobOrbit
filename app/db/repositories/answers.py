"""Answer bank and action-inbox queries.

The action inbox is *derived*, not stored. One unanswered question appearing on eighty
applications is a single inbox row with a count of eighty, computed by grouping
``application_answer`` on ``question_key``. Storing it separately would create a second
copy of the same fact that could drift from the applications it describes.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    AnswerProvenance,
    Application,
    ApplicationAnswer,
    ApplicationStatus,
    SavedAnswer,
    utcnow,
)

#: Alias used for return annotations inside the class below. The class defines a
#: method called ``list``, which shadows the builtin inside the class body and makes
#: a bare ``list[X]`` annotation resolve to that method instead of the generic type.
SavedAnswerList = list[SavedAnswer]
AppAnswerList = list[ApplicationAnswer]

BANKABLE_PROVENANCE: frozenset[AnswerProvenance] = frozenset(
    {AnswerProvenance.USER_ENTERED, AnswerProvenance.PROFILE_VERIFIED}
)

#: An application in one of these states is finished; backfilling its answers would
#: rewrite the record of what was actually sent to the employer.
_CLOSED_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.CONFIRMED,
        ApplicationStatus.SKIPPED,
    }
)


class UnbankableAnswerError(ValueError):
    """Raised when an answer's provenance disqualifies it from reuse."""

    def __init__(self, provenance: AnswerProvenance) -> None:
        super().__init__(
            f"an answer with provenance '{provenance.value}' cannot be saved to the answer "
            "bank; only answers you entered or verified in your profile are reusable"
        )
        self.provenance = provenance


@dataclass(slots=True)
class InboxEntry:
    question_key: str
    question: str
    is_sensitive: bool
    occurrences: int
    application_ids: list[str]
    example_jobs: list[str]


InboxList = list[InboxEntry]


class SavedAnswerRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, profile_id: int, question_key: str) -> SavedAnswer | None:
        return self._session.scalars(
            select(SavedAnswer).where(
                SavedAnswer.profile_id == profile_id,
                SavedAnswer.question_key == question_key,
            )
        ).first()

    def list(self, profile_id: int) -> SavedAnswerList:
        return list(
            self._session.scalars(
                select(SavedAnswer)
                .where(SavedAnswer.profile_id == profile_id)
                .order_by(SavedAnswer.question_key)
            )
        )

    def as_map(self, profile_id: int) -> dict[str, SavedAnswer]:
        return {entry.question_key: entry for entry in self.list(profile_id)}

    def upsert(
        self,
        *,
        profile_id: int,
        question_key: str,
        question: str,
        answer: str,
        provenance: AnswerProvenance = AnswerProvenance.USER_ENTERED,
        is_sensitive: bool = False,
    ) -> SavedAnswer:
        if provenance not in BANKABLE_PROVENANCE:
            raise UnbankableAnswerError(provenance)

        existing = self.get(profile_id, question_key)
        if existing is None:
            existing = SavedAnswer(profile_id=profile_id, question_key=question_key)
            self._session.add(existing)
        existing.question = question or existing.question
        existing.answer = answer
        existing.provenance = provenance
        existing.is_sensitive = is_sensitive
        self._session.flush()
        return existing

    def record_use(self, entry: SavedAnswer, count: int = 1) -> None:
        entry.times_used += count
        entry.last_used_at = utcnow()
        self._session.flush()

    def delete(self, profile_id: int, question_key: str) -> bool:
        existing = self.get(profile_id, question_key)
        if existing is None:
            return False
        self._session.delete(existing)
        self._session.flush()
        return True

    def open_answers_for_key(self, profile_id: int, question_key: str) -> AppAnswerList:
        """Every still-editable answer row for one question across all applications."""
        return list(
            self._session.scalars(
                select(ApplicationAnswer)
                .join(Application, Application.id == ApplicationAnswer.application_id)
                .where(
                    Application.profile_id == profile_id,
                    Application.status.notin_(_CLOSED_STATUSES),
                    ApplicationAnswer.question_key == question_key,
                )
            )
        )

    def inbox(self, profile_id: int, *, limit: int = 100) -> InboxList:
        """Outstanding questions grouped by key, most frequent first."""
        rows = self._session.execute(
            select(
                ApplicationAnswer.question_key,
                func.min(ApplicationAnswer.question),
                func.max(ApplicationAnswer.is_sensitive),
                func.count(ApplicationAnswer.id),
            )
            .join(Application, Application.id == ApplicationAnswer.application_id)
            .where(
                Application.profile_id == profile_id,
                Application.status.notin_(_CLOSED_STATUSES),
                ApplicationAnswer.requires_user_input.is_(True),
            )
            .group_by(ApplicationAnswer.question_key)
            .order_by(func.count(ApplicationAnswer.id).desc(), ApplicationAnswer.question_key)
            .limit(limit)
        ).all()

        entries: list[InboxEntry] = []
        for key, question, sensitive, occurrences in rows:
            detail = self._session.execute(
                select(Application.id, Application.job_id)
                .join(ApplicationAnswer, ApplicationAnswer.application_id == Application.id)
                .where(
                    Application.profile_id == profile_id,
                    Application.status.notin_(_CLOSED_STATUSES),
                    ApplicationAnswer.question_key == key,
                    ApplicationAnswer.requires_user_input.is_(True),
                )
                .limit(5)
            ).all()
            entries.append(
                InboxEntry(
                    question_key=key,
                    question=question or key,
                    is_sensitive=bool(sensitive),
                    occurrences=int(occurrences),
                    application_ids=[str(row[0]) for row in detail],
                    example_jobs=[str(row[1]) for row in detail],
                )
            )
        return entries
