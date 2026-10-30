"""Job-alert email ingestion — the only authorized *discovery* path in this build.

It is authorized because the data is the user's own: job-alert emails that the platforms
themselves sent to the user's mailbox. Nothing is fetched from any platform's website.

Safeguards:

* Disabled by default (``JA_EMAIL_INGEST_ENABLED=false``).
* Read-only. The mailbox is opened, messages are listed and parsed, and nothing is marked,
  moved or deleted.
* The password is read from the environment per run and is never written to the database.
  Use an app-specific password, not your account password.
* Email bodies are untrusted input. Links are extracted with the same URL safety checks as
  every other source, and the text is never interpreted as instructions.
"""

from __future__ import annotations

import email
import imaplib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.header import decode_header, make_header
from email.message import Message

from app.config import Settings, get_settings
from app.db.models import SourceName, utcnow
from app.logging_conf import get_logger
from app.schemas.job import RawJobRecord
from app.services.text import collapse_whitespace
from app.services.url_safety import inspect_url
from app.sources.base import (
    AdapterCapabilities,
    CapabilityNotAvailable,
    DiscoveryResult,
    SourceAdapter,
    SourceUnavailable,
)

logger = get_logger(__name__)

MAX_MESSAGES_PER_RUN = 50

_SENDER_TO_SOURCE: tuple[tuple[str, SourceName], ...] = (
    ("linkedin.com", SourceName.LINKEDIN),
    ("indeed.com", SourceName.INDEED),
    ("naukri.com", SourceName.NAUKRI),
    ("infoedge.", SourceName.NAUKRI),
    ("wellfound.com", SourceName.WELLFOUND),
    ("angel.co", SourceName.WELLFOUND),
)

# Job-alert mails almost always render each listing as "<title> at <company>" or
# "<title> - <company>" immediately before the apply link.
_TITLE_AT_COMPANY = re.compile(
    r"^\s*(?P<title>[A-Z][\w/&'+.()\- ]{3,90}?)\s+(?:at|@|-|\u2013|\|)\s+(?P<company>[A-Z][\w&'.,()\- ]{1,70})\s*$",
    re.MULTILINE,
)
_LOCATION_LINE = re.compile(
    r"^\s*(?P<location>(?:remote|hybrid|on-?site|[A-Z][a-z]+(?:[ ,][A-Z][a-z]+){0,3}))\s*(?:\(|\u00b7|\|)?",
    re.MULTILINE | re.IGNORECASE,
)
_HTML_TAG = re.compile(r"<[^>]+>")
_ANCHOR_HREF = re.compile(r"<a\b[^>]*?href\s*=\s*[\"']([^\"']+)[\"'][^>]*>", re.IGNORECASE)
_JOB_LINK = re.compile(r"https?://[^\s\"'<>)]+", re.IGNORECASE)


def _html_to_text(html: str) -> str:
    """Convert HTML to text while keeping anchor targets.

    Stripping tags naively discards every ``href``, which in a job-alert email is the
    apply link itself. Each anchor is therefore replaced by its URL on its own line before
    the remaining tags are removed.
    """
    with_links = _ANCHOR_HREF.sub(lambda match: f"\n{match.group(1)}\n", html)
    unescaped = (
        with_links.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return _HTML_TAG.sub("\n", unescaped)


@dataclass(frozen=True, slots=True)
class ParsedAlert:
    source: SourceName
    records: list[RawJobRecord]
    subject: str


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _message_text(message: Message) -> str:
    """Extract readable text from every text part.

    Both the plain and HTML parts are returned, plain first. Job alerts routinely put a
    stub like "view this email in your browser" in text/plain and the actual listings in
    the HTML alternative, so preferring one part loses listings. Duplicate listings across
    the two parts are collapsed later by their (title, company) key.
    """
    plain: list[str] = []
    html: list[str] = []
    for part in message.walk():
        if part.get_content_maintype() != "text":
            continue
        try:
            payload = part.get_payload(decode=True)
        except Exception:
            continue
        if not isinstance(payload, bytes | bytearray):
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = bytes(payload).decode(charset, errors="replace")
        except LookupError:
            text = bytes(payload).decode("utf-8", errors="replace")
        if part.get_content_subtype() == "html":
            html.append(text)
        else:
            plain.append(text)

    stripped = _html_to_text("\n".join(html)) if html else ""
    combined = "\n".join(plain + ([stripped] if stripped else []))
    return re.sub(r"\n{3,}", "\n\n", combined)


def _source_for_sender(sender: str) -> SourceName:
    lowered = sender.lower()
    for fragment, source in _SENDER_TO_SOURCE:
        if fragment in lowered:
            return source
    return SourceName.EMAIL_ALERT


def _message_date(message: Message) -> datetime | None:
    raw = message.get("Date")
    if not raw:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_alert_message(message: Message) -> ParsedAlert:
    """Extract job records from one job-alert email.

    The alert tells us when *the alert* was sent, which is not when the job was posted, so
    ``posted_at`` is left unset and only the sent date is kept in metadata. Guessing here
    would be exactly the "discovered today means posted today" error.
    """
    sender = _decode(message.get("From"))
    subject = _decode(message.get("Subject"))
    source = _source_for_sender(sender)
    text = _message_text(message)
    sent_at = _message_date(message)

    links = [
        candidate
        for candidate in dict.fromkeys(_JOB_LINK.findall(text))
        if inspect_url(candidate).safe
    ]

    records: list[RawJobRecord] = []
    seen: set[tuple[str, str]] = set()
    for index, match in enumerate(_TITLE_AT_COMPANY.finditer(text)):
        title = collapse_whitespace(match.group("title"))
        company = collapse_whitespace(match.group("company"))
        if len(title) < 4 or len(company) < 2:
            continue
        key = (title.lower(), company.lower())
        if key in seen:
            continue
        seen.add(key)

        tail = text[match.end() : match.end() + 200]
        location_match = _LOCATION_LINE.search(tail)
        location = collapse_whitespace(location_match.group("location")) if location_match else ""
        url = links[index] if index < len(links) else (links[0] if links else "")
        if not url:
            continue

        try:
            records.append(
                RawJobRecord(
                    source=source,
                    title=title,
                    company=company,
                    location=location,
                    url=url,
                    description="",
                    retrieval_method="email_alert",
                    posted_at=None,
                    source_metadata={
                        "alert_subject": subject[:200],
                        "alert_sender": sender[:200],
                        "alert_sent_at": sent_at.isoformat() if sent_at else None,
                        "note": (
                            "Extracted from a job-alert email. The posting date was not "
                            "stated, so it is unknown; the alert's own send time is "
                            "recorded here instead."
                        ),
                    },
                )
            )
        except Exception as exc:
            logger.debug("skipped an unparseable alert entry", extra={"reason": str(exc)})
    return ParsedAlert(source=source, records=records, subject=subject)


class EmailAlertAdapter(SourceAdapter):
    """Reads job-alert emails from the user's own mailbox over IMAP, read-only."""

    source = SourceName.EMAIL_ALERT
    display_name = "Job-alert email (IMAP)"
    capabilities = AdapterCapabilities(
        manual_import_enabled=True,
        authorized_discovery_enabled=True,
        browser_assistance_enabled=True,
    )
    policy_basis = (
        "The data is your own: emails the platforms sent to your mailbox. No platform "
        "website is accessed. Access is read-only, opt-in, and disabled by default."
    )
    limitations = (
        "Disabled until you set JA_EMAIL_INGEST_ENABLED=true and the IMAP settings.",
        "Alert emails rarely state the original posting date, so freshness usually cannot "
        "be scored for these jobs.",
        "Alert emails carry a title, company and link but no description, so skills are "
        "unknown until you open the listing.",
        "Use an app-specific password. Your password is read from the environment and "
        "never stored in the database.",
    )

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def _connect(self) -> imaplib.IMAP4_SSL:
        settings = self._settings
        try:
            client = imaplib.IMAP4_SSL(settings.email_imap_host, settings.email_imap_port)
        except Exception as exc:
            raise SourceUnavailable(
                self.source, f"could not reach the IMAP server: {type(exc).__name__}"
            ) from exc
        try:
            client.login(settings.email_username, settings.email_app_password)
        except imaplib.IMAP4.error as exc:
            raise SourceUnavailable(
                self.source,
                "the IMAP server rejected the login. Check JA_EMAIL_USERNAME and use an "
                "app-specific password.",
                retryable=False,
            ) from exc
        return client

    def discover(self, *, query: dict[str, object] | None = None) -> DiscoveryResult:
        settings = self._settings
        if not settings.email_ingest_enabled:
            raise CapabilityNotAvailable(
                self.source,
                "authorized_discovery",
                "Email job-alert ingestion is disabled. Set JA_EMAIL_INGEST_ENABLED=true "
                "and provide JA_EMAIL_IMAP_HOST, JA_EMAIL_USERNAME and "
                "JA_EMAIL_APP_PASSWORD to enable it.",
            )
        missing = [
            name
            for name, value in (
                ("JA_EMAIL_IMAP_HOST", settings.email_imap_host),
                ("JA_EMAIL_USERNAME", settings.email_username),
                ("JA_EMAIL_APP_PASSWORD", settings.email_app_password),
            )
            if not value
        ]
        if missing:
            raise CapabilityNotAvailable(
                self.source,
                "authorized_discovery",
                f"Email ingestion is enabled but these settings are missing: {', '.join(missing)}.",
            )

        raw_days = (query or {}).get("days", 7)
        days = int(raw_days) if isinstance(raw_days, int | str) else 7
        since = (utcnow() - timedelta(days=days)).strftime("%d-%b-%Y")
        errors: list[str] = []
        records: list[RawJobRecord] = []
        examined = 0

        client = self._connect()
        try:
            status, _ = client.select(settings.email_folder, readonly=True)
            if status != "OK":
                raise SourceUnavailable(
                    self.source,
                    f"could not open the mailbox folder '{settings.email_folder}'",
                    retryable=False,
                )
            status, data = client.search(None, "SINCE", since)
            if status != "OK":
                raise SourceUnavailable(self.source, "the IMAP search failed")

            identifiers = (data[0].split() if data and data[0] else [])[-MAX_MESSAGES_PER_RUN:]
            for identifier in identifiers:
                status, payload = client.fetch(identifier, "(RFC822)")
                if status != "OK" or not payload:
                    errors.append(f"message {identifier!r} could not be fetched")
                    continue
                raw = next(
                    (item[1] for item in payload if isinstance(item, tuple) and len(item) > 1),
                    None,
                )
                if not isinstance(raw, bytes | bytearray):
                    continue
                examined += 1
                parsed = parse_alert_message(email.message_from_bytes(bytes(raw)))
                records.extend(parsed.records)
        finally:
            try:
                client.close()
            except Exception:
                pass
            try:
                client.logout()
            except Exception:
                pass

        if examined and not records:
            errors.append(
                f"{examined} message(s) were read but no job listings could be extracted. "
                "Alert layouts change; use CSV import for these."
            )
        return DiscoveryResult(
            records=records,
            errors=errors,
            metadata={
                "messages_examined": examined,
                "since": since,
                "folder": settings.email_folder,
            },
        )

    def parse_messages(self, messages: Iterable[Message]) -> DiscoveryResult:
        """Parse already-loaded messages. Used by tests and by offline .eml import."""
        records: list[RawJobRecord] = []
        for message in messages:
            records.extend(parse_alert_message(message).records)
        return DiscoveryResult(records=records, metadata={"messages_examined": "offline"})

    def health(self) -> tuple[bool, str]:
        if not self._settings.email_ingest_enabled:
            return False, (
                "Disabled. Set JA_EMAIL_INGEST_ENABLED=true and the IMAP settings to use it."
            )
        if not self._settings.email_imap_host:
            return False, "Enabled but JA_EMAIL_IMAP_HOST is not set."
        return True, "Enabled and configured for read-only mailbox access."
