"""Saved-search request and response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.repositories.searches import ALLOWED_CRITERIA
from app.schemas.job import JobRead


class SavedSearchCriteria(BaseModel):
    """The filters a saved search may carry.

    Mirrors the subset :data:`~app.db.repositories.searches.ALLOWED_CRITERIA` permits, and
    a test asserts the two stay in step: the stored blob is replayed into a database query,
    so a field accepted here but unknown to the repository would be silently dropped.
    """

    model_config = ConfigDict(extra="forbid")

    search: str | None = Field(default=None, max_length=200)
    statuses: list[str] | None = None
    sources: list[str] | None = None
    company: str | None = Field(default=None, max_length=200)
    min_score: float | None = Field(default=None, ge=0, le=100)
    max_age_days: int | None = Field(default=None, ge=1, le=365)
    bands: list[str] | None = None
    include_duplicates: bool | None = None
    sort_by: str | None = None
    descending: bool | None = None

    @field_validator("bands")
    @classmethod
    def _known_bands(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        allowed = {"high", "review", "low"}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unknown band(s): {', '.join(unknown)}")
        return value

    def to_storage(self) -> dict[str, object]:
        return {
            key: value
            for key, value in self.model_dump(exclude_none=True).items()
            if key in ALLOWED_CRITERIA
        }


class SavedSearchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    criteria: SavedSearchCriteria = Field(default_factory=SavedSearchCriteria)


class SavedSearchUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    criteria: SavedSearchCriteria | None = None


class SavedSearchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    criteria: dict
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SavedSearchDigest(BaseModel):
    """What a search found, separating what is new from what the user has already seen."""

    search_id: int
    name: str
    total_matching: int
    new_since_last_run: int
    previous_run_at: datetime | None
    jobs: list[JobRead]
