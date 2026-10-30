"""Job-match persistence."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import JobMatch


class MatchRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_job(self, job_id: int, profile_id: int) -> JobMatch | None:
        return self._session.scalars(
            select(JobMatch).where(JobMatch.job_id == job_id, JobMatch.profile_id == profile_id)
        ).first()

    def upsert(self, match: JobMatch) -> JobMatch:
        """Replace any previous score for this (job, profile) pair.

        Re-scoring is idempotent: the unique constraint makes a second insert impossible,
        so the existing row's computed fields are overwritten in place.
        """
        existing = self.get_for_job(match.job_id, match.profile_id)
        if existing is None:
            self._session.add(match)
            self._session.flush()
            return match

        for field in (
            "total_score",
            "band",
            "category_scores",
            "weights_used",
            "matched_skills",
            "missing_required_skills",
            "missing_preferred_skills",
            "uncertain_requirements",
            "explanation",
            "filtered_out",
            "filter_reasons",
            "scorer",
            "scored_at",
        ):
            setattr(existing, field, getattr(match, field))
        self._session.flush()
        return existing

    def list_for_profile(self, profile_id: int, limit: int = 100) -> list[JobMatch]:
        return list(
            self._session.scalars(
                select(JobMatch)
                .where(JobMatch.profile_id == profile_id)
                .order_by(JobMatch.total_score.desc())
                .limit(limit)
            )
        )

    def band_counts(self, profile_id: int) -> dict[str, int]:
        rows = self._session.execute(
            select(JobMatch.band, func.count(JobMatch.id))
            .where(JobMatch.profile_id == profile_id)
            .group_by(JobMatch.band)
        ).all()
        return {band: count for band, count in rows}

    def filtered_out_count(self, profile_id: int) -> int:
        return int(
            self._session.scalar(
                select(func.count(JobMatch.id)).where(
                    JobMatch.profile_id == profile_id, JobMatch.filtered_out.is_(True)
                )
            )
            or 0
        )
