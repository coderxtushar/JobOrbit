"""Read-only Gmail access through installed-app OAuth 2.0 with PKCE.

What this module will and will not do:

* It requests exactly one scope, ``gmail.readonly``. That scope cannot send, delete,
  label or modify mail, so a bug here cannot touch the mailbox; and a token response that
  grants anything else is refused and revoked.
* It talks only to Google's OAuth endpoints (authorise, token, revoke) and to two Gmail
  read endpoints: ``users.messages.list`` and ``users.messages.get``. Every Gmail request
  is a GET. There is no code path to a send, modify, trash or label endpoint.
* It never sees a password. The user signs in on Google's own page in their browser.
* The refresh token is written to the :class:`~app.services.secrets.SecretStore`, keyed
  by account id, and never to the database or a log. Access tokens live in memory only.
* A sync reads a narrow query (job-related words or known hiring-system senders, within
  ``JA_EMAIL_SYNC_DAYS``, excluding the Promotions tab), at most ``JA_EMAIL_MAX_MESSAGES``
  messages, and keeps only those the classifier judges job-related.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import message_from_bytes
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import EmailAccount, utcnow
from app.logging_conf import get_logger
from app.services.email_tracking.classifier import ASSESSMENT_DOMAINS, ATS_SENDER_DOMAINS
from app.services.email_tracking.service import EmailTrackingService
from app.services.redaction import redact
from app.services.secrets import SecretStore

logger = get_logger(__name__)

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"

PENDING_TTL_SECONDS = 600
HTTP_TIMEOUT_SECONDS = 20.0
LIST_PAGE_SIZE = 100

_QUERY_TERMS = (
    '"your application"',
    '"thank you for applying"',
    '"thanks for applying"',
    '"application received"',
    "interview",
    "assessment",
    '"coding challenge"',
    '"offer letter"',
    "unfortunately",
    "recruiter",
    "candidacy",
)


def _describe_gmail_error(response: httpx.Response) -> str:
    """Turn a Gmail error into something a person can act on.

    Google's error body names the cause (an API switched off, a quota, a missing scope);
    it carries no token or message content, so its own message is safe to show.
    """
    status = response.status_code
    try:
        error = response.json().get("error") or {}
    except (ValueError, AttributeError):
        error = {}
    if not isinstance(error, dict):
        error = {}
    reasons = {
        str(item.get("reason")) for item in error.get("errors") or [] if isinstance(item, dict)
    }
    reasons |= {
        str(item.get("reason")) for item in error.get("details") or [] if isinstance(item, dict)
    }
    if reasons & {"accessNotConfigured", "SERVICE_DISABLED"}:
        return (
            "The Gmail API is turned off in the Google Cloud project that owns your OAuth "
            "client. In Google Cloud Console, open APIs & Services, then Library, search "
            "for Gmail API and press Enable. Wait a minute, then connect again."
        )
    message = " ".join(str(error.get("message") or "").split())[:300]
    return (
        f"Gmail returned HTTP {status}: {message}" if message else f"Gmail returned HTTP {status}"
    )


class GmailError(RuntimeError):
    """A user-facing Gmail failure. Messages are redacted and never contain tokens."""


class GmailNotConfigured(GmailError):
    pass


def refresh_token_key(account_id: int) -> str:
    return f"gmail-refresh-token-{account_id}"


def redirect_uri(settings: Settings) -> str:
    return f"http://127.0.0.1:{settings.api_port}/api/email/gmail/callback"


def build_query(settings: Settings) -> str:
    """The Gmail search used by a sync: narrow on purpose, never the whole mailbox."""
    senders = " ".join(f"from:{domain}" for domain in (*ATS_SENDER_DOMAINS, *ASSESSMENT_DOMAINS))
    terms = " ".join(_QUERY_TERMS)
    return (
        f"newer_than:{settings.email_sync_days}d -category:promotions -category:social "
        f"{{{terms} {senders}}}"
    )


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


@dataclass(slots=True)
class _PendingAuthorization:
    verifier: str
    created: float


#: Outstanding authorisations, keyed by the ``state`` value. In memory because the
#: callback is served by the same local API process that issued the URL, and a verifier
#: that survives a restart would only widen the window in which it could be replayed.
_PENDING: dict[str, _PendingAuthorization] = {}
_PENDING_LOCK = threading.Lock()
#: account id -> (access token, monotonic expiry).
_ACCESS_TOKENS: dict[int, tuple[str, float]] = {}


@dataclass(slots=True)
class SyncReport:
    listed: int = 0
    fetched: int = 0
    kept: int = 0
    duplicates: int = 0
    skipped_not_job_related: int = 0
    suggestions: int = 0
    needs_review: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "listed": self.listed,
            "fetched": self.fetched,
            "kept": self.kept,
            "duplicates": self.duplicates,
            "skipped_not_job_related": self.skipped_not_job_related,
            "suggestions": self.suggestions,
            "needs_review": self.needs_review,
            "errors": list(self.errors),
        }


class GmailClient:
    def __init__(
        self,
        settings: Settings | None = None,
        store: SecretStore | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._store = store
        self._transport = transport

    @property
    def store(self) -> SecretStore:
        if self._store is None:
            self._store = SecretStore(self._settings)
        return self._store

    def _http(self) -> httpx.Client:
        return httpx.Client(
            transport=self._transport, timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=False
        )

    # ------------------------------------------------------------------ OAuth

    def ensure_configured(self) -> None:
        if not self._settings.email_tracking_enabled:
            raise GmailNotConfigured(
                "Email tracking is off. Set JA_EMAIL_TRACKING_ENABLED=true to opt in."
            )
        if not self._settings.gmail_client_id.strip():
            raise GmailNotConfigured(
                "No Gmail OAuth client is configured. Create a Desktop OAuth client in your "
                "own Google Cloud project and set JA_GMAIL_CLIENT_ID (see "
                "docs/EMAIL_TRACKING.md)."
            )

    def authorization_url(self) -> str:
        """Start an authorisation: a fresh ``state`` and PKCE verifier per call."""
        self.ensure_configured()
        state = secrets.token_urlsafe(32)
        verifier, challenge = _pkce_pair()
        now = time.monotonic()
        with _PENDING_LOCK:
            for key, pending in list(_PENDING.items()):
                if now - pending.created > PENDING_TTL_SECONDS:
                    del _PENDING[key]
            _PENDING[state] = _PendingAuthorization(verifier=verifier, created=now)
        params = {
            "client_id": self._settings.gmail_client_id.strip(),
            "redirect_uri": redirect_uri(self._settings),
            "response_type": "code",
            "scope": GMAIL_READONLY_SCOPE,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            # Offline access is what yields a refresh token; consent forces Google to
            # return one even if the user authorised this client before.
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{AUTH_ENDPOINT}?{urlencode(params)}"

    @staticmethod
    def _take_pending(state: str) -> _PendingAuthorization:
        with _PENDING_LOCK:
            pending = _PENDING.pop(state or "", None)
        if pending is None or time.monotonic() - pending.created > PENDING_TTL_SECONDS:
            raise GmailError(
                "This sign-in link is unknown or has expired. Start again from JobOrbit."
            )
        return pending

    def _post_form(self, url: str, data: dict[str, str]) -> dict[str, Any]:
        try:
            with self._http() as client:
                response = client.post(url, data=data)
        except httpx.HTTPError as error:
            raise GmailError(f"Google could not be reached: {type(error).__name__}") from error
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400:
            code = (
                str(payload.get("error", response.status_code)) if isinstance(payload, dict) else ""
            )
            raise GmailError(redact(f"Google refused the request ({code})"))
        return payload if isinstance(payload, dict) else {}

    def complete_authorization(self, session: Session, code: str, state: str) -> EmailAccount:
        """Exchange the authorisation code, verify the granted scope, store the token."""
        self.ensure_configured()
        pending = self._take_pending(state)
        if not code:
            raise GmailError("Google did not return an authorisation code.")
        data = {
            "code": code,
            "client_id": self._settings.gmail_client_id.strip(),
            "redirect_uri": redirect_uri(self._settings),
            "grant_type": "authorization_code",
            "code_verifier": pending.verifier,
        }
        if self._settings.gmail_client_secret:
            data["client_secret"] = self._settings.gmail_client_secret
        tokens = self._post_form(TOKEN_ENDPOINT, data)
        access_token = str(tokens.get("access_token") or "")
        refresh_token = str(tokens.get("refresh_token") or "")
        granted = set(str(tokens.get("scope") or "").split())
        if granted != {GMAIL_READONLY_SCOPE}:
            self._revoke(refresh_token or access_token)
            raise GmailError(
                "Google granted a different set of permissions than the read-only scope "
                "JobOrbit asked for, so the connection was refused and revoked."
            )
        if not access_token or not refresh_token:
            self._revoke(refresh_token or access_token)
            raise GmailError(
                "Google did not return a refresh token. Remove JobOrbit's access at "
                "myaccount.google.com/permissions and connect again."
            )

        try:
            address = self._profile_address(access_token)
        except GmailError:
            # The grant is useless if Gmail itself refuses it, so do not leave it live.
            self._revoke(refresh_token)
            raise
        account = session.scalars(
            select(EmailAccount).where(
                EmailAccount.provider == "gmail", EmailAccount.address == address
            )
        ).first()
        if account is None:
            account = EmailAccount(provider="gmail", address=address)
            session.add(account)
        account.scopes = [GMAIL_READONLY_SCOPE]
        account.status = "connected"
        account.connected_at = utcnow()
        account.last_error = ""
        session.flush()
        self.store.set(refresh_token_key(account.id), refresh_token)
        expires_in = float(tokens.get("expires_in") or 3000)
        _ACCESS_TOKENS[account.id] = (access_token, time.monotonic() + expires_in - 60)
        logger.info("gmail connected", extra={"detail": f"account {account.id}"})
        return account

    def _profile_address(self, access_token: str) -> str:
        payload = self._get(f"{GMAIL_API}/profile", access_token)
        return str(payload.get("emailAddress") or "")[:320]

    def _access_token(self, session: Session, account: EmailAccount) -> str:
        cached = _ACCESS_TOKENS.get(account.id)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        refresh_token = self.store.get(refresh_token_key(account.id))
        if not refresh_token:
            account.status = "reauth_required"
            account.last_error = "No stored token. Connect Gmail again."
            session.flush()
            raise GmailError(account.last_error)
        data = {
            "client_id": self._settings.gmail_client_id.strip(),
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        if self._settings.gmail_client_secret:
            data["client_secret"] = self._settings.gmail_client_secret
        try:
            tokens = self._post_form(TOKEN_ENDPOINT, data)
        except GmailError as error:
            account.status = "reauth_required"
            account.last_error = redact(
                f"{error}. Google expires refresh tokens after 7 days for apps in testing "
                "mode; connect again."
            )
            session.flush()
            raise GmailError(account.last_error) from error
        access_token = str(tokens.get("access_token") or "")
        if not access_token:
            raise GmailError("Google returned no access token.")
        expires_in = float(tokens.get("expires_in") or 3000)
        _ACCESS_TOKENS[account.id] = (access_token, time.monotonic() + expires_in - 60)
        return access_token

    # ------------------------------------------------------------------ Gmail reads

    def _get(
        self, url: str, access_token: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """The only way this module calls Gmail: an authorised GET."""
        try:
            with self._http() as client:
                response = client.get(
                    url, params=params, headers={"Authorization": f"Bearer {access_token}"}
                )
        except httpx.HTTPError as error:
            raise GmailError(f"Gmail could not be reached: {type(error).__name__}") from error
        if response.status_code >= 400:
            raise GmailError(_describe_gmail_error(response))
        try:
            payload = response.json()
        except ValueError as error:
            raise GmailError("Gmail returned a response that is not JSON") from error
        return payload if isinstance(payload, dict) else {}

    def list_message_ids(self, access_token: str) -> list[tuple[str, str]]:
        """``(message id, thread id)`` pairs for the sync query, capped."""
        cap = self._settings.email_max_messages
        query = build_query(self._settings)
        found: list[tuple[str, str]] = []
        page_token = ""
        while len(found) < cap:
            params: dict[str, Any] = {
                "q": query,
                "maxResults": min(LIST_PAGE_SIZE, cap - len(found)),
            }
            if page_token:
                params["pageToken"] = page_token
            payload = self._get(f"{GMAIL_API}/messages", access_token, params)
            for item in payload.get("messages") or []:
                if isinstance(item, dict) and item.get("id"):
                    found.append((str(item["id"]), str(item.get("threadId") or "")))
            page_token = str(payload.get("nextPageToken") or "")
            if not page_token:
                break
        return found[:cap]

    def sync(self, session: Session, account: EmailAccount) -> SyncReport:
        """Fetch recent candidate messages and keep the job-related ones."""
        self.ensure_configured()
        if account.status == "disconnected":
            raise GmailError("This Gmail account is disconnected. Connect it again first.")
        token = self._access_token(session, account)
        service = EmailTrackingService(session)
        report = SyncReport()
        try:
            ids = self.list_message_ids(token)
        except GmailError as error:
            account.last_error = redact(str(error))
            session.flush()
            raise
        report.listed = len(ids)
        for message_id, thread_id in ids:
            if service.find_existing(message_id, account.id) is not None:
                report.duplicates += 1
                continue
            try:
                payload = self._get(f"{GMAIL_API}/messages/{message_id}", token, {"format": "raw"})
                raw = base64.urlsafe_b64decode(str(payload.get("raw") or "") + "===")
            except (GmailError, ValueError) as error:
                report.errors.append(redact(f"message could not be read: {error}"))
                continue
            report.fetched += 1
            received_at = None
            internal = payload.get("internalDate")
            if internal and str(internal).isdigit():
                received_at = datetime.fromtimestamp(int(internal) / 1000, tz=UTC)
            result = service.ingest_message(
                message_from_bytes(raw),
                account_id=account.id,
                provider_message_id=message_id,
                thread_id=thread_id,
                received_at=received_at,
            )
            del raw, payload  # the body is not kept past this point
            if result.outcome == "created":
                report.kept += 1
                if result.suggestion is not None:
                    report.suggestions += 1
                if result.message is not None and result.message.match_state == "needs_review":
                    report.needs_review += 1
            elif result.outcome == "duplicate":
                report.duplicates += 1
            else:
                report.skipped_not_job_related += 1
        account.last_sync_at = utcnow()
        account.last_error = "; ".join(report.errors)[:2000]
        session.flush()
        return report

    # ------------------------------------------------------------------ disconnect

    def _revoke(self, token: str) -> bool:
        if not token:
            return False
        try:
            with self._http() as client:
                response = client.post(REVOKE_ENDPOINT, data={"token": token})
            return response.status_code < 400
        except httpx.HTTPError:
            return False

    def disconnect(self, session: Session, account: EmailAccount) -> bool:
        """Revoke at Google (best effort), delete the stored token, mark disconnected."""
        key = refresh_token_key(account.id)
        refresh_token = self.store.get(key)
        revoked = self._revoke(refresh_token or "")
        self.store.delete(key)
        _ACCESS_TOKENS.pop(account.id, None)
        account.status = "disconnected"
        account.last_error = (
            ""
            if revoked or not refresh_token
            else (
                "Google's revoke endpoint did not confirm; remove access at "
                "myaccount.google.com/permissions to be sure."
            )
        )
        session.flush()
        return revoked


__all__ = [
    "AUTH_ENDPOINT",
    "GMAIL_API",
    "GMAIL_READONLY_SCOPE",
    "REVOKE_ENDPOINT",
    "TOKEN_ENDPOINT",
    "GmailClient",
    "GmailError",
    "GmailNotConfigured",
    "SyncReport",
    "build_query",
    "redirect_uri",
    "refresh_token_key",
]
