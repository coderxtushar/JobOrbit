"""Candidate profile DTOs.

Sensitive fields (salary, notice period, work authorization, sponsorship) are
``Optional`` with a ``None`` default throughout. ``None`` means "the user has not told
us"; it is never interpreted as a value, and no default is ever guessed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_TARGET_TITLES: tuple[str, ...] = (
    "Software Engineer",
    "Software Developer",
    "Backend Developer",
    "Python Developer",
    "Frontend Developer",
    "Full-Stack Developer",
    "AI Engineer",
    "Generative AI Engineer",
    "Agentic AI Engineer",
    "LLM Application Developer",
    "Machine Learning Engineer",
    "Cloud Engineer",
    "DevOps Engineer",
    "Junior Platform Engineer",
)

EXPERIENCE_LEVELS: tuple[str, ...] = ("fresher", "junior", "mid", "senior", "lead")
WORK_ARRANGEMENTS: tuple[str, ...] = ("onsite", "hybrid", "remote")
EMPLOYMENT_TYPES: tuple[str, ...] = (
    "full_time",
    "part_time",
    "internship",
    "contract",
    "temporary",
)


class EducationEntry(BaseModel):
    degree: str = ""
    institution: str = ""
    field_of_study: str = ""
    start_year: str = ""
    end_year: str = ""
    grade: str = ""


class ProjectEntry(BaseModel):
    name: str = ""
    description: str = ""
    technologies: list[str] = Field(default_factory=list)
    url: str = ""


class ScoringWeights(BaseModel):
    """Category weights. Values are relative and normalized before use."""

    skills: float = Field(default=35.0, ge=0, le=100)
    title: float = Field(default=25.0, ge=0, le=100)
    experience: float = Field(default=15.0, ge=0, le=100)
    location: float = Field(default=10.0, ge=0, le=100)
    freshness: float = Field(default=10.0, ge=0, le=100)
    preferences: float = Field(default=5.0, ge=0, le=100)

    @model_validator(mode="after")
    def _reject_all_zero(self) -> ScoringWeights:
        if self.total == 0:
            raise ValueError("at least one scoring weight must be greater than zero")
        return self

    @property
    def total(self) -> float:
        return (
            self.skills
            + self.title
            + self.experience
            + self.location
            + self.freshness
            + self.preferences
        )

    def normalized(self) -> dict[str, float]:
        """Return weights as fractions summing to 1.0."""
        total = self.total
        return {
            "skills": self.skills / total,
            "title": self.title / total,
            "experience": self.experience / total,
            "location": self.location / total,
            "freshness": self.freshness / total,
            "preferences": self.preferences / total,
        }


class ProfileUpdate(BaseModel):
    """Partial update. Only fields present in the request body are written."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=50)
    links: list[str] | None = None

    headline: str | None = Field(default=None, max_length=300)
    experience_level: str | None = None
    years_experience: float | None = Field(default=None, ge=0, le=60)

    target_titles: list[str] | None = None
    technical_skills: list[str] | None = None
    soft_skills: list[str] | None = None

    education: list[EducationEntry] | None = None
    graduation_date: str | None = Field(default=None, max_length=20)
    projects: list[ProjectEntry] | None = None
    certifications: list[str] | None = None

    preferred_locations: list[str] | None = None
    work_arrangements: list[str] | None = None
    employment_types: list[str] | None = None
    open_to_relocation: bool | None = None

    salary_expectation_min: int | None = Field(default=None, ge=0)
    salary_expectation_max: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, max_length=10)
    notice_period_days: int | None = Field(default=None, ge=0, le=365)
    work_authorization: str | None = Field(default=None, max_length=200)
    requires_sponsorship: bool | None = None

    excluded_companies: list[str] | None = None
    excluded_keywords: list[str] | None = None
    minimum_match_score: float | None = Field(default=None, ge=0, le=100)
    max_job_age_days: int | None = Field(default=None, ge=1, le=365)
    scoring_weights: ScoringWeights | None = None
    extra_answers: dict[str, Any] | None = None

    @field_validator("experience_level")
    @classmethod
    def _known_experience_level(cls, value: str | None) -> str | None:
        if value is not None and value not in EXPERIENCE_LEVELS:
            raise ValueError(f"experience_level must be one of {list(EXPERIENCE_LEVELS)}")
        return value

    @field_validator("work_arrangements")
    @classmethod
    def _known_arrangements(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        unknown = sorted(set(value) - set(WORK_ARRANGEMENTS))
        if unknown:
            raise ValueError(f"unknown work arrangement(s): {unknown}")
        return value

    @field_validator("employment_types")
    @classmethod
    def _known_employment_types(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        unknown = sorted(set(value) - set(EMPLOYMENT_TYPES))
        if unknown:
            raise ValueError(f"unknown employment type(s): {unknown}")
        return value

    @field_validator("target_titles", "technical_skills", "soft_skills", "certifications")
    @classmethod
    def _strip_blanks(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [item.strip() for item in value if item and item.strip()]

    @model_validator(mode="after")
    def _salary_range_is_ordered(self) -> ProfileUpdate:
        low, high = self.salary_expectation_min, self.salary_expectation_max
        if low is not None and high is not None and low > high:
            raise ValueError("salary_expectation_min cannot exceed salary_expectation_max")
        return self

    def to_changes(self) -> dict[str, Any]:
        """Convert to a plain dict of ORM column values, omitting unset fields."""
        data = self.model_dump(exclude_unset=True, exclude_none=False)
        if "education" in data and data["education"] is not None:
            data["education"] = [entry.model_dump() for entry in self.education or []]
        if "projects" in data and data["projects"] is not None:
            data["projects"] = [entry.model_dump() for entry in self.projects or []]
        if "scoring_weights" in data and self.scoring_weights is not None:
            data["scoring_weights"] = self.scoring_weights.model_dump()
        return data


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: str
    phone: str
    links: list[str]
    headline: str
    experience_level: str
    years_experience: float
    target_titles: list[str]
    technical_skills: list[str]
    soft_skills: list[str]
    education: list[dict[str, Any]]
    graduation_date: str | None
    projects: list[dict[str, Any]]
    certifications: list[str]
    preferred_locations: list[str]
    work_arrangements: list[str]
    employment_types: list[str]
    open_to_relocation: bool | None
    salary_expectation_min: int | None
    salary_expectation_max: int | None
    salary_currency: str
    notice_period_days: int | None
    work_authorization: str | None
    requires_sponsorship: bool | None
    excluded_companies: list[str]
    excluded_keywords: list[str]
    minimum_match_score: float
    max_job_age_days: int
    scoring_weights: dict[str, Any]
    extra_answers: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    unanswered_sensitive_fields: list[str] = Field(default_factory=list)
