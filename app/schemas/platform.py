"""Platform assistant response models.

Every field is either copied from :mod:`app.services.platforms` or counted from the
database. Nothing is defaulted to a flattering value: a platform with no stored jobs
reports zero, and a capability the adapter has not documented reports ``false``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.schemas.source import Capabilities


class PlatformActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    description: str
    available: bool


class PlatformSourceRead(BaseModel):
    """One adapter inside a platform section, with its own capabilities and status."""

    source: str
    display_name: str
    enabled: bool
    capabilities: Capabilities
    effective_capabilities: Capabilities
    policy_basis: str
    limitations: list[str]
    last_run_at: str | None = None
    last_error: str = ""
    jobs_stored: int = 0


class PlatformSummary(BaseModel):
    key: str
    display_name: str
    tagline: str
    homepage: str
    how_jobs_arrive: str
    notes: list[str]
    source_count: int
    discovery_source_count: int
    jobs_stored: int
    applications: int
    supports_automated_discovery: bool
    supports_automated_submission: bool = False


class PlatformDetail(PlatformSummary):
    search_url_template: str
    actions: list[PlatformActionRead]
    sources: list[PlatformSourceRead]
    jobs_by_status: dict[str, int]
    applications_by_status: dict[str, int]
