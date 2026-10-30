"""Resume and resume-variant DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ParsedResumeFields(BaseModel):
    """What the parser found. Absent fields are omitted, never invented."""

    full_name: str = ""
    email: str = ""
    phone: str = ""
    links: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    education: list[dict[str, Any]] = Field(default_factory=list)
    projects: list[dict[str, Any]] = Field(default_factory=list)
    experience: list[dict[str, Any]] = Field(default_factory=list)
    internships: list[dict[str, Any]] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)
    graduation_date: str | None = None
    estimated_years_experience: float | None = None
    field_confidence: dict[str, float] = Field(default_factory=dict)


class ResumeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    profile_id: int
    label: str
    original_filename: str
    content_type: str
    file_size_bytes: int
    sha256: str
    is_primary: bool
    parse_warnings: list[str]
    extracted_fields: dict[str, Any]
    created_at: datetime
    text_character_count: int = 0
    variant_count: int = 0


class ResumeUploadResponse(BaseModel):
    """Returned after upload.

    ``applied_to_profile`` is always ``False``: extraction is a proposal that the user
    confirms on the review screen before anything is written to the profile.
    """

    resume: ResumeRead
    parsed: ParsedResumeFields
    applied_to_profile: bool = False
    review_required: bool = True


class VariantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resume_id: int | None = None
    job_family: str = Field(min_length=1, max_length=100)
    emphasised_skills: list[str] = Field(default_factory=list)
    name: str = Field(default="", max_length=200)


class VariantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    resume_id: int
    name: str
    job_family: str
    version: int
    emphasised_skills: list[str]
    included_items: dict[str, Any]
    content: str
    generated_by: str
    created_at: datetime
