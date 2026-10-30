"""Candidate profile endpoints."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import Authorized, DbSession, Profile
from app.db.repositories import AuditRepository, ProfileRepository
from app.schemas.profile import ProfileRead, ProfileUpdate

router = APIRouter(prefix="/api/profile", tags=["profile"], dependencies=[Authorized])

SENSITIVE_PROFILE_FIELDS: tuple[str, ...] = (
    "salary_expectation_min",
    "notice_period_days",
    "work_authorization",
    "requires_sponsorship",
    "graduation_date",
    "open_to_relocation",
)


def _unanswered_sensitive(profile) -> list[str]:
    """Fields the user has not supplied. Never filled with a guess."""
    return [name for name in SENSITIVE_PROFILE_FIELDS if getattr(profile, name, None) is None]


def _to_read(profile) -> ProfileRead:
    model = ProfileRead.model_validate(profile)
    return model.model_copy(update={"unanswered_sensitive_fields": _unanswered_sensitive(profile)})


@router.get("", response_model=ProfileRead, summary="Read the candidate profile")
def read_profile(profile: Profile) -> ProfileRead:
    return _to_read(profile)


@router.put(
    "",
    response_model=ProfileRead,
    status_code=status.HTTP_200_OK,
    summary="Update the candidate profile",
)
def update_profile(payload: ProfileUpdate, session: DbSession, profile: Profile) -> ProfileRead:
    """Partial update. Only fields present in the body are written."""
    changes = payload.to_changes()
    updated = ProfileRepository(session).update(profile, changes)
    AuditRepository(session).record(
        "profile.updated",
        entity_type="candidate_profile",
        entity_id=updated.id,
        detail={"fields": sorted(changes)},
    )
    return _to_read(updated)
