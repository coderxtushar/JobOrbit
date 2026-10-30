"""Resume and resume-variant persistence."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Resume, ResumeVariant


class ResumeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, resume: Resume) -> Resume:
        if resume.is_primary:
            self._clear_primary(resume.profile_id)
        self._session.add(resume)
        self._session.flush()
        return resume

    def get(self, resume_id: int) -> Resume | None:
        return self._session.get(Resume, resume_id)

    def list_for_profile(self, profile_id: int) -> list[Resume]:
        return list(
            self._session.scalars(
                select(Resume)
                .where(Resume.profile_id == profile_id)
                .order_by(Resume.is_primary.desc(), Resume.created_at.desc())
            )
        )

    def get_primary(self, profile_id: int) -> Resume | None:
        primary = self._session.scalars(
            select(Resume).where(Resume.profile_id == profile_id, Resume.is_primary.is_(True))
        ).first()
        if primary is not None:
            return primary
        return self._session.scalars(
            select(Resume).where(Resume.profile_id == profile_id).order_by(Resume.created_at.desc())
        ).first()

    def find_by_hash(self, profile_id: int, sha256: str) -> Resume | None:
        return self._session.scalars(
            select(Resume).where(Resume.profile_id == profile_id, Resume.sha256 == sha256)
        ).first()

    def set_primary(self, resume: Resume) -> Resume:
        self._clear_primary(resume.profile_id)
        resume.is_primary = True
        self._session.flush()
        return resume

    def _clear_primary(self, profile_id: int) -> None:
        for existing in self._session.scalars(
            select(Resume).where(Resume.profile_id == profile_id, Resume.is_primary.is_(True))
        ):
            existing.is_primary = False


class ResumeVariantRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, variant: ResumeVariant) -> ResumeVariant:
        self._session.add(variant)
        self._session.flush()
        return variant

    def get(self, variant_id: int) -> ResumeVariant | None:
        return self._session.get(ResumeVariant, variant_id)

    def list_for_resume(self, resume_id: int) -> list[ResumeVariant]:
        return list(
            self._session.scalars(
                select(ResumeVariant)
                .where(ResumeVariant.resume_id == resume_id)
                .order_by(ResumeVariant.job_family, ResumeVariant.version.desc())
            )
        )

    def latest_for_family(self, resume_id: int, job_family: str) -> ResumeVariant | None:
        return self._session.scalars(
            select(ResumeVariant)
            .where(ResumeVariant.resume_id == resume_id, ResumeVariant.job_family == job_family)
            .order_by(ResumeVariant.version.desc())
        ).first()

    def next_version(self, resume_id: int, job_family: str) -> int:
        latest = self.latest_for_family(resume_id, job_family)
        return 1 if latest is None else latest.version + 1
