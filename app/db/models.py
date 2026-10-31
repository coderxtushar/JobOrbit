"""SQLAlchemy 2.x ORM models.

Conventions enforced across every table:

* All timestamps are stored in UTC via :class:`UtcDateTime`, which attaches ``tzinfo`` on
  read so SQLite and PostgreSQL behave identically.
* Imported data, generated content and user-verified data live in separate columns and are
  never merged in place. ``Job`` holds only what a source gave us; ``JobMatch`` holds only
  what we computed; ``ApplicationAnswer.provenance`` records who produced each answer.
* ``posted_at`` (from the source) and ``discovered_at`` (when we saw it) are distinct, and
  ``posted_at`` is nullable because many listings do not expose it.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Timezone-aware current time. The single source of 'now' in the app."""
    return datetime.now(UTC)


class UtcDateTime(TypeDecorator[datetime]):
    """A DateTime that is always stored and returned as UTC-aware.

    SQLite discards timezone information. Without this decorator a value written as
    ``2026-01-01T00:00+05:30`` reads back as naive and silently compares wrongly.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime rejected; pass a timezone-aware value")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    """Declarative base for every model."""

    type_annotation_map = {dict[str, Any]: JSON, list[str]: JSON, list[dict[str, Any]]: JSON}


# --------------------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------------------


class SourceName(str, enum.Enum):
    MANUAL = "manual"
    CSV = "csv"
    EMAIL_ALERT = "email_alert"
    LINKEDIN = "linkedin"
    INDEED = "indeed"
    NAUKRI = "naukri"
    WELLFOUND = "wellfound"
    INSTAHYRE = "instahyre"
    CUTSHORT = "cutshort"
    HIRIST = "hirist"
    # The ATS platforms below publish a documented public endpoint serving a company's
    # own job board, which is the basis for their discovery capability. Discovery is
    # per-company: nothing is fetched until the user names a board.
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    WORKABLE = "workable"
    ASHBY = "ashby"
    SMARTRECRUITERS = "smartrecruiters"
    # Open job feeds that publish a whole-feed API rather than a per-company board. Each
    # one's terms permit reading the feed; see ``app/sources/aggregators.py`` for the
    # notice each publisher returns in its own payload.
    ARBEITNOW = "arbeitnow"
    REMOTEOK = "remoteok"
    REMOTIVE = "remotive"
    HIMALAYAS = "himalayas"
    JOBICY = "jobicy"
    WORKDAY = "workday"
    COMPANY_SITE = "company_site"


class JobStatus(str, enum.Enum):
    """Lifecycle of a *job listing* (distinct from an application)."""

    DISCOVERED = "DISCOVERED"
    SCORED = "SCORED"
    SHORTLISTED = "SHORTLISTED"
    SKIPPED = "SKIPPED"
    FILTERED_OUT = "FILTERED_OUT"
    EXPIRED = "EXPIRED"
    DUPLICATE = "DUPLICATE"


class ApplicationStatus(str, enum.Enum):
    """Lifecycle of an *application*. Submission is always user-performed."""

    DISCOVERED = "DISCOVERED"
    SCORED = "SCORED"
    SHORTLISTED = "SHORTLISTED"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    SUBMISSION_UNKNOWN = "SUBMISSION_UNKNOWN"


class AnswerProvenance(str, enum.Enum):
    """Where an application answer came from. Never inferred after the fact."""

    PROFILE_VERIFIED = "profile_verified"
    RESUME_EXTRACTED = "resume_extracted"
    AI_DRAFT = "ai_draft"
    USER_ENTERED = "user_entered"
    NEEDS_USER_INPUT = "needs_user_input"


class WorkArrangement(str, enum.Enum):
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"
    UNKNOWN = "unknown"


class EmploymentType(str, enum.Enum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    INTERNSHIP = "internship"
    CONTRACT = "contract"
    TEMPORARY = "temporary"
    UNKNOWN = "unknown"


class ImportStatus(str, enum.Enum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED_UNSUPPORTED = "skipped_unsupported"


class BatchStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class BatchItemStatus(str, enum.Enum):
    """Per-job state inside a batch run. Each value is a durable checkpoint."""

    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    PREPARED = "prepared"
    NEEDS_ACTION = "needs_action"
    SKIPPED_DUPLICATE = "skipped_duplicate"
    SKIPPED_INELIGIBLE = "skipped_ineligible"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Outcome(str, enum.Enum):
    PENDING = "pending"
    NO_RESPONSE = "no_response"
    REJECTED = "rejected"
    SCREENING = "screening"
    INTERVIEWING = "interviewing"
    OFFER = "offer"
    WITHDRAWN = "withdrawn"
    ACCEPTED = "accepted"


def _enum_column(enum_cls: type[enum.Enum], **kwargs: Any) -> Any:
    """Store enums by *value* so the database rows stay human-readable."""
    return mapped_column(
        SAEnum(enum_cls, values_callable=lambda e: [member.value for member in e]),
        **kwargs,
    )


# --------------------------------------------------------------------------------------
# Candidate profile and resumes
# --------------------------------------------------------------------------------------


class CandidateProfile(Base):
    """The user's verified preferences and facts. Edited only by the user."""

    __tablename__ = "candidate_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(320), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    links: Mapped[list[str]] = mapped_column(default=list)

    headline: Mapped[str] = mapped_column(String(300), default="")
    experience_level: Mapped[str] = mapped_column(String(50), default="fresher")
    years_experience: Mapped[float] = mapped_column(Float, default=0.0)

    target_titles: Mapped[list[str]] = mapped_column(default=list)
    technical_skills: Mapped[list[str]] = mapped_column(default=list)
    soft_skills: Mapped[list[str]] = mapped_column(default=list)

    education: Mapped[list[dict[str, Any]]] = mapped_column(default=list)
    graduation_date: Mapped[str | None] = mapped_column(String(20), default=None)
    projects: Mapped[list[dict[str, Any]]] = mapped_column(default=list)
    certifications: Mapped[list[str]] = mapped_column(default=list)

    preferred_locations: Mapped[list[str]] = mapped_column(default=list)
    work_arrangements: Mapped[list[str]] = mapped_column(default=list)
    employment_types: Mapped[list[str]] = mapped_column(default=list)
    open_to_relocation: Mapped[bool | None] = mapped_column(Boolean, default=None)

    # Sensitive answers. ``None`` means "the user has not told us", never "assume no".
    salary_expectation_min: Mapped[int | None] = mapped_column(Integer, default=None)
    salary_expectation_max: Mapped[int | None] = mapped_column(Integer, default=None)
    salary_currency: Mapped[str] = mapped_column(String(10), default="INR")
    notice_period_days: Mapped[int | None] = mapped_column(Integer, default=None)
    work_authorization: Mapped[str | None] = mapped_column(String(200), default=None)
    requires_sponsorship: Mapped[bool | None] = mapped_column(Boolean, default=None)

    excluded_companies: Mapped[list[str]] = mapped_column(default=list)
    excluded_keywords: Mapped[list[str]] = mapped_column(default=list)
    minimum_match_score: Mapped[float] = mapped_column(Float, default=65.0)
    max_job_age_days: Mapped[int] = mapped_column(Integer, default=30)
    scoring_weights: Mapped[dict[str, Any]] = mapped_column(default=dict)
    extra_answers: Mapped[dict[str, Any]] = mapped_column(default=dict)

    # Hard constraints: a listing failing one of these is filtered out with a reason.
    # Separated from the soft preferences above because the two must not be confused —
    # "Bengaluru preferred" should reorder the feed, while "I can only work from India"
    # should remove listings from it. Both default to off so an existing profile keeps
    # its current feed until the user asks for the constraint.
    requires_india_work_eligibility: Mapped[bool] = mapped_column(Boolean, default=False)
    max_required_experience_years: Mapped[float | None] = mapped_column(Float, default=None)

    # Soft preferences: these move a listing up or down, never out.
    preferred_companies: Mapped[list[str]] = mapped_column(default=list)
    preferred_industries: Mapped[list[str]] = mapped_column(default=list)
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)

    resumes: Mapped[list[Resume]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "minimum_match_score >= 0 AND minimum_match_score <= 100", name="ck_profile_min_score"
        ),
        CheckConstraint("max_job_age_days > 0", name="ck_profile_max_age"),
    )


class Resume(Base):
    """An uploaded resume file plus the data extracted from it."""

    __tablename__ = "resume"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_profile.id", ondelete="CASCADE"), index=True
    )

    label: Mapped[str] = mapped_column(String(200), default="base")
    original_filename: Mapped[str] = mapped_column(String(300))
    stored_path: Mapped[str] = mapped_column(String(600))
    content_type: Mapped[str] = mapped_column(String(100))
    file_size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)

    # Extracted (machine-produced) data, kept separate from the profile the user verified.
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    extracted_fields: Mapped[dict[str, Any]] = mapped_column(default=dict)
    parse_warnings: Mapped[list[str]] = mapped_column(default=list)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    profile: Mapped[CandidateProfile] = relationship(back_populates="resumes")
    variants: Mapped[list[ResumeVariant]] = relationship(
        back_populates="resume", cascade="all, delete-orphan"
    )


class ResumeVariant(Base):
    """A role-family-specific view of a resume.

    A variant only ever *selects and reorders* facts already present in the source resume.
    ``content`` is the rendered text; ``included_items`` records exactly which source facts
    were used so the variant can be audited against the original.
    """

    __tablename__ = "resume_variant"

    id: Mapped[int] = mapped_column(primary_key=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resume.id", ondelete="CASCADE"), index=True)

    name: Mapped[str] = mapped_column(String(200))
    job_family: Mapped[str] = mapped_column(String(100), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    emphasised_skills: Mapped[list[str]] = mapped_column(default=list)
    included_items: Mapped[dict[str, Any]] = mapped_column(default=dict)
    content: Mapped[str] = mapped_column(Text, default="")
    generated_by: Mapped[str] = mapped_column(String(50), default="rule_based")
    stored_path: Mapped[str | None] = mapped_column(String(600), default=None)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    resume: Mapped[Resume] = relationship(back_populates="variants")

    __table_args__ = (
        UniqueConstraint("resume_id", "job_family", "version", name="uq_variant_family_version"),
    )


# --------------------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------------------


class Job(Base):
    """A normalized job listing. Holds source-provided data only."""

    __tablename__ = "job"

    id: Mapped[int] = mapped_column(primary_key=True)

    title: Mapped[str] = mapped_column(String(400))
    company: Mapped[str] = mapped_column(String(300), index=True)
    company_normalized: Mapped[str] = mapped_column(String(300), index=True)
    location: Mapped[str] = mapped_column(String(300), default="")
    location_normalized: Mapped[str] = mapped_column(String(300), default="")
    work_arrangement: Mapped[WorkArrangement] = _enum_column(
        WorkArrangement, default=WorkArrangement.UNKNOWN
    )
    employment_type: Mapped[EmploymentType] = _enum_column(
        EmploymentType, default=EmploymentType.UNKNOWN
    )

    salary_min: Mapped[int | None] = mapped_column(Integer, default=None)
    salary_max: Mapped[int | None] = mapped_column(Integer, default=None)
    salary_currency: Mapped[str | None] = mapped_column(String(10), default=None)
    salary_raw: Mapped[str] = mapped_column(String(200), default="")

    experience_min_years: Mapped[float | None] = mapped_column(Float, default=None)
    experience_max_years: Mapped[float | None] = mapped_column(Float, default=None)
    experience_raw: Mapped[str] = mapped_column(String(200), default="")

    required_skills: Mapped[list[str]] = mapped_column(default=list)
    preferred_skills: Mapped[list[str]] = mapped_column(default=list)
    education_requirements: Mapped[list[str]] = mapped_column(default=list)

    description: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(1200), default="")
    canonical_url: Mapped[str] = mapped_column(String(1200), default="", index=True)
    application_method: Mapped[str] = mapped_column(String(100), default="external_site")

    # posted_at is what the source said. discovered_at is when we first stored it.
    # They are never substituted for one another.
    posted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None, index=True)
    posted_at_is_approximate: Mapped[bool] = mapped_column(Boolean, default=False)
    discovered_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)

    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[JobStatus] = _enum_column(JobStatus, default=JobStatus.DISCOVERED, index=True)
    duplicate_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None, index=True
    )
    raw_payload: Mapped[dict[str, Any]] = mapped_column(default=dict)

    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)

    source_references: Mapped[list[JobSourceReference]] = relationship(
        back_populates="job", cascade="all, delete-orphan", lazy="selectin"
    )
    matches: Mapped[list[JobMatch]] = relationship(
        back_populates="job", cascade="all, delete-orphan", lazy="selectin"
    )
    applications: Mapped[list[Application]] = relationship(back_populates="job")

    __table_args__ = (
        Index("ix_job_status_discovered", "status", "discovered_at"),
        Index("ix_job_company_title", "company_normalized", "title"),
    )


class JobSourceReference(Base):
    """One row per platform a job was seen on.

    Cross-platform duplicates collapse into a single ``Job`` with several references, so the
    user can still see every platform where the posting appeared.
    """

    __tablename__ = "job_source_reference"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), index=True)

    source: Mapped[SourceName] = _enum_column(SourceName, index=True)
    external_id: Mapped[str | None] = mapped_column(String(300), default=None)
    url: Mapped[str] = mapped_column(String(1200), default="")
    retrieved_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    retrieval_method: Mapped[str] = mapped_column(String(100), default="manual_import")
    import_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_run.id", ondelete="SET NULL"), default=None
    )
    source_metadata: Mapped[dict[str, Any]] = mapped_column(default=dict)

    job: Mapped[Job] = relationship(back_populates="source_references")

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_source_external_id"),
        Index("ix_source_ref_job_source", "job_id", "source"),
    )


class JobMatch(Base):
    """Computed score for a (job, profile) pair. Never mixed into ``Job``."""

    __tablename__ = "job_match"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_profile.id", ondelete="CASCADE"), index=True
    )

    total_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    band: Mapped[str] = mapped_column(String(20), default="low")
    #: How much of the configured weighting could actually be judged, and the resulting
    #: confidence label. Stored alongside the score rather than folded into it, because a
    #: listing can look like a strong match and still be impossible to judge.
    evidence_coverage: Mapped[float] = mapped_column(Float, default=1.0)
    confidence: Mapped[str] = mapped_column(String(20), default="high")
    confidence_reasons: Mapped[list[str]] = mapped_column(default=list)
    category_scores: Mapped[dict[str, Any]] = mapped_column(default=dict)
    weights_used: Mapped[dict[str, Any]] = mapped_column(default=dict)

    matched_skills: Mapped[list[str]] = mapped_column(default=list)
    missing_required_skills: Mapped[list[str]] = mapped_column(default=list)
    missing_preferred_skills: Mapped[list[str]] = mapped_column(default=list)
    uncertain_requirements: Mapped[list[str]] = mapped_column(default=list)
    explanation: Mapped[list[str]] = mapped_column(default=list)

    filtered_out: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    filter_reasons: Mapped[list[str]] = mapped_column(default=list)
    scorer: Mapped[str] = mapped_column(String(50), default="rule_based")

    scored_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    job: Mapped[Job] = relationship(back_populates="matches")

    __table_args__ = (
        UniqueConstraint("job_id", "profile_id", name="uq_match_job_profile"),
        CheckConstraint("total_score >= 0 AND total_score <= 100", name="ck_match_score_range"),
        Index("ix_match_profile_score", "profile_id", "total_score"),
    )


# --------------------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------------------


class Application(Base):
    """One application attempt for one job.

    A unique constraint on ``(job_id, profile_id)`` is the structural guarantee against
    applying twice to the same posting.
    """

    __tablename__ = "application"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_profile.id", ondelete="CASCADE"), index=True
    )

    platform: Mapped[SourceName] = _enum_column(SourceName)
    status: Mapped[ApplicationStatus] = _enum_column(
        ApplicationStatus, default=ApplicationStatus.SHORTLISTED, index=True
    )

    resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resume.id", ondelete="SET NULL"), default=None
    )
    resume_variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("resume_variant.id", ondelete="SET NULL"), default=None
    )
    resume_version_label: Mapped[str] = mapped_column(String(200), default="")
    cover_letter: Mapped[str] = mapped_column(Text, default="")
    cover_letter_version: Mapped[int] = mapped_column(Integer, default=0)
    cover_letter_generated_by: Mapped[str] = mapped_column(String(50), default="")

    prepared_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    reviewed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    user_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    submitted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    submitted_by: Mapped[str] = mapped_column(String(50), default="")
    confirmation_evidence: Mapped[str | None] = mapped_column(Text, default=None)
    confirmed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)

    notes: Mapped[str] = mapped_column(Text, default="")
    follow_up_date: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None, index=True)
    outcome: Mapped[Outcome] = _enum_column(Outcome, default=Outcome.PENDING, index=True)
    interview_status: Mapped[str] = mapped_column(String(100), default="")

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)

    job: Mapped[Job] = relationship(back_populates="applications")
    answers: Mapped[list[ApplicationAnswer]] = relationship(
        back_populates="application", cascade="all, delete-orphan", lazy="selectin"
    )
    events: Mapped[list[ApplicationEvent]] = relationship(
        back_populates="application", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("job_id", "profile_id", name="uq_application_job_profile"),
        Index("ix_application_status_created", "status", "created_at"),
    )


class ApplicationAnswer(Base):
    """A single question/answer pair with explicit provenance."""

    __tablename__ = "application_answer"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), index=True
    )

    question: Mapped[str] = mapped_column(Text)
    question_key: Mapped[str] = mapped_column(String(100), default="", index=True)
    answer: Mapped[str] = mapped_column(Text, default="")
    provenance: Mapped[AnswerProvenance] = _enum_column(
        AnswerProvenance, default=AnswerProvenance.NEEDS_USER_INPUT
    )
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_user_input: Mapped[bool] = mapped_column(Boolean, default=False)
    flag_reason: Mapped[str] = mapped_column(String(300), default="")
    source_field: Mapped[str] = mapped_column(String(100), default="")

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)

    application: Mapped[Application] = relationship(back_populates="answers")


class ApplicationEvent(Base):
    """Append-only audit of every application state change."""

    __tablename__ = "application_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), index=True
    )

    from_status: Mapped[ApplicationStatus | None] = _enum_column(
        ApplicationStatus, default=None, nullable=True
    )
    to_status: Mapped[ApplicationStatus] = _enum_column(ApplicationStatus)
    actor: Mapped[str] = mapped_column(String(50), default="user")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)

    application: Mapped[Application] = relationship(back_populates="events")


# --------------------------------------------------------------------------------------
# Source configuration, imports, audit
# --------------------------------------------------------------------------------------


class SourceConfiguration(Base):
    """Per-source user settings.

    Capability flags are *not* stored here as user-editable booleans by accident: the
    adapter's declared capabilities are the ceiling, and these columns can only narrow them.
    """

    __tablename__ = "source_configuration"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[SourceName] = _enum_column(SourceName, unique=True)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    manual_import_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    authorized_discovery_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    browser_assistance_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    automated_submission_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    rate_limit_per_hour: Mapped[int] = mapped_column(Integer, default=30)
    last_run_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    last_error: Mapped[str] = mapped_column(Text, default="")
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict)

    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        # Structural guarantee: the database itself refuses to record an enabled
        # automated-submission capability. Portable across SQLite and PostgreSQL.
        CheckConstraint("NOT automated_submission_enabled", name="ck_no_automated_submission"),
        CheckConstraint("rate_limit_per_hour > 0", name="ck_rate_limit_positive"),
    )


class ImportRun(Base):
    """One discovery or import attempt, successful or not."""

    __tablename__ = "import_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[SourceName] = _enum_column(SourceName, index=True)
    trigger: Mapped[str] = mapped_column(String(50), default="manual")
    status: Mapped[ImportStatus] = _enum_column(
        ImportStatus, default=ImportStatus.RUNNING, index=True
    )

    started_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)

    records_received: Mapped[int] = mapped_column(Integer, default=0)
    records_invalid: Mapped[int] = mapped_column(Integer, default=0)
    jobs_created: Mapped[int] = mapped_column(Integer, default=0)
    jobs_updated: Mapped[int] = mapped_column(Integer, default=0)
    duplicates_detected: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=1)

    message: Mapped[str] = mapped_column(Text, default="")
    errors: Mapped[list[str]] = mapped_column(default=list)
    run_metadata: Mapped[dict[str, Any]] = mapped_column(default=dict)


class SavedAnswer(Base):
    """A screening answer the user verified once and may reuse on every application.

    The bank only ever stores answers whose provenance is ``user_entered`` or
    ``profile_verified``. An ``ai_draft`` is never banked, because reuse would turn one
    unreviewed draft into a claim repeated across a hundred employers.
    """

    __tablename__ = "saved_answer"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_profile.id", ondelete="CASCADE"), index=True
    )

    question_key: Mapped[str] = mapped_column(String(100), index=True)
    question: Mapped[str] = mapped_column(Text, default="")
    answer: Mapped[str] = mapped_column(Text, default="")
    provenance: Mapped[AnswerProvenance] = _enum_column(
        AnswerProvenance, default=AnswerProvenance.USER_ENTERED
    )
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)

    times_used: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("profile_id", "question_key", name="uq_saved_answer_profile_key"),
        CheckConstraint(
            "provenance IN ('user_entered', 'profile_verified')",
            name="ck_saved_answer_verified_provenance",
        ),
    )


class ApplicationArtifact(Base):
    """An immutable snapshot of material prepared for one application.

    Stored verbatim with a content hash so the exact resume text and letter that went to a
    given employer can be reproduced later, even after the variant is regenerated.
    """

    __tablename__ = "application_artifact"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), index=True
    )

    kind: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(200), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    content_sha256: Mapped[str] = mapped_column(String(64), default="", index=True)
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)

    __table_args__ = (
        UniqueConstraint(
            "application_id", "kind", "content_sha256", name="uq_artifact_app_kind_hash"
        ),
    )


class BatchRun(Base):
    """One bulk preparation run over many jobs.

    The row is the run's checkpoint: ``status`` and the per-item rows survive a crash, so an
    interrupted run is resumable rather than restarted. Nothing here submits an application.
    """

    __tablename__ = "batch_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_profile.id", ondelete="CASCADE"), index=True
    )

    status: Mapped[BatchStatus] = _enum_column(BatchStatus, default=BatchStatus.PENDING, index=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)

    concurrency: Mapped[int] = mapped_column(Integer, default=4)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    selection: Mapped[dict[str, Any]] = mapped_column(default=dict)

    total_items: Mapped[int] = mapped_column(Integer, default=0)
    prepared_count: Mapped[int] = mapped_column(Integer, default=0)
    needs_action_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)

    started_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    message: Mapped[str] = mapped_column(Text, default="")

    items: Mapped[list[BatchRunItem]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint("concurrency BETWEEN 1 AND 16", name="ck_batch_concurrency_range"),
        CheckConstraint("max_attempts BETWEEN 1 AND 10", name="ck_batch_attempts_range"),
    )


class BatchRunItem(Base):
    """One job inside a batch run, with its own attempt count and terminal reason.

    The unique constraint on ``(batch_run_id, job_id)`` is what makes a resumed run
    idempotent: re-queuing a job already recorded in the run is impossible.
    """

    __tablename__ = "batch_run_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_run_id: Mapped[int] = mapped_column(
        ForeignKey("batch_run.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("application.id", ondelete="SET NULL"), default=None
    )

    status: Mapped[BatchItemStatus] = _enum_column(
        BatchItemStatus, default=BatchItemStatus.QUEUED, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    blocking_questions: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)

    run: Mapped[BatchRun] = relationship(back_populates="items")

    __table_args__ = (
        UniqueConstraint("batch_run_id", "job_id", name="uq_batch_item_run_job"),
        Index("ix_batch_item_run_status", "batch_run_id", "status"),
    )


class AuditLog(Base):
    """Append-only record of user- and system-initiated actions."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(50), default="")
    entity_id: Mapped[int | None] = mapped_column(Integer, default=None)
    actor: Mapped[str] = mapped_column(String(50), default="user")
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)

    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"),)


class SavedSearch(Base):
    """A named set of feed criteria, plus the watermark for "new since last run".

    ``last_run_at`` is what makes the digest honest: new matches are the ones discovered
    after the user last looked at this search, not the ones discovered today. A job
    imported today may have been posted weeks ago, and the reverse is also true, so the
    watermark is compared against ``discovered_at`` rather than ``posted_at``.
    """

    __tablename__ = "saved_search"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_profile.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    criteria: Mapped[dict[str, Any]] = mapped_column(default=dict)
    last_run_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("profile_id", "name", name="uq_saved_search_profile_name"),)
