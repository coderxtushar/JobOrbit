"""Candidate profile persistence."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CandidateProfile


class ProfileRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, profile_id: int) -> CandidateProfile | None:
        return self._session.get(CandidateProfile, profile_id)

    def get_default(self) -> CandidateProfile | None:
        """The single local user's profile, i.e. the lowest-id row."""
        return self._session.scalars(
            select(CandidateProfile).order_by(CandidateProfile.id).limit(1)
        ).first()

    def get_or_create_default(self) -> CandidateProfile:
        existing = self.get_default()
        if existing is not None:
            return existing
        profile = CandidateProfile()
        self._session.add(profile)
        self._session.flush()
        return profile

    def update(self, profile: CandidateProfile, changes: dict[str, Any]) -> CandidateProfile:
        for field, value in changes.items():
            if not hasattr(profile, field):
                raise AttributeError(f"unknown profile field: {field}")
            setattr(profile, field, value)
        self._session.flush()
        return profile
