"""Application DTOs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import AnswerProvenance, ApplicationStatus, Outcome, SourceName


class AnswerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    question: str
    question_key: str
    answer: str
    provenance: AnswerProvenance
    is_sensitive: bool
    requires_user_input: bool
    flag_reason: str
    source_field: str


class AnswerUpdate(BaseModel):
    """A user edit to one answer. The provenance becomes ``user_entered``."""

    model_config = ConfigDict(extra="forbid")

    id: int
    answer: str = Field(max_length=8000)


class ApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    profile_id: int
    platform: SourceName
    status: ApplicationStatus
    resume_id: int | None
    resume_variant_id: int | None
    resume_version_label: str
    cover_letter: str
    cover_letter_version: int
    cover_letter_generated_by: str
    prepared_at: datetime | None
    reviewed_at: datetime | None
    user_approved: bool
    approved_at: datetime | None
    submitted_at: datetime | None
    submitted_by: str
    confirmation_evidence: str | None
    confirmed_at: datetime | None
    notes: str
    follow_up_date: datetime | None
    outcome: Outcome
    interview_status: str
    created_at: datetime
    updated_at: datetime
    answers: list[AnswerRead] = Field(default_factory=list)

    job_title: str = ""
    job_company: str = ""
    job_url: str = ""
    blocking_questions: list[str] = Field(default_factory=list)


class ApplicationEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_status: ApplicationStatus | None
    to_status: ApplicationStatus
    actor: str
    detail: str
    created_at: datetime


class ApplicationDetail(ApplicationRead):
    events: list[ApplicationEventRead] = Field(default_factory=list)


class PrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: int
    include_cover_letter: bool = True
    extra_questions: list[str] = Field(default_factory=list, max_length=50)


class ApplicationUpdate(BaseModel):
    """Partial update for ``PATCH /api/applications/{id}``.

    ``status`` transitions are validated by the tracking service, not here. Recording a
    submission requires ``submitted_by`` so the audit trail always says who did it; the
    application never submits anything itself.
    """

    model_config = ConfigDict(extra="forbid")

    status: ApplicationStatus | None = None
    cover_letter: str | None = Field(default=None, max_length=20000)
    answers: list[AnswerUpdate] | None = None
    notes: str | None = Field(default=None, max_length=8000)
    follow_up_date: datetime | None = None
    outcome: Outcome | None = None
    interview_status: str | None = Field(default=None, max_length=100)
    user_approved: bool | None = None
    submitted_by: str | None = Field(default=None, max_length=50)
    confirmation_evidence: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _confirmation_requires_evidence(self) -> ApplicationUpdate:
        if (
            self.status == ApplicationStatus.CONFIRMED
            and not (self.confirmation_evidence or "").strip()
        ):
            raise ValueError(
                "CONFIRMED requires confirmation_evidence, for example the confirmation "
                "email subject or the reference number shown by the employer"
            )
        if self.status == ApplicationStatus.SUBMITTED and not (self.submitted_by or "").strip():
            raise ValueError("SUBMITTED requires submitted_by, recording who submitted it")
        return self
