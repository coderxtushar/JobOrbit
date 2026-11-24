"""Opt-in, read-only email response tracking.

Every route refuses in demo mode: a shared deployment has no per-user login, so a mailbox
connected there would be readable by every visitor.

Every route requires the API bearer token except the OAuth callback. The callback is
opened by Google's redirect in the user's browser, which cannot carry the token; it is
authenticated instead by the one-time ``state`` value issued by ``/gmail/connect``, which
also binds the PKCE verifier, so a forged callback has nothing to exchange.
"""

from __future__ import annotations

import html
from typing import Annotated

from fastapi import APIRouter, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select

from app.api.deps import AppSettings, Authorized, DbSession, refuse_in_demo_mode
from app.api.errors import ApiError
from app.db.models import Application, EmailAccount, Job, StatusSuggestion
from app.schemas.common import Page
from app.schemas.email import (
    EmailAccountRead,
    EmailDeleteResponse,
    EmailDisconnectResponse,
    EmailIngestRequest,
    EmailIngestResponse,
    EmailLinkRequest,
    EmailLinkResponse,
    EmailMessageRead,
    EmailSyncResponse,
    EmailTrackingStatus,
    GmailConnectResponse,
    StatusSuggestionRead,
    SuggestionDecision,
)
from app.services.email_tracking.gmail import (
    GMAIL_READONLY_SCOPE,
    GmailClient,
    GmailError,
    GmailNotConfigured,
    redirect_uri,
)
from app.services.email_tracking.service import (
    PENDING,
    EmailTrackingError,
    EmailTrackingService,
    SuggestionNotApplicable,
)
from app.services.redaction import redact
from app.services.secrets import SecretStore, SecretStoreError

OPERATION = "email_tracking"

# No router-level auth dependency: the OAuth callback must be reachable from a browser
# redirect. Every other route declares ``dependencies=[Authorized]`` itself.
router = APIRouter(prefix="/api/email", tags=["email"])


def _gmail(settings) -> GmailClient:
    return GmailClient(settings)


def _suggestion_read(session, suggestion: StatusSuggestion) -> StatusSuggestionRead:
    model = StatusSuggestionRead.model_validate(suggestion)
    application = session.get(Application, suggestion.application_id)
    if application is not None:
        job = session.get(Job, application.job_id)
        model = model.model_copy(
            update={
                "job_title": job.title if job else "",
                "job_company": job.company if job else "",
                "current_status": application.status.value,
                "current_outcome": application.outcome.value,
            }
        )
    return model


def _connected_accounts(session) -> list[EmailAccount]:
    return list(
        session.scalars(
            select(EmailAccount)
            .where(EmailAccount.status != "disconnected")
            .order_by(EmailAccount.id)
        )
    )


def _not_found(error: EmailTrackingError) -> ApiError:
    code = "not_found" if "not found" in str(error) else "invalid_state"
    http_status = status.HTTP_404_NOT_FOUND if code == "not_found" else status.HTTP_409_CONFLICT
    return ApiError(code, str(error), http_status)


@router.get(
    "/status",
    response_model=EmailTrackingStatus,
    dependencies=[Authorized],
    summary="Whether email tracking is enabled and a mailbox is connected",
)
def email_tracking_status(session: DbSession, settings: AppSettings) -> EmailTrackingStatus:
    refuse_in_demo_mode(settings, OPERATION)
    accounts = list(session.scalars(select(EmailAccount).order_by(EmailAccount.id)))
    service = EmailTrackingService(session)
    pending = session.scalar(
        select(func.count()).where(
            StatusSuggestion.state == PENDING, StatusSuggestion.email_message_id.is_not(None)
        )
    )
    backend: str
    try:
        backend = SecretStore(settings).backend
    except SecretStoreError:
        backend = "unavailable"
    return EmailTrackingStatus(
        enabled=settings.email_tracking_enabled,
        oauth_configured=bool(settings.gmail_client_id.strip()),
        connected=any(account.status == "connected" for account in accounts),
        redirect_uri=redirect_uri(settings),
        scope=GMAIL_READONLY_SCOPE,
        sync_days=settings.email_sync_days,
        max_messages=settings.email_max_messages,
        secret_backend=backend,
        accounts=[EmailAccountRead.model_validate(account) for account in accounts],
        needs_review=service.review_count(),
        pending_suggestions=int(pending or 0),
    )


@router.get(
    "/gmail/connect",
    response_model=GmailConnectResponse,
    dependencies=[Authorized],
    summary="Begin read-only Gmail OAuth: returns the Google sign-in URL to open",
)
def gmail_connect_url(settings: AppSettings) -> GmailConnectResponse:
    refuse_in_demo_mode(settings, OPERATION)
    try:
        url = _gmail(settings).authorization_url()
    except GmailNotConfigured as error:
        raise ApiError(
            "email_tracking_not_configured", str(error), status.HTTP_409_CONFLICT
        ) from error
    return GmailConnectResponse(
        auth_url=url, redirect_uri=redirect_uri(settings), scope=GMAIL_READONLY_SCOPE
    )


def _callback_page(title: str, body: str, http_status: int = 200) -> HTMLResponse:
    page = (
        "<!doctype html><html><head><meta charset='utf-8'><title>JobOrbit</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:36rem;margin:4rem auto;"
        "padding:0 1rem;line-height:1.5}</style></head><body>"
        f"<h1>{html.escape(title)}</h1><p>{html.escape(body)}</p></body></html>"
    )
    return HTMLResponse(page, status_code=http_status)


@router.get(
    "/gmail/callback",
    response_class=HTMLResponse,
    include_in_schema=False,
    summary="OAuth redirect target; exchanges the code after validating state",
)
def gmail_oauth_callback(
    session: DbSession,
    settings: AppSettings,
    code: str = "",
    state: str = "",
    error: str = "",
) -> HTMLResponse:
    refuse_in_demo_mode(settings, OPERATION)
    if error:
        return _callback_page(
            "Gmail was not connected",
            f"Google reported: {redact(error)[:200]}. You can close this tab.",
            status.HTTP_400_BAD_REQUEST,
        )
    try:
        account = _gmail(settings).complete_authorization(session, code, state)
    except (GmailError, SecretStoreError) as failure:
        return _callback_page(
            "Gmail was not connected", redact(str(failure)), status.HTTP_400_BAD_REQUEST
        )
    return _callback_page(
        "Gmail connected, read-only",
        f"JobOrbit can now read job-related mail in {account.address or 'your mailbox'}. "
        "It cannot send, delete or change anything. You can close this tab.",
    )


@router.post(
    "/sync",
    response_model=list[EmailSyncResponse],
    dependencies=[Authorized],
    summary="Read recent job-related Gmail messages and propose status changes",
)
def sync_email(session: DbSession, settings: AppSettings) -> list[EmailSyncResponse]:
    refuse_in_demo_mode(settings, OPERATION)
    accounts = [account for account in _connected_accounts(session) if account.provider == "gmail"]
    if not accounts:
        raise ApiError(
            "email_not_connected", "No Gmail account is connected.", status.HTTP_409_CONFLICT
        )
    client = _gmail(settings)
    reports: list[EmailSyncResponse] = []
    for account in accounts:
        try:
            report = client.sync(session, account)
        except GmailNotConfigured as failure:
            raise ApiError(
                "email_tracking_not_configured", str(failure), status.HTTP_409_CONFLICT
            ) from failure
        except (GmailError, SecretStoreError) as failure:
            # Committed, not rolled back: the account's reauth_required status is the
            # useful outcome of a failed sync.
            session.commit()
            raise ApiError(
                "email_sync_failed", redact(str(failure)), status.HTTP_502_BAD_GATEWAY
            ) from failure
        reports.append(EmailSyncResponse(account_id=account.id, **report.to_dict()))
    return reports


@router.post(
    "/ingest",
    response_model=EmailIngestResponse,
    dependencies=[Authorized],
    summary="Process one pasted .eml message, for use without Gmail OAuth",
)
def ingest_email(
    payload: EmailIngestRequest, session: DbSession, settings: AppSettings
) -> EmailIngestResponse:
    refuse_in_demo_mode(settings, OPERATION)
    service = EmailTrackingService(session)
    try:
        result = service.ingest_raw(payload.raw)
    except EmailTrackingError as failure:
        raise ApiError(
            "invalid_email", str(failure), status.HTTP_422_UNPROCESSABLE_ENTITY
        ) from failure
    classification = result.classification
    return EmailIngestResponse(
        outcome=result.outcome,
        category=classification.category,
        confidence=classification.confidence,
        reasons=classification.reasons[:12],
        message=EmailMessageRead.model_validate(result.message) if result.message else None,
        suggestion=_suggestion_read(session, result.suggestion) if result.suggestion else None,
    )


@router.get(
    "/messages",
    response_model=Page[EmailMessageRead],
    dependencies=[Authorized],
    summary="Stored job-related emails, filterable by match state and category",
)
def list_email_messages(
    session: DbSession,
    settings: AppSettings,
    match_state: str | None = None,
    category: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[EmailMessageRead]:
    refuse_in_demo_mode(settings, OPERATION)
    rows, total = EmailTrackingService(session).list_messages(
        match_state=match_state, category=category, limit=limit, offset=offset
    )
    return Page[EmailMessageRead](
        items=[EmailMessageRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/suggestions",
    response_model=list[StatusSuggestionRead],
    dependencies=[Authorized],
    summary="Suggested status or outcome changes from email, pending by default",
)
def list_status_suggestions(
    session: DbSession,
    settings: AppSettings,
    state: str = PENDING,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[StatusSuggestionRead]:
    refuse_in_demo_mode(settings, OPERATION)
    service = EmailTrackingService(session)
    rows = service.list_suggestions(state=None if state == "all" else state, limit=limit)
    return [_suggestion_read(session, row) for row in rows]


@router.post(
    "/suggestions/{suggestion_id}/accept",
    response_model=SuggestionDecision,
    dependencies=[Authorized],
    summary="Apply a suggestion through the legal status transitions",
)
def accept_status_suggestion(
    suggestion_id: int, session: DbSession, settings: AppSettings
) -> SuggestionDecision:
    refuse_in_demo_mode(settings, OPERATION)
    try:
        result = EmailTrackingService(session).accept_suggestion(suggestion_id)
    except SuggestionNotApplicable as failure:
        raise ApiError(
            "suggestion_not_applicable", str(failure), status.HTTP_409_CONFLICT
        ) from failure
    except EmailTrackingError as failure:
        raise _not_found(failure) from failure
    return SuggestionDecision(
        suggestion=_suggestion_read(session, result.suggestion),
        message=result.message,
        changes=result.changes,
    )


@router.post(
    "/suggestions/{suggestion_id}/dismiss",
    response_model=SuggestionDecision,
    dependencies=[Authorized],
    summary="Dismiss a suggestion without changing the application",
)
def dismiss_status_suggestion(
    suggestion_id: int, session: DbSession, settings: AppSettings
) -> SuggestionDecision:
    refuse_in_demo_mode(settings, OPERATION)
    try:
        suggestion = EmailTrackingService(session).dismiss_suggestion(suggestion_id)
    except EmailTrackingError as failure:
        raise _not_found(failure) from failure
    return SuggestionDecision(suggestion=_suggestion_read(session, suggestion), message="dismissed")


@router.post(
    "/messages/{message_id}/link",
    response_model=EmailLinkResponse,
    dependencies=[Authorized],
    summary="Link an email to the application you picked from the review inbox",
)
def link_email_message(
    message_id: int, payload: EmailLinkRequest, session: DbSession, settings: AppSettings
) -> EmailLinkResponse:
    refuse_in_demo_mode(settings, OPERATION)
    try:
        message, suggestion = EmailTrackingService(session).link_message(
            message_id, payload.application_id
        )
    except EmailTrackingError as failure:
        raise _not_found(failure) from failure
    return EmailLinkResponse(
        message=EmailMessageRead.model_validate(message),
        suggestion=_suggestion_read(session, suggestion) if suggestion else None,
    )


@router.post(
    "/messages/{message_id}/dismiss",
    response_model=EmailMessageRead,
    dependencies=[Authorized],
    summary="Mark an email as not about any application",
)
def dismiss_email_message(
    message_id: int, session: DbSession, settings: AppSettings
) -> EmailMessageRead:
    refuse_in_demo_mode(settings, OPERATION)
    try:
        message = EmailTrackingService(session).dismiss_message(message_id)
    except EmailTrackingError as failure:
        raise _not_found(failure) from failure
    return EmailMessageRead.model_validate(message)


@router.post(
    "/disconnect",
    response_model=EmailDisconnectResponse,
    dependencies=[Authorized],
    summary="Revoke Gmail access and delete the stored token",
)
def disconnect_email(session: DbSession, settings: AppSettings) -> EmailDisconnectResponse:
    refuse_in_demo_mode(settings, OPERATION)
    client = _gmail(settings)
    accounts = _connected_accounts(session)
    revoked = 0
    try:
        for account in accounts:
            revoked += int(client.disconnect(session, account))
    except SecretStoreError as failure:
        raise ApiError(
            "secret_store_failed", redact(str(failure)), status.HTTP_500_INTERNAL_SERVER_ERROR
        ) from failure
    return EmailDisconnectResponse(disconnected=len(accounts), revoked=revoked)


@router.delete(
    "/data",
    response_model=EmailDeleteResponse,
    dependencies=[Authorized],
    summary="Disconnect, then delete every stored email, suggestion and account record",
)
def delete_email_data(session: DbSession, settings: AppSettings) -> EmailDeleteResponse:
    refuse_in_demo_mode(settings, OPERATION)
    client = _gmail(settings)
    try:
        for account in _connected_accounts(session):
            client.disconnect(session, account)
    except SecretStoreError as failure:
        raise ApiError(
            "secret_store_failed", redact(str(failure)), status.HTTP_500_INTERNAL_SERVER_ERROR
        ) from failure
    counts = EmailTrackingService(session).delete_data(everything=True)
    accounts = list(session.scalars(select(EmailAccount)))
    for account in accounts:
        session.delete(account)
    session.flush()
    return EmailDeleteResponse(
        messages=counts["messages"], suggestions=counts["suggestions"], accounts=len(accounts)
    )
