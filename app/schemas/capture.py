"""DTOs for user-initiated job capture from the browser extension.

The extension reads one listing the user is looking at, after the user clicks its toolbar
button, and posts it here. Everything in the body came from a third-party web page and was
then editable by the user, so it is treated as untrusted text: lengths are bounded, unknown
keys are refused, and the URL must be a public http(s) address before it is stored or
rendered as a link.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.url_safety import inspect_url

#: Matches the extractor's own cap, so a description that reached the API untruncated is
#: never silently shortened here.
MAX_DESCRIPTION_CHARS = 20_000


def _checked_url(value: str, *, required: bool) -> str:
    candidate = (value or "").strip()
    if not candidate:
        if required:
            raise ValueError("a job url is required")
        return ""
    verdict = inspect_url(candidate)
    if not verdict.safe:
        raise ValueError(f"url rejected: {verdict.reason}")
    return candidate


class CaptureExtraction(BaseModel):
    """How the extension found the fields, kept as provenance."""

    model_config = ConfigDict(extra="forbid")

    method: str = Field(default="manual", max_length=50)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    missing: list[str] = Field(default_factory=list, max_length=20)
    field_sources: dict[str, str] = Field(default_factory=dict, max_length=20)

    @field_validator("missing")
    @classmethod
    def _short_names(cls, value: list[str]) -> list[str]:
        return [item.strip()[:40] for item in value if item and item.strip()]

    @field_validator("field_sources")
    @classmethod
    def _short_sources(cls, value: dict[str, str]) -> dict[str, str]:
        return {str(key)[:40]: str(item)[:50] for key, item in value.items()}


class CaptureRequest(BaseModel):
    """Body for ``POST /api/capture/job``."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=400)
    company: str = Field(min_length=1, max_length=300)
    location: str = Field(default="", max_length=300)
    url: str = Field(max_length=1200)
    description: str = Field(default="", max_length=MAX_DESCRIPTION_CHARS)
    posted_at: str = Field(default="", max_length=100)
    employment_type: str = Field(default="", max_length=100)
    source_hint: str = Field(default="", max_length=50)
    page_url: str = Field(default="", max_length=1200)
    extraction: CaptureExtraction = Field(default_factory=CaptureExtraction)
    extension_version: str = Field(default="", max_length=30)
    captured_at: datetime | None = None

    @field_validator("url")
    @classmethod
    def _job_url(cls, value: str) -> str:
        return _checked_url(value, required=True)

    @field_validator("page_url")
    @classmethod
    def _page_url(cls, value: str) -> str:
        # Provenance only, never rendered as a link: an address that fails the check (an
        # intranet or loopback page the user captured, then pointed ``url`` at the public
        # posting) is dropped rather than failing the whole capture.
        candidate = (value or "").strip()
        return candidate if candidate and inspect_url(candidate).safe else ""


class CaptureResult(BaseModel):
    """What the popup shows after a capture."""

    job_id: int
    created: bool
    duplicate_of: int | None = None
    source: str
    score: float | None = None
    band: str | None = None
    confidence: str | None = None
    filtered_out: bool = False
    filter_reasons: list[str] = Field(default_factory=list)
    explanation: list[str] = Field(default_factory=list)
    dashboard_path: str
    message: str = ""
    warnings: list[str] = Field(default_factory=list)


class CaptureStatus(BaseModel):
    """A cheap "JobOrbit is reachable" answer for the extension's popup and options page."""

    app: str = "JobOrbit"
    status: str = "ok"
    version: str
    token_required: bool
    demo_mode: bool
    capture_enabled: bool
