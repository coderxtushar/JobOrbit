"""Email response tracking: request and response models.

Responses carry what is stored and nothing more. There is no field for a message body
because none is kept, and no field for a token because none is in the database.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EmailAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    address: str
    scopes: list[str]
    status: str
    connected_at: datetime
    last_sync_at: datetime | None
    last_error: str


class EmailTrackingStatus(BaseModel):
    enabled: bool
    oauth_configured: bool
    connected: bool
    redirect_uri: str
    scope: str
    sync_days: int
    max_messages: int
    secret_backend: str
    accounts: list[EmailAccountRead] = Field(default_factory=list)
    needs_review: int = 0
    pending_suggestions: int = 0


class GmailConnectResponse(BaseModel):
    auth_url: str
    redirect_uri: str
    scope: str


class EmailMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int | None
    provider_message_id: str
    thread_id: str
    received_at: datetime | None
    sender: str
    sender_domain: str
    recipient: str
    subject: str
    snippet: str
    category: str
    confidence: float
    extracted: dict[str, Any]
    application_id: int | None
    match_confidence: float
    match_state: str
    match_candidates: list[dict[str, Any]]
    created_at: datetime


class StatusSuggestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    email_message_id: int | None
    attempt_id: int | None
    field: str
    suggested_value: str
    reason: str
    confidence: float
    state: str
    created_at: datetime
    resolved_at: datetime | None
    job_title: str = ""
    job_company: str = ""
    current_status: str = ""
    current_outcome: str = ""


class EmailIngestRequest(BaseModel):
    """A raw RFC 822 message, as saved by "Download message" / "Show original"."""

    raw: str = Field(min_length=1, max_length=5 * 1024 * 1024)


class EmailIngestResponse(BaseModel):
    outcome: str
    category: str
    confidence: float
    reasons: list[str]
    message: EmailMessageRead | None = None
    suggestion: StatusSuggestionRead | None = None


class EmailLinkRequest(BaseModel):
    application_id: int = Field(ge=1)


class EmailLinkResponse(BaseModel):
    message: EmailMessageRead
    suggestion: StatusSuggestionRead | None = None


class SuggestionDecision(BaseModel):
    suggestion: StatusSuggestionRead
    message: str
    changes: list[str] = Field(default_factory=list)


class EmailSyncResponse(BaseModel):
    account_id: int
    listed: int
    fetched: int
    kept: int
    duplicates: int
    skipped_not_job_related: int
    suggestions: int
    needs_review: int
    errors: list[str]


class EmailDisconnectResponse(BaseModel):
    disconnected: int
    revoked: int


class EmailDeleteResponse(BaseModel):
    messages: int
    suggestions: int
    accounts: int
