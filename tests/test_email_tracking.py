"""Email response tracking: classification, extraction, matching, suggestions, Gmail.

No test here reaches Google. Gmail is exercised through ``httpx.MockTransport``, which
also records every request so the tests can assert that nothing but read-only GETs ever
went to the Gmail API.
"""

from __future__ import annotations

import base64
import itertools
import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage as MimeMessage
from email.utils import format_datetime, make_msgid
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings, reset_settings_cache
from app.db.models import (
    Application,
    ApplicationStatus,
    AutoApplyRun,
    CandidateProfile,
    EmailAccount,
    EmailMessage,
    Outcome,
    SourceName,
    StatusSuggestion,
    SubmissionAttempt,
    SubmissionState,
)
from app.services.email_tracking import gmail as gmail_module
from app.services.email_tracking.classifier import classify
from app.services.email_tracking.extract import extract, find_dates
from app.services.email_tracking.gmail import (
    GMAIL_READONLY_SCOPE,
    GmailClient,
    GmailError,
    refresh_token_key,
)
from app.services.email_tracking.service import (
    EmailTrackingService,
    SuggestionNotApplicable,
)
from app.services.secrets import SecretStore
from tests.conftest import persist_job, utc_days_ago

_ids = itertools.count(1)


@pytest.fixture(autouse=True)
def _clean_gmail_state() -> Iterator[None]:
    gmail_module._PENDING.clear()
    gmail_module._ACCESS_TOKENS.clear()
    yield
    gmail_module._PENDING.clear()
    gmail_module._ACCESS_TOKENS.clear()


@pytest.fixture
def tracking_enabled(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("JA_EMAIL_TRACKING_ENABLED", "true")
    monkeypatch.setenv("JA_GMAIL_CLIENT_ID", "test-client.apps.googleusercontent.com")
    monkeypatch.setenv("JA_GMAIL_CLIENT_SECRET", "test-installed-app-secret")
    monkeypatch.setenv("JA_SECRET_BACKEND", "file")
    reset_settings_cache()
    yield
    reset_settings_cache()


# --------------------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------------------


def make_application(
    session: Session,
    profile: CandidateProfile,
    *,
    company: str = "Acme Technologies",
    title: str = "Backend Engineer",
    url: str = "https://boards.greenhouse.io/acme/jobs/1001",
    status: ApplicationStatus = ApplicationStatus.SUBMITTED,
    days_ago: float = 5,
) -> Application:
    number = next(_ids)
    job = persist_job(
        session,
        source=SourceName.MANUAL,
        external_id=f"EMAIL-{number}",
        title=title,
        company=company,
        url=url,
        description=f"{title} at {company} number {number}.",
    )
    application = Application(
        job_id=job.id,
        profile_id=profile.id,
        platform=SourceName.MANUAL,
        status=status,
        created_at=utc_days_ago(days_ago),
        prepared_at=utc_days_ago(days_ago),
    )
    if status in (ApplicationStatus.SUBMITTED, ApplicationStatus.SUBMISSION_UNKNOWN):
        application.submitted_at = utc_days_ago(days_ago)
        application.submitted_by = "user"
    session.add(application)
    session.flush()
    return application


def make_eml(
    subject: str,
    body: str,
    sender: str,
    *,
    to: str = "test@example.com",
    date: datetime | None = None,
    message_id: str | None = None,
) -> str:
    message = MimeMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = to
    message["Date"] = format_datetime(date or datetime.now(UTC))
    message["Message-ID"] = message_id or make_msgid(domain="mail.example")
    message.set_content(body)
    return message.as_string()


CONFIRMATION = (
    "Thank you for applying to Acme Technologies",
    "Hi Test, thank you for applying to the Backend Engineer position at Acme Technologies. "
    "We have received your application and our team will review it shortly.",
    "Acme Technologies Recruiting <no-reply@greenhouse.io>",
)
REJECTION = (
    "Your application to Acme Technologies",
    "Thank you for applying to the Backend Engineer position at Acme Technologies. "
    "Unfortunately, after careful consideration we have decided to move forward with other "
    "candidates whose experience more closely matches our needs.",
    "Acme Technologies Recruiting <no-reply@greenhouse.io>",
)


# --------------------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("subject", "body", "sender", "expected"),
    [
        (*CONFIRMATION, "application_confirmation"),
        (
            "Thanks for applying to Ramp!",
            "Hi there, thanks for applying to Ramp. We've received your application for "
            "Software Engineer, Backend and will be in touch if there is a fit.",
            "Ramp <no-reply@ashbyhq.com>",
            "application_confirmation",
        ),
        (
            "Application submitted: Software Engineer II",
            "Thank you for applying for the position of Software Engineer II. Your "
            "application has been submitted. Application ID: JR123456",
            "Globex Careers <globex@myworkday.com>",
            "application_confirmation",
        ),
        (*REJECTION, "rejection"),
        (
            "Update on your application",
            "Hi, thank you for your interest in Initech. We will not be moving forward with "
            "your application at this time. We wish you the best in your job search.",
            "Initech <no-reply@hire.lever.co>",
            "rejection",
        ),
        (
            "Interview invitation - Software Engineer at Globex",
            "We were impressed by your profile and would like to invite you to an interview "
            "for the Software Engineer role. Please share your availability for next week.",
            "Globex Talent <talent@globex.com>",
            "interview_invitation",
        ),
        (
            "Next steps: schedule your technical interview",
            "Please use this link to schedule an interview with our team: "
            "https://calendly.com/globex/tech-interview",
            "Globex Recruiting <recruiting@globex.com>",
            "interview_invitation",
        ),
        (
            "Acme has invited you to a HackerRank test",
            "You have been invited to take the Acme coding assessment. Please complete it "
            "within 3 days: https://www.hackerrank.com/test/abc123/login",
            "Acme via HackerRank <support@hackerrank.com>",
            "assessment_invitation",
        ),
        (
            "Codility: complete your task",
            "Please complete the online assessment for Hooli. https://app.codility.com/c/xyz",
            "Codility <no-reply@codility.com>",
            "assessment_invitation",
        ),
        (
            "Your offer from Globex",
            "We are delighted to offer you the position of Data Analyst at Globex. Please "
            "find your offer letter attached.",
            "Globex HR <hr@globex.com>",
            "offer",
        ),
        (
            "Exciting backend opportunity",
            "Hi, I came across your profile and I'm a technical recruiter at Hooli. Would you "
            "be open to new opportunities?",
            "Jane Doe <jane@hooli.com>",
            "recruiter_message",
        ),
        (
            "Your application is under review",
            "Hi, your application for Backend Developer is currently under review.",
            "Workday <acme@myworkday.com>",
            "process_update",
        ),
        (
            "15 new jobs for you",
            "Jobs you may be interested in: Python Developer at X, Software Engineer at Y.",
            "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
            "not_job_related",
        ),
        (
            "Weekend sale: 40% off",
            "Our biggest sale of the year starts now. Free shipping on every order.",
            "Shop <news@shop.example>",
            "not_job_related",
        ),
    ],
)
def test_classification_of_realistic_emails(subject, body, sender, expected) -> None:
    result = classify(subject, body, sender)
    assert result.category == expected, result.reasons
    assert 0.0 < result.confidence <= 1.0
    if expected != "not_job_related":
        assert result.reasons


def test_rejection_beats_confirmation_when_both_appear() -> None:
    result = classify(
        "Thank you for applying",
        "Thank you for applying to Acme. We have received your application. Unfortunately, "
        "the team has chosen not to proceed further.",
        "careers@acme.example",
    )
    assert result.category == "rejection"


def test_an_unfortunately_disclaimer_in_a_confirmation_is_not_a_rejection() -> None:
    result = classify(
        "Application received",
        "Thank you for applying. Due to the high volume of applications, unfortunately we "
        "cannot respond to every applicant individually.",
        "Initech Careers <careers@initech.example>",
    )
    assert result.category == "application_confirmation"


def test_an_interview_word_in_a_rejection_does_not_make_it_an_invitation() -> None:
    result = classify(
        "Following up on your interview",
        "Thank you for interviewing with us. Unfortunately we have decided to move forward "
        "with other candidates.",
        "talent@globex.example",
    )
    assert result.category == "rejection"


# --------------------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------------------

RECEIVED = datetime(2026, 11, 21, 9, 0, tzinfo=UTC)


def test_extracts_interview_datetime_timezone_and_meeting_link() -> None:
    facts = extract(
        "Interview invitation - Software Engineer at Globex",
        "Your interview is scheduled for Monday, 30 November 2026 at 3:30 PM IST. "
        "Join here: https://zoom.us/j/123456789?pwd=abc.",
        "Globex Talent <talent@globex.com>",
        RECEIVED,
    )
    assert facts.employer == "Globex"
    assert facts.job_title == "Software Engineer"
    assert facts.interview_date == "2026-11-30"
    assert facts.interview_time == "15:30"
    assert facts.interview_timezone == "IST"
    assert facts.interview_at == "2026-11-30T15:30:00+05:30"
    assert facts.meeting_link == "https://zoom.us/j/123456789?pwd=abc"
    assert facts.sender_domain == "globex.com"
    assert facts.timestamp == RECEIVED.isoformat()


@pytest.mark.parametrize(
    "link",
    [
        "https://meet.google.com/abc-defg-hij",
        "https://teams.microsoft.com/l/meetup-join/19%3ameeting_x/0",
        "https://acme.webex.com/meet/recruiter",
    ],
)
def test_extracts_other_meeting_providers(link: str) -> None:
    facts = extract(
        "Interview", f"Interview call on 2026-12-01 at 10:00. Link: {link}", "a@b.example"
    )
    assert facts.meeting_link == link
    assert facts.interview_date == "2026-12-01"
    assert facts.interview_time == "10:00"
    assert facts.interview_at is None  # no timezone stated, so no instant is invented


def test_extracts_assessment_link_deadline_and_reference() -> None:
    facts = extract(
        "Your application",
        "Thanks for your application for the role of ML Engineer. Reference number: "
        "ABC-77123. Please complete the test before November 30th: "
        "https://www.hackerrank.com/test/abc123/login",
        "Acme Careers <careers@acme.io>",
        RECEIVED,
    )
    assert facts.employer == "Acme"
    assert facts.job_title == "ML Engineer"
    assert facts.application_reference == "ABC-77123"
    assert facts.deadline == "2026-11-30"
    assert facts.assessment_link == "https://www.hackerrank.com/test/abc123/login"


def test_relative_deadline_needs_a_received_time() -> None:
    body = "Please complete the coding challenge within 3 days."
    assert extract("Test", body, "x@hackerrank.com", RECEIVED).deadline == "2026-11-24"
    assert extract("Test", body, "x@hackerrank.com", None).deadline is None


def test_unknown_values_are_none_not_guesses() -> None:
    facts = extract(
        "Hello", "Can we talk on 04/05/2026 about the interview?", "Jane <jane@hooli.com>"
    )
    assert facts.interview_date is None  # April or May? Ambiguous, so unknown.
    assert facts.employer is None  # a person's display name is not an employer
    assert facts.job_title is None
    assert facts.application_reference is None
    assert facts.meeting_link is None


def test_date_formats_parsed_without_dateutil() -> None:
    text = "on 28 Nov 2026, Dec 3rd 2026, 2026-12-05, 25/12/2026 and Monday, 7 December"
    values = [value.isoformat() for _, _, value in find_dates(text, RECEIVED)]
    assert values == ["2026-11-28", "2026-12-03", "2026-12-05", "2026-12-25", "2026-12-07"]
    assert [v.isoformat() for _, _, v in find_dates("Monday, 7 December", None)] == []


# --------------------------------------------------------------------------------------
# Matching and suggestions
# --------------------------------------------------------------------------------------


def _ingest(session: Session, parts: tuple[str, str, str], **kwargs):
    subject, body, sender = parts
    return EmailTrackingService(session).ingest_raw(make_eml(subject, body, sender, **kwargs))


def test_confident_match_is_auto_linked(session: Session, profile: CandidateProfile) -> None:
    application = make_application(session, profile)
    make_application(
        session,
        profile,
        company="Globex",
        title="Data Analyst",
        url="https://globex.example/jobs/9",
    )
    result = _ingest(session, REJECTION)
    assert result.outcome == "created"
    message = result.message
    assert message is not None
    assert message.match_state == "auto_linked"
    assert message.application_id == application.id
    assert message.match_confidence >= 0.75
    assert message.match_candidates[0]["application_id"] == application.id


def test_ambiguous_match_goes_to_review_with_candidates(
    session: Session, profile: CandidateProfile
) -> None:
    first = make_application(session, profile, title="Backend Engineer")
    second = make_application(session, profile, title="Backend Engineer, Payments")
    result = _ingest(
        session,
        (
            "Your application to Acme Technologies",
            "Thank you for your interest in Acme Technologies. Unfortunately we will not be "
            "moving forward.",
            "Acme Technologies Recruiting <no-reply@greenhouse.io>",
        ),
    )
    message = result.message
    assert message is not None
    assert message.match_state == "needs_review"
    assert message.application_id is None
    ids = {candidate["application_id"] for candidate in message.match_candidates}
    assert {first.id, second.id} <= ids
    assert all(candidate["signals"] for candidate in message.match_candidates)
    assert result.suggestion is None  # nothing is proposed until the user picks one


def test_no_candidate_is_unmatched(session: Session, profile: CandidateProfile) -> None:
    make_application(
        session, profile, company="Globex", title="Data Analyst", url="https://globex.example/j/1"
    )
    result = _ingest(session, CONFIRMATION)
    assert result.message is not None
    assert result.message.match_state == "unmatched"
    assert result.message.match_candidates == []


def test_duplicate_message_ids_are_stored_once(session: Session, profile: CandidateProfile) -> None:
    make_application(session, profile)
    raw = make_eml(*REJECTION, message_id="<same-id@mail.example>")
    service = EmailTrackingService(session)
    assert service.ingest_raw(raw).outcome == "created"
    assert service.ingest_raw(raw).outcome == "duplicate"
    assert len(session.scalars(select(EmailMessage)).all()) == 1
    assert len(session.scalars(select(StatusSuggestion)).all()) == 1


def test_not_job_related_mail_is_not_stored(session: Session, profile: CandidateProfile) -> None:
    result = _ingest(
        session, ("Weekend sale", "40% off everything this weekend.", "news@shop.example")
    )
    assert result.outcome == "skipped_not_job_related"
    assert session.scalars(select(EmailMessage)).all() == []


def test_suggestions_are_never_applied_automatically(
    session: Session, profile: CandidateProfile
) -> None:
    application = make_application(session, profile)
    result = _ingest(session, REJECTION)
    suggestion = result.suggestion
    assert suggestion is not None
    assert (suggestion.field, suggestion.suggested_value, suggestion.state) == (
        "outcome",
        "rejected",
        "pending",
    )
    session.refresh(application)
    assert application.outcome is Outcome.PENDING
    assert application.status is ApplicationStatus.SUBMITTED


def test_accepting_a_rejection_sets_the_outcome(
    session: Session, profile: CandidateProfile
) -> None:
    application = make_application(session, profile)
    suggestion = _ingest(session, REJECTION).suggestion
    assert suggestion is not None
    result = EmailTrackingService(session).accept_suggestion(suggestion.id)
    assert result.suggestion.state == "accepted"
    assert application.outcome is Outcome.REJECTED
    assert "greenhouse.io" in application.notes


def test_accepting_a_confirmation_uses_legal_transitions_with_evidence(
    session: Session, profile: CandidateProfile
) -> None:
    application = make_application(session, profile, status=ApplicationStatus.SUBMITTED)
    suggestion = _ingest(session, CONFIRMATION).suggestion
    assert suggestion is not None
    assert (suggestion.field, suggestion.suggested_value) == ("status", "CONFIRMED")

    EmailTrackingService(session).accept_suggestion(suggestion.id)
    assert application.status is ApplicationStatus.CONFIRMED
    evidence = application.confirmation_evidence or ""
    assert "greenhouse.io" in evidence
    assert "Thank you for applying to Acme Technologies" in evidence
    assert datetime.now(UTC).date().isoformat() in evidence
    last_event = application.events[-1]
    assert last_event.to_status is ApplicationStatus.CONFIRMED
    assert last_event.actor == "user"


def test_an_illegal_transition_is_reported_not_forced(
    session: Session, profile: CandidateProfile
) -> None:
    application = make_application(session, profile, status=ApplicationStatus.SHORTLISTED)
    message = _ingest(session, CONFIRMATION).message
    assert message is not None
    _, suggestion = EmailTrackingService(session).link_message(message.id, application.id)
    assert suggestion is not None
    with pytest.raises(SuggestionNotApplicable, match="SHORTLISTED"):
        EmailTrackingService(session).accept_suggestion(suggestion.id)
    assert suggestion.state == "pending"
    assert application.status is ApplicationStatus.SHORTLISTED


def test_outcome_regression_is_refused(session: Session, profile: CandidateProfile) -> None:
    application = make_application(session, profile)
    application.outcome = Outcome.OFFER
    session.flush()
    message = _ingest(
        session,
        (
            "Interview invitation - Backend Engineer at Acme Technologies",
            "We would like to invite you to an interview for the Backend Engineer role.",
            "Acme Technologies Recruiting <no-reply@greenhouse.io>",
        ),
    ).message
    assert message is not None
    _, suggestion = EmailTrackingService(session).link_message(message.id, application.id)
    assert suggestion is not None
    with pytest.raises(SuggestionNotApplicable, match="further along"):
        EmailTrackingService(session).accept_suggestion(suggestion.id)
    assert application.outcome is Outcome.OFFER


def _unknown_attempt(
    session: Session, profile: CandidateProfile, application: Application
) -> SubmissionAttempt:
    run = AutoApplyRun(profile_id=profile.id, targets={}, unknown_count=1)
    session.add(run)
    session.flush()
    attempt = SubmissionAttempt(
        autoapply_run_id=run.id,
        job_id=application.job_id,
        application_id=application.id,
        target_key="greenhouse_browser",
        state=SubmissionState.OUTCOME_UNKNOWN,
        idempotency_key=f"key-{application.id}",
    )
    session.add(attempt)
    session.flush()
    return attempt


def test_outcome_unknown_attempt_is_confirmed_only_on_accept(
    session: Session, profile: CandidateProfile
) -> None:
    application = make_application(session, profile, status=ApplicationStatus.APPROVED)
    attempt = _unknown_attempt(session, profile, application)

    suggestion = _ingest(session, CONFIRMATION).suggestion
    assert suggestion is not None
    assert suggestion.attempt_id == attempt.id
    session.refresh(attempt)
    assert attempt.state is SubmissionState.OUTCOME_UNKNOWN
    assert attempt.confirmation_id == ""

    EmailTrackingService(session).accept_suggestion(suggestion.id)
    session.flush()
    session.refresh(attempt)
    assert attempt.state is SubmissionState.SUBMITTED_CONFIRMED
    assert attempt.confirmation_id.startswith("email-")
    assert "greenhouse.io" in attempt.confirmation_evidence
    assert application.status is ApplicationStatus.CONFIRMED
    assert application.submitted_by == "joborbit-autoapply/greenhouse_browser"
    run = session.get(AutoApplyRun, attempt.autoapply_run_id)
    assert run is not None
    assert (run.confirmed_count, run.unknown_count) == (1, 0)


def test_privacy_no_body_stored_and_snippet_redacted(
    session: Session, profile: CandidateProfile
) -> None:
    make_application(session, profile)
    sentinel = "SENTINEL-END-OF-BODY"
    body = (
        REJECTION[1]
        + " Reach me at test@example.com or +91 98765 43210, Test Candidate. "
        + "Filler sentence about the hiring process. " * 30
        + sentinel
    )
    message = _ingest(session, (REJECTION[0], body, REJECTION[2])).message
    assert message is not None
    assert len(message.snippet) <= 500
    assert "test@example.com" not in message.snippet
    assert "98765" not in message.snippet
    assert "Test Candidate" not in message.snippet
    for column in EmailMessage.__table__.columns:
        value = getattr(message, column.key)
        assert sentinel not in json.dumps(value, default=str), column.key


# --------------------------------------------------------------------------------------
# API: manual ingest, review inbox, accept
# --------------------------------------------------------------------------------------


def test_api_ingest_review_link_and_accept(
    client: TestClient, session: Session, profile: CandidateProfile
) -> None:
    first = make_application(session, profile, title="Backend Engineer")
    make_application(session, profile, title="Backend Engineer, Payments")
    session.commit()
    raw = make_eml(
        "Your application to Acme Technologies",
        "Thank you for your interest in Acme Technologies. Unfortunately we will not be "
        "moving forward.",
        "Acme Technologies Recruiting <no-reply@greenhouse.io>",
    )
    response = client.post("/api/email/ingest", json={"raw": raw})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["category"] == "rejection"
    assert body["message"]["match_state"] == "needs_review"
    message_id = body["message"]["id"]

    review = client.get("/api/email/messages", params={"match_state": "needs_review"}).json()
    assert review["total"] == 1

    linked = client.post(
        f"/api/email/messages/{message_id}/link", json={"application_id": first.id}
    )
    assert linked.status_code == 200, linked.text
    suggestion_id = linked.json()["suggestion"]["id"]

    pending = client.get("/api/email/suggestions").json()
    assert [item["id"] for item in pending] == [suggestion_id]
    assert pending[0]["current_outcome"] == "pending"

    accepted = client.post(f"/api/email/suggestions/{suggestion_id}/accept")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["suggestion"]["state"] == "accepted"
    again = client.post(f"/api/email/suggestions/{suggestion_id}/accept")
    assert again.status_code == 409


def test_api_dismiss_leaves_the_application_alone(
    client: TestClient, session: Session, profile: CandidateProfile
) -> None:
    application = make_application(session, profile)
    session.commit()
    body = client.post("/api/email/ingest", json={"raw": make_eml(*REJECTION)}).json()
    suggestion_id = body["suggestion"]["id"]
    response = client.post(f"/api/email/suggestions/{suggestion_id}/dismiss")
    assert response.status_code == 200
    session.expire_all()
    assert session.get(Application, application.id).outcome is Outcome.PENDING


def test_api_illegal_accept_returns_409_with_reason(
    client: TestClient, session: Session, profile: CandidateProfile
) -> None:
    application = make_application(session, profile, status=ApplicationStatus.READY_FOR_REVIEW)
    session.commit()
    body = client.post("/api/email/ingest", json={"raw": make_eml(*CONFIRMATION)}).json()
    message_id = body["message"]["id"]
    link = client.post(
        f"/api/email/messages/{message_id}/link", json={"application_id": application.id}
    )
    suggestion_id = link.json()["suggestion"]["id"]
    response = client.post(f"/api/email/suggestions/{suggestion_id}/accept")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "suggestion_not_applicable"
    assert "READY_FOR_REVIEW" in response.json()["error"]["message"]


# --------------------------------------------------------------------------------------
# Gmail OAuth and sync against a mocked transport
# --------------------------------------------------------------------------------------


class FakeGoogle:
    """A recording stand-in for Google's OAuth and Gmail endpoints."""

    def __init__(
        self, messages: dict[str, str] | None = None, granted_scope: str = GMAIL_READONLY_SCOPE
    ):
        self.messages = messages or {}
        self.granted_scope = granted_scope
        self.requests: list[httpx.Request] = []
        self.revoked: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url.startswith(gmail_module.TOKEN_ENDPOINT):
            form = parse_qs(request.content.decode())
            if form["grant_type"] == ["authorization_code"]:
                assert form["code_verifier"][0]
                return httpx.Response(
                    200,
                    json={
                        "access_token": "ya29.test-access",
                        "refresh_token": "1//test-refresh-token",
                        "expires_in": 3599,
                        "scope": self.granted_scope,
                        "token_type": "Bearer",
                    },
                )
            return httpx.Response(200, json={"access_token": "ya29.refreshed", "expires_in": 3599})
        if url.startswith(gmail_module.REVOKE_ENDPOINT):
            self.revoked.append(parse_qs(request.content.decode())["token"][0])
            return httpx.Response(200)
        if url.startswith(f"{gmail_module.GMAIL_API}/profile"):
            return httpx.Response(200, json={"emailAddress": "test@example.com"})
        if request.url.path.endswith("/messages"):
            return httpx.Response(
                200,
                json={"messages": [{"id": key, "threadId": f"t-{key}"} for key in self.messages]},
            )
        if "/messages/" in request.url.path:
            key = request.url.path.rsplit("/", 1)[-1]
            raw = base64.urlsafe_b64encode(self.messages[key].encode()).decode().rstrip("=")
            return httpx.Response(
                200,
                json={
                    "id": key,
                    "raw": raw,
                    "internalDate": str(int(datetime.now(UTC).timestamp() * 1000)),
                },
            )
        return httpx.Response(404)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def _connect(session: Session, google: FakeGoogle) -> tuple[GmailClient, EmailAccount]:
    client = GmailClient(get_settings(), transport=google.transport())
    url = client.authorization_url()
    state = parse_qs(urlsplit(url).query)["state"][0]
    account = client.complete_authorization(session, "auth-code", state)
    return client, account


def test_oauth_url_requests_only_readonly_scope_with_pkce(tracking_enabled: None) -> None:
    url = GmailClient(get_settings()).authorization_url()
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == gmail_module.AUTH_ENDPOINT
    assert query["scope"] == [GMAIL_READONLY_SCOPE]
    assert query["code_challenge_method"] == ["S256"]
    assert len(query["code_challenge"][0]) == 43
    assert len(query["state"][0]) >= 32
    assert query["redirect_uri"] == [
        f"http://127.0.0.1:{get_settings().api_port}/api/email/gmail/callback"
    ]
    assert query["response_type"] == ["code"]
    assert "include_granted_scopes" not in query


def test_connect_refused_when_disabled_or_unconfigured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = client.get("/api/email/gmail/connect")
    assert response.status_code == 409
    assert "JA_EMAIL_TRACKING_ENABLED" in response.json()["error"]["message"]

    monkeypatch.setenv("JA_EMAIL_TRACKING_ENABLED", "true")
    monkeypatch.setenv("JA_GMAIL_CLIENT_ID", "")
    reset_settings_cache()
    response = client.get("/api/email/gmail/connect")
    assert response.status_code == 409
    assert "JA_GMAIL_CLIENT_ID" in response.json()["error"]["message"]


def test_callback_stores_refresh_token_in_secret_store_not_db(
    tracking_enabled: None, client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    google = FakeGoogle()
    monkeypatch.setattr(
        "app.api.routes.email._gmail",
        lambda settings: GmailClient(settings, transport=google.transport()),
    )
    url = client.get("/api/email/gmail/connect").json()["auth_url"]
    state = parse_qs(urlsplit(url).query)["state"][0]

    forged = client.get("/api/email/gmail/callback", params={"code": "c", "state": "forged"})
    assert forged.status_code == 400

    response = client.get("/api/email/gmail/callback", params={"code": "auth-code", "state": state})
    assert response.status_code == 200, response.text
    assert "connected" in response.text.lower()
    replay = client.get("/api/email/gmail/callback", params={"code": "auth-code", "state": state})
    assert replay.status_code == 400  # a state value works once

    session.expire_all()
    account = session.scalars(select(EmailAccount)).one()
    assert account.scopes == [GMAIL_READONLY_SCOPE]
    assert SecretStore(get_settings()).get(refresh_token_key(account.id)) == "1//test-refresh-token"
    for column in EmailAccount.__table__.columns:
        assert "test-refresh-token" not in str(getattr(account, column.key))

    status = client.get("/api/email/status").json()
    assert status["connected"] is True
    assert status["scope"] == GMAIL_READONLY_SCOPE


def test_a_broader_granted_scope_is_refused_and_revoked(
    tracking_enabled: None, session: Session
) -> None:
    google = FakeGoogle(granted_scope=f"{GMAIL_READONLY_SCOPE} https://mail.google.com/")
    with pytest.raises(GmailError, match="different set of permissions"):
        _connect(session, google)
    assert google.revoked == ["1//test-refresh-token"]
    assert session.scalars(select(EmailAccount)).all() == []


def test_sync_keeps_only_job_related_and_only_reads(
    tracking_enabled: None, session: Session, profile: CandidateProfile
) -> None:
    make_application(session, profile)
    google = FakeGoogle(
        {
            "m1": make_eml(*CONFIRMATION),
            "m2": make_eml("Weekend sale", "40% off everything this weekend.", "news@shop.example"),
            "m3": make_eml(*REJECTION),
        }
    )
    client, account = _connect(session, google)
    report = client.sync(session, account)

    assert (report.listed, report.fetched, report.kept, report.skipped_not_job_related) == (
        3,
        3,
        2,
        1,
    )
    stored = session.scalars(select(EmailMessage)).all()
    assert {row.provider_message_id for row in stored} == {"m1", "m3"}
    assert account.last_sync_at is not None

    gmail_requests = [r for r in google.requests if r.url.host == "gmail.googleapis.com"]
    assert gmail_requests
    assert all(r.method == "GET" for r in gmail_requests)
    forbidden = (
        "send",
        "modify",
        "trash",
        "delete",
        "batch",
        "labels",
        "drafts",
        "import",
        "insert",
    )
    assert not any(word in r.url.path.lower() for r in gmail_requests for word in forbidden)
    list_query = next(r for r in gmail_requests if r.url.path.endswith("/messages")).url.params["q"]
    assert "newer_than:30d" in list_query
    assert "-category:promotions" in list_query
    assert "from:greenhouse.io" in list_query

    # A second sync fetches nothing new: ids already stored are skipped before download.
    before = len(google.requests)
    again = client.sync(session, account)
    assert again.duplicates == 2
    fetched_again = [r for r in google.requests[before:] if "/messages/" in r.url.path]
    assert [r.url.path.rsplit("/", 1)[-1] for r in fetched_again] == ["m2"]


def test_sync_respects_the_message_cap(
    tracking_enabled: None, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JA_EMAIL_MAX_MESSAGES", "2")
    reset_settings_cache()
    google = FakeGoogle({f"m{i}": make_eml(*CONFIRMATION) for i in range(5)})
    client, account = _connect(session, google)
    assert len(client.list_message_ids("token")) == 2


def test_disconnect_revokes_and_deletes_the_token(tracking_enabled: None, session: Session) -> None:
    google = FakeGoogle()
    client, account = _connect(session, google)
    store = SecretStore(get_settings())
    assert store.get(refresh_token_key(account.id))
    assert client.disconnect(session, account) is True
    assert google.revoked == ["1//test-refresh-token"]
    assert store.get(refresh_token_key(account.id)) is None
    assert account.status == "disconnected"
    with pytest.raises(GmailError):
        client.sync(session, account)


def test_delete_data_removes_messages_suggestions_and_tokens(
    tracking_enabled: None,
    client: TestClient,
    session: Session,
    profile: CandidateProfile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_application(session, profile)
    google = FakeGoogle({"m1": make_eml(*REJECTION)})
    gmail_client, account = _connect(session, google)
    gmail_client.sync(session, account)
    account_id = account.id
    session.commit()
    assert session.scalars(select(StatusSuggestion)).all()
    monkeypatch.setattr(
        "app.api.routes.email._gmail",
        lambda settings: GmailClient(settings, transport=google.transport()),
    )

    response = client.delete("/api/email/data")
    assert response.status_code == 200, response.text
    assert response.json() == {"messages": 1, "suggestions": 1, "accounts": 1}
    session.expire_all()
    assert session.scalars(select(EmailMessage)).all() == []
    assert session.scalars(select(StatusSuggestion)).all() == []
    assert session.scalars(select(EmailAccount)).all() == []
    assert SecretStore(get_settings()).get(refresh_token_key(account_id)) is None


# --------------------------------------------------------------------------------------
# Demo mode
# --------------------------------------------------------------------------------------

EMAIL_ROUTES: list[tuple[str, str, Callable[[], dict]]] = [
    ("GET", "/api/email/status", dict),
    ("GET", "/api/email/gmail/connect", dict),
    ("GET", "/api/email/gmail/callback?code=x&state=y", dict),
    ("POST", "/api/email/sync", dict),
    ("POST", "/api/email/ingest", lambda: {"json": {"raw": make_eml(*CONFIRMATION)}}),
    ("GET", "/api/email/messages", dict),
    ("GET", "/api/email/suggestions", dict),
    ("POST", "/api/email/suggestions/1/accept", dict),
    ("POST", "/api/email/suggestions/1/dismiss", dict),
    ("POST", "/api/email/messages/1/link", lambda: {"json": {"application_id": 1}}),
    ("POST", "/api/email/messages/1/dismiss", dict),
    ("POST", "/api/email/disconnect", dict),
    ("DELETE", "/api/email/data", dict),
]


def test_demo_mode_refuses_every_email_route(engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JA_DEMO_MODE", "true")
    monkeypatch.setenv("JA_EMAIL_TRACKING_ENABLED", "true")
    reset_settings_cache()
    from app.main import create_app

    with TestClient(create_app()) as demo:
        for method, path, extra in EMAIL_ROUTES:
            response = demo.request(method, path, **extra())
            assert response.status_code == 403, (method, path, response.text)
            if "callback" not in path:
                assert response.json()["error"]["code"] == "demo_mode_email_tracking_blocked"
    reset_settings_cache()


def test_every_email_route_is_covered_by_the_demo_test() -> None:
    from app.api.routes.email import router

    declared = {(method, route.path) for route in router.routes for method in route.methods}  # type: ignore[attr-defined]
    tested = {
        (method, path.split("?")[0].replace("/1/", "/{x}/")) for method, path, _ in EMAIL_ROUTES
    }
    normalised = {
        (method, path.replace("{suggestion_id}", "{x}").replace("{message_id}", "{x}"))
        for method, path in declared
    }
    assert normalised == tested


def test_received_after_application_scores_higher(
    session: Session, profile: CandidateProfile
) -> None:
    """An email that predates the application cannot be a response to it."""
    make_application(session, profile, days_ago=1)
    result = _ingest(session, REJECTION, date=datetime.now(UTC) - timedelta(days=30))
    assert result.message is not None
    assert result.message.match_state != "auto_linked"
