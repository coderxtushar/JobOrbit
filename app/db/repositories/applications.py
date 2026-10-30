"""Application, answer and event persistence."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Application,
    ApplicationAnswer,
    ApplicationEvent,
    ApplicationStatus,
    Outcome,
)


class DuplicateApplicationError(RuntimeError):
    """Raised when an application already exists for a (job, profile) pair."""

    def __init__(self, application_id: int, job_id: int) -> None:
        super().__init__(
            f"an application for job {job_id} already exists (application {application_id})"
        )
        self.application_id = application_id
        self.job_id = job_id


@dataclass(slots=True)
class ApplicationQuery:
    statuses: list[ApplicationStatus] = field(default_factory=list)
    outcomes: list[Outcome] = field(default_factory=list)
    profile_id: int | None = None
    limit: int = 25
    offset: int = 0


class ApplicationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, application_id: int) -> Application | None:
        return self._session.get(Application, application_id)

    def find_for_job(self, job_id: int, profile_id: int) -> Application | None:
        return self._session.scalars(
            select(Application).where(
                Application.job_id == job_id, Application.profile_id == profile_id
            )
        ).first()

    def create(self, application: Application) -> Application:
        existing = self.find_for_job(application.job_id, application.profile_id)
        if existing is not None:
            raise DuplicateApplicationError(existing.id, existing.job_id)
        self._session.add(application)
        self._session.flush()
        return application

    def add_answer(self, answer: ApplicationAnswer) -> ApplicationAnswer:
        self._session.add(answer)
        self._session.flush()
        return answer

    def replace_answers(
        self, application: Application, answers: list[ApplicationAnswer]
    ) -> list[ApplicationAnswer]:
        for existing in list(application.answers):
            self._session.delete(existing)
        self._session.flush()
        for answer in answers:
            answer.application_id = application.id
            self._session.add(answer)
        self._session.flush()
        self._session.refresh(application)
        return list(application.answers)

    def get_answer(self, answer_id: int) -> ApplicationAnswer | None:
        return self._session.get(ApplicationAnswer, answer_id)

    def add_event(self, event: ApplicationEvent) -> ApplicationEvent:
        self._session.add(event)
        self._session.flush()
        return event

    def _apply_filters(self, statement: Select[tuple], query: ApplicationQuery) -> Select[tuple]:
        if query.statuses:
            statement = statement.where(Application.status.in_(query.statuses))
        if query.outcomes:
            statement = statement.where(Application.outcome.in_(query.outcomes))
        if query.profile_id is not None:
            statement = statement.where(Application.profile_id == query.profile_id)
        return statement

    def list(self, query: ApplicationQuery) -> list[Application]:
        statement = self._apply_filters(select(Application), query)
        statement = (
            statement.order_by(Application.updated_at.desc())
            .limit(query.limit)
            .offset(query.offset)
        )
        return list(self._session.scalars(statement).unique())

    def count(self, query: ApplicationQuery) -> int:
        statement = self._apply_filters(select(func.count(Application.id)), query)
        return int(self._session.scalar(statement) or 0)

    def status_counts(self) -> dict[str, int]:
        rows = self._session.execute(
            select(Application.status, func.count(Application.id)).group_by(Application.status)
        ).all()
        return {status.value: count for status, count in rows}

    def outcome_counts(self) -> dict[str, int]:
        rows = self._session.execute(
            select(Application.outcome, func.count(Application.id)).group_by(Application.outcome)
        ).all()
        return {outcome.value: count for outcome, count in rows}
