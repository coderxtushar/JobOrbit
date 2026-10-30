"""Scoring service.

Wraps the pure scorer in :mod:`app.services.matching` with persistence: it loads the jobs,
checks whether each already has an application (which is a hard filter), writes the
:class:`JobMatch` row, and updates the job's status.

A job that fails a hard filter is still scored and stored, with ``filtered_out=True`` and
the reasons attached, so the user can see *why* something was excluded instead of finding
it missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.db.models import (
    CandidateProfile,
    Job,
    JobMatch,
    JobStatus,
    utcnow,
)
from app.db.repositories import (
    ApplicationRepository,
    AuditRepository,
    JobQuery,
    JobRepository,
    MatchRepository,
)
from app.logging_conf import get_logger
from app.services.filters import FilterContext
from app.services.matching import score_job, weights_for

logger = get_logger(__name__)


@dataclass(slots=True)
class ScoreReport:
    scored: int = 0
    filtered_out: int = 0
    high: int = 0
    review: int = 0
    low: int = 0
    failures: list[str] = field(default_factory=list)
    scorer: str = "rule_based"


class ScoringService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._jobs = JobRepository(session)
        self._matches = MatchRepository(session)
        self._applications = ApplicationRepository(session)
        self._audit = AuditRepository(session)

    def score_one(self, job: Job, profile: CandidateProfile) -> JobMatch:
        already_applied = self._applications.find_for_job(job.id, profile.id) is not None
        result = score_job(
            job, profile, filter_context=FilterContext(already_applied=already_applied)
        )
        match = self._matches.upsert(
            JobMatch(
                job_id=job.id,
                profile_id=profile.id,
                total_score=result.total_score,
                band=result.band,
                evidence_coverage=result.evidence_coverage,
                confidence=result.confidence,
                confidence_reasons=result.confidence_reasons,
                category_scores=result.category_scores,
                weights_used=weights_for(profile).normalized(),
                matched_skills=result.matched_skills,
                missing_required_skills=result.missing_required_skills,
                missing_preferred_skills=result.missing_preferred_skills,
                uncertain_requirements=result.uncertain_requirements,
                explanation=result.explanation,
                filtered_out=result.filtered_out,
                filter_reasons=result.filter_reasons,
                scorer=result.scorer,
                scored_at=utcnow(),
            )
        )

        if result.filtered_out:
            if job.status in (JobStatus.DISCOVERED, JobStatus.SCORED):
                self._jobs.set_status(job, JobStatus.FILTERED_OUT)
        elif job.status in (JobStatus.DISCOVERED, JobStatus.FILTERED_OUT):
            self._jobs.set_status(job, JobStatus.SCORED)
        return match

    def score_many(
        self,
        profile: CandidateProfile,
        *,
        job_ids: list[int] | None = None,
        rescore_all: bool = False,
    ) -> ScoreReport:
        """Score the requested jobs, or every unscored job when nothing is specified."""
        report = ScoreReport()

        if job_ids:
            jobs = [
                job for job in (self._jobs.get(job_id) for job_id in job_ids) if job is not None
            ]
            missing = set(job_ids) - {job.id for job in jobs}
            report.failures.extend(f"job {job_id} does not exist" for job_id in sorted(missing))
        else:
            statuses = (
                None
                if rescore_all
                else [JobStatus.DISCOVERED, JobStatus.SCORED, JobStatus.FILTERED_OUT]
            )
            query = JobQuery(
                statuses=statuses or [],
                limit=2000,
                sort_by="discovered_at",
                profile_id=profile.id,
            )
            jobs = self._jobs.list(query)

        for job in jobs:
            try:
                match = self.score_one(job, profile)
            except Exception as exc:
                report.failures.append(f"job {job.id}: {type(exc).__name__}: {exc}")
                logger.exception("scoring failed", extra={"job_id": job.id})
                continue
            report.scored += 1
            if match.filtered_out:
                report.filtered_out += 1
            if match.band == "high":
                report.high += 1
            elif match.band == "review":
                report.review += 1
            else:
                report.low += 1

        self._audit.record(
            "jobs.scored",
            entity_type="candidate_profile",
            entity_id=profile.id,
            detail={
                "scored": report.scored,
                "filtered_out": report.filtered_out,
                "high": report.high,
                "review": report.review,
                "low": report.low,
                "failures": len(report.failures),
            },
        )
        self._session.flush()
        return report
