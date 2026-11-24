"""Auto-apply request and response models.

``confirmed`` and ``prepared`` are separate fields everywhere in this module, and nothing
aggregates them into a single "processed" number. A prepared application and a confirmed
submission are different claims about what happened, and a client that cannot tell them
apart will eventually show the wrong one.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.models import SourceName
from app.services.autoapply import ALLOWED_AGE_HOURS


class AutoApplyTargetsIn(BaseModel):
    """The scope one click authorises."""

    model_config = ConfigDict(extra="forbid")

    sources: list[SourceName] = Field(default_factory=list)
    max_discover: int = Field(default=200, ge=0, le=500)
    max_submissions: int = Field(default=100, ge=0, le=500)
    max_age_hours: int = 48
    min_score: float = Field(default=70.0, ge=0, le=100)
    min_confidence: str = Field(default="medium")
    bands: list[str] = Field(default_factory=lambda: ["high", "review"])
    titles: list[str] = Field(default_factory=list)
    excluded_companies: list[str] = Field(default_factory=list)
    concurrency: int = Field(default=4, ge=1, le=16)
    max_attempts: int = Field(default=2, ge=1, le=10)
    #: Defaults to true so the first run a new user starts sends nothing at all.
    dry_run: bool = True
    include_cover_letter: bool = True
    role_families: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    remote_preference: str = "any"
    experience_tolerance_years: float | None = Field(default=1.0, ge=0, le=20)
    daily_cap: int | None = Field(default=None, ge=1, le=500)
    platforms: list[str] = Field(default_factory=list)
    #: The exact job ids the user approved in the preflight. Empty runs the whole plan.
    approved_job_ids: list[int] = Field(default_factory=list, max_length=500)

    @field_validator("remote_preference")
    @classmethod
    def _known_remote_preference(cls, value: str) -> str:
        allowed = ("any", "remote_only", "remote_or_hybrid", "onsite_or_hybrid")
        if value not in allowed:
            raise ValueError(f"remote_preference must be one of {', '.join(allowed)}")
        return value

    @field_validator("max_age_hours")
    @classmethod
    def _known_window(cls, value: int) -> int:
        if value not in ALLOWED_AGE_HOURS:
            allowed = ", ".join(str(hours) for hours in sorted(ALLOWED_AGE_HOURS))
            raise ValueError(f"max_age_hours must be one of {allowed}")
        return value

    @field_validator("min_confidence")
    @classmethod
    def _known_confidence(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"low", "medium", "high"}:
            raise ValueError("min_confidence must be low, medium or high")
        return normalized

    @field_validator("bands")
    @classmethod
    def _known_bands(cls, value: list[str]) -> list[str]:
        allowed = {"high", "review", "low"}
        unknown = [band for band in value if band not in allowed]
        if unknown:
            raise ValueError(f"unknown bands: {', '.join(unknown)}")
        return value


class TargetBreakdown(BaseModel):
    key: str
    display_name: str
    eligible: int
    submission_supported: bool
    reason: str = ""


class RunPreviewRead(BaseModel):
    """What a run would do. ``submittable`` is almost always far below ``eligible``."""

    eligible: int
    submittable: int
    targets: list[TargetBreakdown] = Field(default_factory=list)
    note: str = ""


class SubmissionEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    name: str
    detail: str = ""
    created_at: datetime


class SubmissionAttemptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    application_id: int | None = None
    target_key: str
    state: str
    attempts: int
    confirmation_id: str = ""
    submitted_url: str = ""
    resume_sha256: str = ""
    detail: str = ""
    checkpoint: str = ""
    failure_category: str = ""
    duration_ms: int | None = None
    confirmation_evidence: str = ""
    #: Whether a screenshot exists. The image is served only by the evidence endpoint.
    has_evidence: bool = False
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @field_validator("state", mode="before")
    @classmethod
    def _state_value(cls, value: object) -> str:
        return str(getattr(value, "value", value or ""))

    @model_validator(mode="before")
    @classmethod
    def _evidence_flag(cls, value: object) -> object:
        path = getattr(value, "evidence_path", None)
        if path is not None and not isinstance(value, dict):
            data = {name: getattr(value, name, None) for name in cls.model_fields}
            data["has_evidence"] = bool(path)
            return data
        return value


class SubmissionAttemptDetail(SubmissionAttemptRead):
    answers_sent: dict[str, object] = Field(default_factory=dict)
    artifacts: dict[str, object] = Field(default_factory=dict)
    events: list[SubmissionEventRead] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _detail_fields(cls, value: object) -> object:
        if isinstance(value, dict):
            return value
        data = {name: getattr(value, name, None) for name in cls.model_fields}
        data["has_evidence"] = bool(getattr(value, "evidence_path", ""))
        data["events"] = list(getattr(value, "events", []) or [])
        data["answers_sent"] = dict(getattr(value, "answers_sent", {}) or {})
        data["artifacts"] = dict(getattr(value, "artifacts", {}) or {})
        return data


class ResolveAttemptIn(BaseModel):
    """The user's own finding about an attempt whose outcome JobOrbit could not read."""

    model_config = ConfigDict(extra="forbid")

    outcome: str
    #: Required for "submitted": what the user saw (a confirmation email, a reference).
    evidence: str = Field(default="", max_length=1000)

    @field_validator("outcome")
    @classmethod
    def _known_outcome(cls, value: str) -> str:
        if value not in ("submitted", "not_submitted"):
            raise ValueError("outcome must be 'submitted' or 'not_submitted'")
        return value


class FitRead(BaseModel):
    status: str
    detail: str = ""


class ScreeningAnswerRead(BaseModel):
    question: str
    question_key: str
    answer: str
    provenance: str
    sensitive: bool
    source: str


class JobPlanRead(BaseModel):
    job_id: int
    title: str
    employer: str
    sources: list[str]
    url: str
    posted_at: datetime | None = None
    discovered_at: datetime | None = None
    score: float | None = None
    band: str = ""
    evidence_coverage: float | None = None
    confidence: str = ""
    role_family: str = ""
    location_fit: FitRead
    experience_fit: FitRead
    platform: str
    platform_name: str
    submission_supported: bool
    capability_reason: str = ""
    resume_artifact: str = ""
    cover_letter_preview: str = ""
    application_id: int | None = None
    screening_answers: list[ScreeningAnswerRead] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    status: str
    queued: bool
    planned: bool


class PreflightCountsRead(BaseModel):
    total_discovered: int
    new_jobs: int
    duplicates: int
    previously_applied: int
    scored: int
    meeting_score: int
    meeting_confidence: int
    meeting_experience: int
    meeting_location: int
    expired_or_stale: int
    missing_answers: int
    blocked_by_eligibility: int
    blocked_by_constraints: int
    unsupported_platform: int
    ready: int
    queued: int
    planned_attempts: int
    daily_cap: int | None = None
    dispatched_today: int = 0
    daily_cap_remaining: int | None = None


class PreflightRead(BaseModel):
    counts: PreflightCountsRead
    jobs: list[JobPlanRead]
    queue_job_ids: list[int]
    notes: list[str] = Field(default_factory=list)
    generated_at: datetime
    emergency_stop: bool = False


class BreakerRead(BaseModel):
    target: str
    consecutive_failures: int
    open: bool
    opened_at: str | None = None
    reason: str = ""


class ControlStatusRead(BaseModel):
    emergency_stop: bool
    emergency_stop_reason: str = ""
    emergency_stop_at: str = ""
    breakers: list[BreakerRead] = Field(default_factory=list)
    daily_cap: int | None = None
    dispatched_today: int = 0
    browser_submission_enabled: bool = False
    evidence_retention_days: int = 30


class EmergencyStopIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=300)


class AutoApplyRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    dry_run: bool
    pause_requested: bool
    cancel_requested: bool
    max_submissions: int
    discovered_count: int
    eligible_count: int
    prepared_count: int
    confirmed_count: int
    blocked_count: int
    needs_user_count: int
    unsupported_count: int
    failed_count: int
    unknown_count: int
    started_at: datetime
    finished_at: datetime | None = None
    message: str = ""
    attempts: list[SubmissionAttemptRead] = Field(default_factory=list)

    @field_validator("status", mode="before")
    @classmethod
    def _status_value(cls, value: object) -> str:
        return str(getattr(value, "value", value or ""))


class PlatformSubmissionRead(BaseModel):
    """One row of the submission feasibility matrix, read from the adapter itself."""

    key: str
    display_name: str
    submission_supported: bool
    reason: str
    credential_owner: str
    documented_api: bool
    browser_submission_permitted: bool
    manual_completion_required: bool
    evidence_url: str = ""
    evidence_quote: str = ""


class SubmissionCapabilitiesRead(BaseModel):
    supported_targets: list[str]
    platforms: list[PlatformSubmissionRead]
    note: str
