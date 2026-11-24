"""Schemas for salary normalisation, company research and interview preparation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CompensationRead(BaseModel):
    """A parsed salary. ``assumptions`` lists every step that was not a literal reading."""

    original: str
    currency: str | None
    period: str | None
    minimum: float | None
    maximum: float | None
    annual_minimum: float | None
    annual_maximum: float | None
    inr_annual_minimum: float | None
    inr_annual_maximum: float | None
    is_range: bool
    disclosed: bool
    assumptions: list[str]
    currency_stated: bool
    period_stated: bool
    scale: str


class ConversionRead(BaseModel):
    value: str
    exact: bool
    assumptions: list[str]


class SalaryParseRead(BaseModel):
    compensation: CompensationRead
    #: The same figure proposed in every unit a form might ask for. Proposals only.
    proposals: dict[str, ConversionRead]


class SalaryComparison(BaseModel):
    comparable: bool
    statement: str


class JobSalaryRead(BaseModel):
    job_id: int
    job_title: str
    company: str
    listing: CompensationRead
    listing_source: str
    expectation: CompensationRead
    comparison: SalaryComparison


class CompanyRefreshRequest(BaseModel):
    """``website`` must be a URL you supply; JobOrbit never guesses one from a name."""

    website: str | None = Field(default=None, max_length=600)
    fetch_website: bool = False

    @field_validator("website")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        stripped = (value or "").strip()
        return stripped or None


class CompanyResearchRead(BaseModel):
    company: str
    company_normalized: str
    website: str
    refreshed_at: str | None
    from_cache: bool
    data: dict[str, Any]
    sources: list[dict[str, Any]]
    job_context: dict[str, Any] | None = None


class InterviewPrepGenerate(BaseModel):
    regenerate: bool = False


class InterviewPrepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    content: dict[str, Any]
    practice: list[dict[str, Any]]
    generated_at: datetime
    updated_at: datetime
    interview_stage: bool = False
    next_question: dict[str, Any] | None = None


class PracticeRequest(BaseModel):
    question_id: str = Field(min_length=1, max_length=64)
    answer: str = Field(default="", max_length=5000)


class PracticeResult(BaseModel):
    question: dict[str, Any]
    feedback: dict[str, Any]
    practice_count: int
    next_question: dict[str, Any] | None = None


class NextQuestionRead(BaseModel):
    question: dict[str, Any] | None


class InterviewRoundBase(BaseModel):
    round_name: str = Field(default="", max_length=120)
    scheduled_at: datetime | None = None
    interviewer_notes: str = Field(default="", max_length=20_000)
    questions_asked: list[str] = Field(default_factory=list, max_length=50)
    feedback: str = Field(default="", max_length=20_000)
    next_steps: str = Field(default="", max_length=5_000)

    @field_validator("scheduled_at")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("scheduled_at must include a timezone offset")
        return value


class InterviewRoundCreate(InterviewRoundBase):
    pass


class InterviewRoundUpdate(BaseModel):
    """Only the fields sent are changed."""

    round_name: str | None = Field(default=None, max_length=120)
    scheduled_at: datetime | None = None
    interviewer_notes: str | None = Field(default=None, max_length=20_000)
    questions_asked: list[str] | None = Field(default=None, max_length=50)
    feedback: str | None = Field(default=None, max_length=20_000)
    next_steps: str | None = Field(default=None, max_length=5_000)

    @field_validator("scheduled_at")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("scheduled_at must include a timezone offset")
        return value


class InterviewRoundRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    round_name: str
    scheduled_at: datetime | None
    interviewer_notes: str
    questions_asked: list[str]
    feedback: str
    next_steps: str
    created_at: datetime
    updated_at: datetime
