"""Job DTOs.

:class:`RawJobRecord` is the contract every source adapter must produce. It is deliberately
permissive about missing data (``posted_at`` may be absent) and strict about provenance
(``source`` and at least one of ``external_id`` / ``url`` are required), because a record
with no provenance cannot be deduplicated or revisited later.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.models import (
    EmploymentType,
    JobStatus,
    SourceName,
    WorkArrangement,
)


class RawJobRecord(BaseModel):
    """A job as received from a source, before normalization."""

    model_config = ConfigDict(extra="ignore")

    source: SourceName
    external_id: str | None = Field(default=None, max_length=300)
    title: str = Field(min_length=1, max_length=400)
    company: str = Field(min_length=1, max_length=300)
    location: str = Field(default="", max_length=300)
    url: str = Field(default="", max_length=1200)

    work_arrangement: str | None = None
    employment_type: str | None = None
    salary_raw: str = Field(default="", max_length=200)
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, max_length=10)

    experience_raw: str = Field(default="", max_length=200)
    experience_min_years: float | None = Field(default=None, ge=0, le=60)
    experience_max_years: float | None = Field(default=None, ge=0, le=60)

    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    education_requirements: list[str] = Field(default_factory=list)

    description: str = ""
    # Accepts a datetime or the source's raw string ("3 days ago", "15 Jan 2026").
    # Resolution happens in normalization, which flags relative values as approximate.
    posted_at: datetime | str | None = None
    posted_at_is_approximate: bool = False
    application_method: str = Field(default="external_site", max_length=100)
    retrieval_method: str = Field(default="manual_import", max_length=100)
    source_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title", "company")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @field_validator("required_skills", "preferred_skills", "education_requirements")
    @classmethod
    def _clean_list(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()]

    @model_validator(mode="after")
    def _require_provenance(self) -> RawJobRecord:
        if not self.external_id and not self.url.strip():
            raise ValueError("a job record needs an external_id or a url to be traceable")
        return self


class JobImportRequest(BaseModel):
    """Body for ``POST /api/jobs/import``."""

    model_config = ConfigDict(extra="forbid")

    records: list[RawJobRecord] = Field(min_length=1, max_length=2000)
    trigger: str = Field(default="manual", max_length=50)


class SourceReferenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: SourceName
    external_id: str | None
    url: str
    retrieved_at: datetime
    retrieval_method: str


class MatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_score: float
    band: str
    evidence_coverage: float
    confidence: str
    confidence_reasons: list[str]
    category_scores: dict[str, Any]
    weights_used: dict[str, Any]
    matched_skills: list[str]
    missing_required_skills: list[str]
    missing_preferred_skills: list[str]
    uncertain_requirements: list[str]
    explanation: list[str]
    filtered_out: bool
    filter_reasons: list[str]
    scorer: str
    scored_at: datetime


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    company: str
    location: str
    work_arrangement: WorkArrangement
    employment_type: EmploymentType
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    salary_raw: str
    experience_min_years: float | None
    experience_max_years: float | None
    experience_raw: str
    required_skills: list[str]
    preferred_skills: list[str]
    education_requirements: list[str]
    url: str
    canonical_url: str
    application_method: str
    posted_at: datetime | None
    posted_at_is_approximate: bool
    discovered_at: datetime
    status: JobStatus
    duplicate_of_id: int | None
    fingerprint: str
    source_references: list[SourceReferenceRead] = Field(default_factory=list)
    match: MatchRead | None = None
    duplicate_count: int = 0
    has_application: bool = False


class JobDetail(JobRead):
    description: str = ""


class ImportSummary(BaseModel):
    """Outcome of one import or discovery run."""

    import_run_id: int
    source: SourceName
    status: str
    records_received: int
    records_invalid: int
    jobs_created: int
    jobs_updated: int
    duplicates_detected: int
    message: str = ""
    errors: list[str] = Field(default_factory=list)
    #: Non-fatal notes from normalization, kept apart from ``errors`` because merging the
    #: two made a clean import report ten "errors" for nothing worse than an employer
    #: omitting a skills list.
    warnings: list[str] = Field(default_factory=list)


class ScoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_ids: list[int] | None = None
    rescore_all: bool = False


class ScoreSummary(BaseModel):
    scored: int
    filtered_out: int
    high: int
    review: int
    low: int
    scorer: str
    failures: list[str] = Field(default_factory=list)


class DiscoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[SourceName] | None = None
    trigger: str = Field(default="manual", max_length=50)
