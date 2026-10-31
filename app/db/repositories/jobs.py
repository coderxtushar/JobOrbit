"""Job and job-source-reference persistence.

All query construction for jobs lives here. Routes and services pass plain values, which
is what keeps the PostgreSQL migration to a connection-string change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Job, JobMatch, JobSourceReference, JobStatus, SourceName, utcnow


@dataclass(slots=True)
class JobQuery:
    """Filter/sort/pagination parameters for a job listing query."""

    search: str | None = None
    statuses: list[JobStatus] = field(default_factory=list)
    sources: list[SourceName] = field(default_factory=list)
    company: str | None = None
    min_score: float | None = None
    max_age_days: int | None = None
    include_duplicates: bool = False
    unscored_only: bool = False
    profile_id: int | None = None
    sort_by: str = "score"
    descending: bool = True
    limit: int = 25
    offset: int = 0


#: Alias used for return annotations inside :class:`JobRepository`. The class defines a
#: method called ``list``, which shadows the builtin inside the class body and makes a
#: bare ``list[Job]`` annotation resolve to that method instead of the generic type.
JobList = list[Job]

#: Band is the honest summary of a match; the raw score is only comparable *within* a band.
#: A listing that published nothing but a title can score in the high nineties on the one
#: category that could be assessed, so ordering by score alone put it above fully-assessed
#: matches. Ranking by band first keeps the number auditable while fixing what the user sees.
_BAND_RANK = case(
    (JobMatch.band == "high", 0),
    (JobMatch.band == "review", 1),
    (JobMatch.band == "low", 2),
    else_=3,
)

#: Within one band, evidence decides the order before the number does. Measured on 7,791
#: real listings: three rows whose title, company and location were each a single character
#: scored 100.0 from the one category that could be assessed (20% coverage, low confidence)
#: and sat at the top of the review band, above fully-assessed matches at 71-77. The band
#: gate had already demoted them; this orders what is left inside the band, and like the
#: band gate it changes only the ordering, never the score.
_CONFIDENCE_RANK = case(
    (JobMatch.confidence == "high", 0),
    (JobMatch.confidence == "medium", 1),
    (JobMatch.confidence == "low", 2),
    else_=3,
)

_SORT_COLUMNS = {
    "score": JobMatch.total_score,
    "posted_at": Job.posted_at,
    "discovered_at": Job.discovered_at,
    "company": Job.company_normalized,
    "title": Job.title,
}


class JobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ---------------- writes ----------------

    def add(self, job: Job) -> Job:
        self._session.add(job)
        self._session.flush()
        return job

    def get(self, job_id: int) -> Job | None:
        return self._session.get(Job, job_id)

    def find_by_fingerprint(self, fingerprint: str) -> Job | None:
        return self._session.scalars(select(Job).where(Job.fingerprint == fingerprint)).first()

    def find_by_canonical_url(self, canonical_url: str) -> Job | None:
        if not canonical_url:
            return None
        return self._session.scalars(select(Job).where(Job.canonical_url == canonical_url)).first()

    def find_by_source_id(self, source: SourceName, external_id: str) -> Job | None:
        if not external_id:
            return None
        reference = self._session.scalars(
            select(JobSourceReference).where(
                JobSourceReference.source == source,
                JobSourceReference.external_id == external_id,
            )
        ).first()
        return reference.job if reference is not None else None

    def add_source_reference(self, reference: JobSourceReference) -> JobSourceReference:
        self._session.add(reference)
        self._session.flush()
        return reference

    def has_source_reference(
        self, job_id: int, source: SourceName, external_id: str | None
    ) -> bool:
        statement = select(func.count(JobSourceReference.id)).where(
            JobSourceReference.job_id == job_id, JobSourceReference.source == source
        )
        if external_id:
            statement = statement.where(JobSourceReference.external_id == external_id)
        return bool(self._session.scalar(statement))

    def set_status(self, job: Job, status: JobStatus) -> Job:
        job.status = status
        self._session.flush()
        return job

    def mark_expired_before(self, cutoff: datetime) -> int:
        """Mark listings whose posting date is older than ``cutoff`` as expired."""
        jobs = self._session.scalars(
            select(Job).where(
                Job.posted_at.is_not(None),
                Job.posted_at < cutoff,
                Job.status.not_in([JobStatus.EXPIRED, JobStatus.DUPLICATE]),
            )
        ).all()
        for job in jobs:
            job.status = JobStatus.EXPIRED
        self._session.flush()
        return len(jobs)

    # ---------------- reads ----------------

    def _apply_filters(self, statement: Select[tuple], query: JobQuery) -> Select[tuple]:
        if not query.include_duplicates:
            statement = statement.where(Job.duplicate_of_id.is_(None))
        if query.statuses:
            statement = statement.where(Job.status.in_(query.statuses))
        if query.company:
            statement = statement.where(Job.company_normalized.like(f"%{query.company.lower()}%"))
        if query.search:
            pattern = f"%{query.search.lower()}%"
            statement = statement.where(
                or_(
                    func.lower(Job.title).like(pattern),
                    func.lower(Job.company).like(pattern),
                    func.lower(Job.description).like(pattern),
                )
            )
        if query.sources:
            statement = statement.where(
                Job.id.in_(
                    select(JobSourceReference.job_id).where(
                        JobSourceReference.source.in_(query.sources)
                    )
                )
            )
        if query.max_age_days is not None:
            cutoff = utcnow() - timedelta(days=query.max_age_days)
            # A job with no posting date is kept: absence of a date is not evidence of age.
            statement = statement.where(or_(Job.posted_at.is_(None), Job.posted_at >= cutoff))
        if query.unscored_only and query.profile_id is not None:
            statement = statement.where(
                Job.id.notin_(
                    select(JobMatch.job_id).where(JobMatch.profile_id == query.profile_id)
                )
            )
        if query.min_score is not None and query.profile_id is not None:
            statement = statement.where(
                Job.id.in_(
                    select(JobMatch.job_id).where(
                        JobMatch.profile_id == query.profile_id,
                        JobMatch.total_score >= query.min_score,
                    )
                )
            )
        return statement

    def count(self, query: JobQuery) -> int:
        statement = self._apply_filters(select(func.count(func.distinct(Job.id))), query)
        return int(self._session.scalar(statement) or 0)

    def list(self, query: JobQuery) -> JobList:
        statement = self._apply_filters(select(Job), query)

        column: Any
        band_first = False
        if query.sort_by == "score":
            # Sorting by score requires the match row, which only exists per profile.
            # Without a profile there is nothing to sort by, so fall back to recency
            # rather than emitting a reference to an unjoined table.
            if query.profile_id is None:
                column = Job.discovered_at
            else:
                statement = statement.outerjoin(
                    JobMatch,
                    (JobMatch.job_id == Job.id) & (JobMatch.profile_id == query.profile_id),
                )
                column = JobMatch.total_score
                band_first = True
        else:
            column = _SORT_COLUMNS.get(query.sort_by, Job.discovered_at)

        ordering = column.desc() if query.descending else column.asc()
        if band_first and query.descending:
            statement = statement.order_by(
                _BAND_RANK.asc(),
                _CONFIDENCE_RANK.asc(),
                ordering.nullslast(),
                Job.id.desc(),
            )
        else:
            statement = statement.order_by(ordering.nullslast(), Job.id.desc())
        statement = statement.limit(query.limit).offset(query.offset)
        return list(self._session.scalars(statement).unique())

    def duplicates_of(self, job_id: int) -> JobList:
        return list(self._session.scalars(select(Job).where(Job.duplicate_of_id == job_id)))

    def status_counts(self) -> dict[str, int]:
        rows = self._session.execute(
            select(Job.status, func.count(Job.id)).group_by(Job.status)
        ).all()
        return {status.value: count for status, count in rows}
