"""Batch run and answer-bank request/response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import (
    AnswerProvenance,
    BatchItemStatus,
    BatchStatus,
    SourceName,
)


class BatchSelectionIn(BaseModel):
    """Which jobs to pull into a run. Every field narrows the selection."""

    min_score: float | None = Field(default=None, ge=0, le=100)
    bands: list[str] = Field(default_factory=list)
    max_age_days: int | None = Field(default=None, ge=1, le=365)
    titles: list[str] = Field(default_factory=list)
    sources: list[SourceName] = Field(default_factory=list)
    include_filtered: bool = False
    include_unscored: bool = False
    limit: int = Field(default=100, ge=1, le=5000)


class BatchStartRequest(BaseModel):
    selection: BatchSelectionIn = Field(default_factory=BatchSelectionIn)
    concurrency: int = Field(default=4, ge=1, le=16)
    max_attempts: int = Field(default=3, ge=1, le=10)
    dry_run: bool = False
    include_cover_letter: bool = True
    run_in_background: bool = True


class BatchItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    application_id: int | None = None
    status: BatchItemStatus
    attempts: int
    blocking_questions: int
    detail: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    job_title: str = ""
    job_company: str = ""


class BatchRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: BatchStatus
    dry_run: bool
    cancel_requested: bool
    concurrency: int
    max_attempts: int
    selection: dict = Field(default_factory=dict)
    total_items: int
    prepared_count: int
    needs_action_count: int
    skipped_count: int
    failed_count: int
    started_at: datetime
    finished_at: datetime | None = None
    message: str


class BatchRunDetail(BatchRunRead):
    items: list[BatchItemRead] = Field(default_factory=list)
    status_counts: dict[str, int] = Field(default_factory=dict)


class BatchPreview(BaseModel):
    """What a selection would cover, without creating a run."""

    job_ids: list[int]
    total: int


class SavedAnswerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    question_key: str
    question: str
    answer: str
    provenance: AnswerProvenance
    is_sensitive: bool
    times_used: int
    last_used_at: datetime | None = None
    updated_at: datetime


class SavedAnswerWrite(BaseModel):
    answer: str = Field(min_length=1, max_length=5000)
    question: str = Field(default="", max_length=2000)
    apply_to_open_applications: bool = True


class InboxEntryRead(BaseModel):
    question_key: str
    question: str
    is_sensitive: bool
    occurrences: int
    has_saved_answer: bool = False
    application_ids: list[str] = Field(default_factory=list)


class ResolveResponse(BaseModel):
    question_key: str
    applications_updated: int
    answer: SavedAnswerRead
