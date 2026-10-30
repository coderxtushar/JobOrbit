"""Source capability, configuration and diagnostics DTOs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import SourceName


class Capabilities(BaseModel):
    """What a source is permitted to do.

    ``automated_submission_enabled`` is typed as a literal ``False``: the field exists so
    the API surface is explicit about the answer, and a validator rejects ``True`` so the
    flag cannot be flipped by configuration or by a future code change.
    """

    manual_import_enabled: bool = True
    authorized_discovery_enabled: bool = False
    browser_assistance_enabled: bool = False
    automated_submission_enabled: bool = False

    @model_validator(mode="after")
    def _submission_stays_disabled(self) -> Capabilities:
        if self.automated_submission_enabled:
            raise ValueError(
                "automated_submission_enabled cannot be true: automated application "
                "submission is prohibited by the platforms in scope and is not implemented"
            )
        return self


class SourceRead(BaseModel):
    source: SourceName
    display_name: str
    enabled: bool
    capabilities: Capabilities
    effective_capabilities: Capabilities
    rate_limit_per_hour: int
    last_run_at: datetime | None = None
    last_error: str = ""
    consecutive_failures: int = 0
    policy_basis: str
    limitations: list[str] = Field(default_factory=list)
    status_detail: str = ""


class SourceUpdate(BaseModel):
    """User-editable source settings.

    A user may only *narrow* what an adapter declares. Requesting a capability the adapter
    does not have is rejected rather than silently ignored.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    manual_import_enabled: bool | None = None
    authorized_discovery_enabled: bool | None = None
    browser_assistance_enabled: bool | None = None
    rate_limit_per_hour: int | None = Field(default=None, ge=1, le=1000)


class DiagnosticEntry(BaseModel):
    source: SourceName
    display_name: str
    healthy: bool
    reason: str
    detail: str = ""
    last_run_at: datetime | None = None
    jobs_last_run: int | None = None


class Diagnostics(BaseModel):
    entries: list[DiagnosticEntry]
    llm_provider: str
    llm_enabled: bool
    scheduler_enabled: bool
    database_dialect: str
    api_bound_to_loopback: bool
    display_timezone: str


class OperationalMetrics(BaseModel):
    """Counted facts. Every value here comes from a database row."""

    jobs_total: int
    jobs_by_status: dict[str, int]
    jobs_imported: int
    records_invalid: int
    duplicates_detected: int
    jobs_filtered_out: int
    match_bands: dict[str, int]
    review_queue_size: int
    applications_by_status: dict[str, int]
    applications_by_outcome: dict[str, int]
    applications_prepared: int
    applications_submitted: int
    applications_confirmed: int
    import_failures: int
    audit_entries: int


class EstimatedMetrics(BaseModel):
    """Derived estimates, clearly separated from counted facts."""

    estimated_minutes_saved: int
    basis: str
