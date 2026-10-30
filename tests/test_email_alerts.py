"""Job-alert email parsing, tested entirely offline.

No IMAP connection is made. Messages are constructed in memory, which is what lets the
one authorized discovery path be covered without credentials or network access.
"""

from __future__ import annotations

import email
from email.message import EmailMessage

import pytest

from app.db.models import SourceName
from app.sources.base import CapabilityNotAvailable, SourceUnavailable
from app.sources.email_alerts import EmailAlertAdapter, parse_alert_message

LINKEDIN_ALERT = """Your job alert for backend developer

Backend Developer at Acme Technologies
Bengaluru, Karnataka (Hybrid)
https://www.linkedin.com/jobs/view/4011223344

Python Developer at Nova Labs
Remote
https://www.linkedin.com/jobs/view/4055667788

See all jobs
"""

INDEED_ALERT = """New jobs for you

Generative AI Engineer - Zeta Systems
Hyderabad, Telangana
https://in.indeed.com/viewjob?jk=abc123def456

Unsubscribe
"""


def _message(sender: str, subject: str, body: str, date: str | None = None) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["Subject"] = subject
    if date:
        message["Date"] = date
    message.set_content(body)
    return message


def test_a_linkedin_alert_yields_one_record_per_listing() -> None:
    parsed = parse_alert_message(
        _message(
            "LinkedIn Job Alerts <jobs-listings@linkedin.com>",
            "Backend Developer: 2 new jobs",
            LINKEDIN_ALERT,
            "Tue, 27 Oct 2026 09:15:00 +0000",
        )
    )

    assert parsed.source is SourceName.LINKEDIN
    assert len(parsed.records) == 2
    titles = {record.title for record in parsed.records}
    assert titles == {"Backend Developer", "Python Developer"}
    companies = {record.company for record in parsed.records}
    assert companies == {"Acme Technologies", "Nova Labs"}
    assert all(
        record.url.startswith("https://www.linkedin.com/jobs/view/") for record in parsed.records
    )


def test_the_alert_send_time_is_never_used_as_the_posting_date() -> None:
    """A job discovered today was not necessarily posted today."""
    parsed = parse_alert_message(
        _message(
            "LinkedIn <jobs@linkedin.com>",
            "New jobs",
            LINKEDIN_ALERT,
            "Tue, 27 Oct 2026 09:15:00 +0000",
        )
    )
    for record in parsed.records:
        assert record.posted_at is None
        assert record.source_metadata["alert_sent_at"].startswith("2026-10-27")
        assert "not stated" in record.source_metadata["note"]


def test_the_sender_domain_determines_the_source() -> None:
    cases = {
        "alerts@linkedin.com": SourceName.LINKEDIN,
        "noreply@indeed.com": SourceName.INDEED,
        "jobs@naukri.com": SourceName.NAUKRI,
        "team@wellfound.com": SourceName.WELLFOUND,
        "someone@unknown-board.com": SourceName.EMAIL_ALERT,
    }
    for sender, expected in cases.items():
        parsed = parse_alert_message(_message(sender, "Jobs", INDEED_ALERT))
        assert parsed.source is expected


def test_a_dash_separated_listing_is_parsed() -> None:
    parsed = parse_alert_message(_message("noreply@indeed.com", "New jobs for you", INDEED_ALERT))
    assert len(parsed.records) == 1
    assert parsed.records[0].title == "Generative AI Engineer"
    assert parsed.records[0].company == "Zeta Systems"


def test_an_html_only_alert_is_stripped_and_parsed() -> None:
    message = EmailMessage()
    message["From"] = "jobs@naukri.com"
    message["Subject"] = "Recommended jobs"
    message.set_content("fallback")
    message.add_alternative(
        "<html><body>"
        "<p>Backend Developer at Acme Technologies</p>"
        "<p>Bengaluru</p>"
        "<a href='https://www.naukri.com/job-listings-12345'>Apply</a>"
        "</body></html>",
        subtype="html",
    )
    parsed = parse_alert_message(message)
    assert any(record.title == "Backend Developer" for record in parsed.records)


def test_unsafe_links_in_an_alert_are_discarded() -> None:
    body = "Backend Developer at Acme Technologies\nBengaluru\njavascript:alert(1)\n"
    parsed = parse_alert_message(_message("jobs@linkedin.com", "Jobs", body))
    assert parsed.records == []


def test_an_alert_with_no_listings_yields_nothing_rather_than_guessing() -> None:
    parsed = parse_alert_message(
        _message("jobs@linkedin.com", "Your weekly digest", "Nothing new this week.\n")
    )
    assert parsed.records == []


def test_an_empty_message_is_handled() -> None:
    parsed = parse_alert_message(email.message_from_string(""))
    assert parsed.records == []


def test_duplicate_listings_inside_one_alert_are_collapsed() -> None:
    body = LINKEDIN_ALERT + "\nBackend Developer at Acme Technologies\nBengaluru\n"
    parsed = parse_alert_message(_message("jobs@linkedin.com", "Jobs", body))
    keys = [(record.title, record.company) for record in parsed.records]
    assert len(keys) == len(set(keys))


def test_offline_batch_parsing_returns_a_discovery_result() -> None:
    adapter = EmailAlertAdapter()
    result = adapter.parse_messages(
        [
            _message("jobs@linkedin.com", "Jobs", LINKEDIN_ALERT),
            _message("noreply@indeed.com", "Jobs", INDEED_ALERT),
        ]
    )
    assert len(result.records) == 3
    assert result.errors == []


def test_discovery_is_refused_while_the_feature_is_disabled(_isolated_settings) -> None:
    with pytest.raises(CapabilityNotAvailable, match="disabled"):
        EmailAlertAdapter(_isolated_settings).discover()


def test_enabling_without_credentials_reports_exactly_what_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings, reset_settings_cache

    monkeypatch.setenv("JA_EMAIL_INGEST_ENABLED", "true")
    monkeypatch.setenv("JA_EMAIL_IMAP_HOST", "")
    monkeypatch.setenv("JA_EMAIL_USERNAME", "")
    monkeypatch.setenv("JA_EMAIL_APP_PASSWORD", "")
    reset_settings_cache()

    with pytest.raises(CapabilityNotAvailable) as error:
        EmailAlertAdapter(get_settings()).discover()
    reason = error.value.reason
    assert "JA_EMAIL_IMAP_HOST" in reason
    assert "JA_EMAIL_USERNAME" in reason
    assert "JA_EMAIL_APP_PASSWORD" in reason
    reset_settings_cache()


def test_an_unreachable_imap_server_is_a_retryable_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings, reset_settings_cache

    monkeypatch.setenv("JA_EMAIL_INGEST_ENABLED", "true")
    monkeypatch.setenv("JA_EMAIL_IMAP_HOST", "imap.invalid")
    monkeypatch.setenv("JA_EMAIL_USERNAME", "user@example.com")
    monkeypatch.setenv("JA_EMAIL_APP_PASSWORD", "app-password")
    reset_settings_cache()

    def _explode(*_args, **_kwargs):
        raise OSError("name resolution failed")

    monkeypatch.setattr("app.sources.email_alerts.imaplib.IMAP4_SSL", _explode)
    with pytest.raises(SourceUnavailable) as error:
        EmailAlertAdapter(get_settings()).discover()
    assert error.value.retryable is True
    reset_settings_cache()


def test_a_rejected_login_is_not_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retrying a bad password would just lock the mailbox."""
    import imaplib

    from app.config import get_settings, reset_settings_cache

    monkeypatch.setenv("JA_EMAIL_INGEST_ENABLED", "true")
    monkeypatch.setenv("JA_EMAIL_IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("JA_EMAIL_USERNAME", "user@example.com")
    monkeypatch.setenv("JA_EMAIL_APP_PASSWORD", "wrong")
    reset_settings_cache()

    class FakeImap:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def login(self, *_args) -> None:
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")

    monkeypatch.setattr("app.sources.email_alerts.imaplib.IMAP4_SSL", FakeImap)
    with pytest.raises(SourceUnavailable) as error:
        EmailAlertAdapter(get_settings()).discover()
    assert error.value.retryable is False
    assert "app-specific password" in error.value.reason
    reset_settings_cache()


def test_the_mailbox_is_opened_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing in the user's mailbox may be modified."""
    from app.config import get_settings, reset_settings_cache

    monkeypatch.setenv("JA_EMAIL_INGEST_ENABLED", "true")
    monkeypatch.setenv("JA_EMAIL_IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("JA_EMAIL_USERNAME", "user@example.com")
    monkeypatch.setenv("JA_EMAIL_APP_PASSWORD", "app-password")
    reset_settings_cache()

    recorded: dict = {}
    raw = _message("jobs@linkedin.com", "Jobs", LINKEDIN_ALERT).as_bytes()

    class FakeImap:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def login(self, *_args) -> None:
            return None

        def select(self, folder, readonly=False):
            recorded["folder"] = folder
            recorded["readonly"] = readonly
            return "OK", [b"1"]

        def search(self, _charset, *criteria):
            recorded["criteria"] = criteria
            return "OK", [b"1"]

        def fetch(self, _identifier, _parts):
            return "OK", [(b"1 (RFC822 {n}", raw)]

        def close(self) -> None:
            recorded["closed"] = True

        def logout(self) -> None:
            recorded["logged_out"] = True

    monkeypatch.setattr("app.sources.email_alerts.imaplib.IMAP4_SSL", FakeImap)
    result = EmailAlertAdapter(get_settings()).discover()

    assert recorded["readonly"] is True
    assert recorded["criteria"][0] == "SINCE"
    assert recorded["closed"] and recorded["logged_out"]
    assert len(result.records) == 2
    assert result.metadata["messages_examined"] == 1
    reset_settings_cache()


def test_messages_that_yield_nothing_are_reported_not_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings, reset_settings_cache

    monkeypatch.setenv("JA_EMAIL_INGEST_ENABLED", "true")
    monkeypatch.setenv("JA_EMAIL_IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("JA_EMAIL_USERNAME", "user@example.com")
    monkeypatch.setenv("JA_EMAIL_APP_PASSWORD", "app-password")
    reset_settings_cache()

    raw = _message("jobs@linkedin.com", "Digest", "Nothing to report.\n").as_bytes()

    class FakeImap:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def login(self, *_args) -> None:
            return None

        def select(self, _folder, readonly=False):
            return "OK", [b"1"]

        def search(self, _charset, *_criteria):
            return "OK", [b"1"]

        def fetch(self, _identifier, _parts):
            return "OK", [(b"1 (RFC822 {n}", raw)]

        def close(self) -> None:
            return None

        def logout(self) -> None:
            return None

    monkeypatch.setattr("app.sources.email_alerts.imaplib.IMAP4_SSL", FakeImap)
    result = EmailAlertAdapter(get_settings()).discover()

    assert result.records == []
    assert any("no job listings could be extracted" in error for error in result.errors)
    reset_settings_cache()


def test_the_adapter_never_declares_automated_submission() -> None:
    adapter = EmailAlertAdapter()
    assert adapter.capabilities.automated_submission_enabled is False
    assert adapter.capabilities.authorized_discovery_enabled is True
    assert "your own" in adapter.policy_basis.lower()
