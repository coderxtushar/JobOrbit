"""End-to-end tests for the submission framework and the auto-apply orchestrator.

Everything here runs against a real HTTP application server on loopback
(:mod:`tests.support.application_server`), not a mock. The requests are real, the
multipart upload is real, the confirmation identifier is real, and the failure modes are
produced by the server rather than asserted about. That is the only way to verify a
submission pipeline without applying to somebody's actual job.

The two cases worth reading first are
``test_a_dropped_commit_is_recorded_as_unknown_not_submitted`` and
``test_an_unknown_outcome_is_never_retried``: together they are the guarantee that a lost
response never becomes either a fabricated submission or a duplicate one.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    AnswerProvenance,
    Application,
    ApplicationAnswer,
    ApplicationArtifact,
    ApplicationStatus,
    AutoApplyRun,
    BatchStatus,
    CandidateProfile,
    Job,
    JobMatch,
    Resume,
    ResumeVariant,
    SourceName,
    SubmissionAttempt,
    SubmissionState,
)
from app.db.repositories import SavedAnswerRepository
from app.services.autoapply import AutoApplyService, AutoApplyTargets, idempotency_key, preview
from app.submission import (
    AnswerValue,
    CandidateIdentity,
    FieldKind,
    FormField,
    FormSpec,
    ResumeDocument,
    adapter_for_job,
    all_submission_adapters,
    fill_form,
    get_submission_adapter,
    supported_targets,
    target_for_url,
    validate_document,
)
from app.submission.base import CredentialOwner
from app.submission.credentials import CredentialRefused, describe_all, resolve
from app.submission.local_test import (
    BASE_URL_ENV,
    TOKEN_ENV,
    LocalTestSubmissionAdapter,
    NonLoopbackTarget,
    build_local_test_adapter,
)
from tests.conftest import persist_job
from tests.support.application_server import (
    DEFAULT_FORM,
    SYNTHETIC_TOKEN,
    ServerBehaviour,
    TestApplicationServer,
)

# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------


@pytest.fixture
def ats_server() -> Iterator[TestApplicationServer]:
    with TestApplicationServer() as server:
        yield server


@pytest.fixture
def configured(
    ats_server: TestApplicationServer, monkeypatch: pytest.MonkeyPatch
) -> TestApplicationServer:
    monkeypatch.setenv(BASE_URL_ENV, ats_server.base_url)
    monkeypatch.setenv(TOKEN_ENV, SYNTHETIC_TOKEN)
    return ats_server


@pytest.fixture
def verified_profile(session: Session, profile: CandidateProfile) -> CandidateProfile:
    """A profile where the sensitive answers are confirmed, so dispatch is reachable.

    Without these the orchestrator correctly blocks every application on an unanswered
    legal question, which is the behaviour several tests below assert in its own right.
    """
    profile.work_authorization = "Authorised to work in India"
    profile.requires_sponsorship = False
    profile.notice_period_days = 0
    profile.open_to_relocation = True
    profile.salary_expectation_min = 600000
    profile.salary_expectation_max = 900000
    profile.phone = "+91 90000 00000"
    profile.graduation_date = "2026-06"
    profile.education = [
        {"degree": "B.Tech Computer Science", "institution": "Test Institute", "end_year": "2026"}
    ]
    profile.links = ["https://github.com/test-candidate"]

    # The provider asks two things no profile field answers: a Yes/No work-authorization
    # radio whose options its own free-text answer cannot satisfy, and an attestation tick
    # box. Both are answered once in the bank, which is the product's documented loop.
    bank = SavedAnswerRepository(session)
    bank.upsert(
        profile_id=profile.id,
        question_key="work_authorization",
        question="Are you authorised to work in this country?",
        answer="Yes",
        provenance=AnswerProvenance.USER_ENTERED,
        is_sensitive=True,
    )
    bank.upsert(
        profile_id=profile.id,
        question_key="accept_terms",
        question="I confirm the information given is accurate",
        answer="Yes",
        provenance=AnswerProvenance.USER_ENTERED,
        is_sensitive=True,
    )

    resume = Resume(
        profile_id=profile.id,
        label="base",
        original_filename="resume.pdf",
        stored_path="var/resumes/test.pdf",
        content_type="application/pdf",
        file_size_bytes=120,
        sha256="0" * 64,
        extracted_text="Backend developer with Python and FastAPI experience.",
        is_primary=True,
    )
    session.add(resume)
    session.flush()
    session.add(
        ResumeVariant(
            resume_id=resume.id,
            name="general",
            job_family="backend",
            content="Test Candidate\nBackend developer. Python, FastAPI, PostgreSQL.",
            emphasised_skills=["python", "fastapi"],
        )
    )
    session.commit()
    return profile


def _verified(value: str) -> AnswerValue:
    return AnswerValue(value=value, provenance=AnswerProvenance.PROFILE_VERIFIED)


def _complete_answers() -> dict[str, AnswerValue]:
    return {
        "work_authorization": _verified("Yes"),
        "notice_period": _verified("Immediate"),
        "accept_terms": _verified("Yes"),
    }


def _job(session: Session, server: TestApplicationServer, key: str, **overrides) -> Job:
    """A job whose application form is served by the loopback test server.

    The URL is written after normalization on purpose: ``url_safety`` rejects loopback
    addresses on import, which is correct for a listing arriving from a job board and
    exactly wrong for a form this project is hosting itself.
    """
    defaults = {
        "source": SourceName.GREENHOUSE,
        "external_id": f"TS-{key}",
        "title": "Backend Developer",
        "company": f"Testcorp {key}",
    }
    defaults.update(overrides)
    job = persist_job(session, **defaults)
    job.url = f"{server.base_url}/api/jobs/{key}/form"
    session.flush()
    return job


def _application(
    session: Session, job: Job, profile: CandidateProfile, *, complete: bool = True
) -> Application:
    """Build a prepared application with answers and a resume artifact already snapshotted."""
    application = Application(
        job_id=job.id,
        profile_id=profile.id,
        status=ApplicationStatus.READY_FOR_REVIEW,
        platform=SourceName.GREENHOUSE,
    )
    session.add(application)
    session.flush()

    answers = [
        ("work_authorization", "Are you authorised to work?", "Yes", True),
        ("notice_period", "Notice period", "Immediate", True),
        ("accept_terms", "I confirm the information is accurate", "Yes", True),
    ]
    for key, question, value, sensitive in answers:
        session.add(
            ApplicationAnswer(
                application_id=application.id,
                question=question,
                question_key=key,
                answer=value if complete else "",
                provenance=(
                    AnswerProvenance.PROFILE_VERIFIED
                    if complete
                    else AnswerProvenance.NEEDS_USER_INPUT
                ),
                is_sensitive=sensitive,
                requires_user_input=not complete,
            )
        )

    content = f"Resume for {job.company}"
    session.add(
        ApplicationArtifact(
            application_id=application.id,
            kind="resume",
            label="general",
            content=content,
            content_sha256=hashlib.sha256(content.encode()).hexdigest(),
            byte_size=len(content),
        )
    )
    session.flush()
    session.refresh(application)
    return application


# --------------------------------------------------------------------------------------
# Milestone 1 — platform feasibility is read from the adapters, never asserted in prose
# --------------------------------------------------------------------------------------


def test_no_real_platform_reports_submission_as_supported() -> None:
    """The central guarantee: the matrix is derived, so documentation cannot drift from it."""
    probe = Job(title="", company="", url="")
    for adapter in all_submission_adapters():
        if adapter.target.key == "local_test":
            continue
        report = adapter.check_capability(probe)
        assert report.supported is False, adapter.target.key
        assert len(report.reason) > 60, f"{adapter.target.key} needs a real reason"


def test_submission_is_switched_off_entirely_in_a_default_installation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(BASE_URL_ENV, raising=False)
    assert supported_targets() == frozenset()
    assert build_local_test_adapter() is None


def test_the_only_supported_target_is_the_local_test_server(
    configured: TestApplicationServer,
) -> None:
    assert supported_targets() == frozenset({"local_test"})


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.linkedin.com/jobs/view/1", "linkedin"),
        ("https://in.indeed.com/viewjob?jk=1", "indeed"),
        ("https://www.naukri.com/job-listings-1", "naukri"),
        ("https://wellfound.com/jobs/1", "wellfound"),
        ("https://boards.greenhouse.io/acme/jobs/1", "greenhouse"),
        ("https://jobs.lever.co/acme/1", "lever"),
        ("https://jobs.ashbyhq.com/acme/1", "ashby"),
        ("https://jobs.smartrecruiters.com/Acme/1", "smartrecruiters"),
        ("https://apply.workable.com/acme/j/ABC/", "workable"),
        ("https://careers.unknown-company.test/jobs/1", "unknown"),
        ("", "unknown"),
    ],
)
def test_a_job_routes_to_the_provider_that_would_receive_it(url: str, expected: str) -> None:
    assert target_for_url(url).key == expected


def test_an_unrecognised_form_is_never_guessed_at() -> None:
    adapter = get_submission_adapter("unknown")
    report = adapter.check_capability(Job(title="", company="", url=""))
    assert report.supported is False
    assert "guess" in report.reason


def test_every_ats_provider_names_the_employer_as_the_credential_holder() -> None:
    """These five are unsupported because of a credential model, not a terms prohibition.

    Each documents a submission interface and each authenticates it with a credential the
    hiring company holds, so every row carries the provider's own wording. That is the
    distinction that would change if any of them published a candidate-side interface.
    """
    probe = Job(title="", company="", url="")
    for key in ("greenhouse", "lever", "ashby", "smartrecruiters", "workable"):
        report = get_submission_adapter(key).check_capability(probe)
        assert report.supported is False
        assert report.credential_owner is CredentialOwner.EMPLOYER, key
        assert report.documented_api is True
        assert report.evidence_url.startswith("http"), key
        assert len(report.evidence_quote) > 30, f"{key} needs the provider's own wording"


@pytest.mark.parametrize(
    ("key", "fragment"),
    [
        ("greenhouse", "Basic Auth"),
        ("lever", "Super Admin"),
        ("ashby", "candidatesWrite"),
        ("smartrecruiters", "Administrator access"),
        ("workable", "w_candidates"),
    ],
)
def test_each_ats_quote_names_the_credential_it_requires(key: str, fragment: str) -> None:
    report = get_submission_adapter(key).check_capability(Job(title="", company="", url=""))
    assert fragment in report.evidence_quote


def test_indeed_names_its_own_prohibition() -> None:
    report = get_submission_adapter("indeed").check_capability(Job(title="", company="", url=""))
    assert "automation" in report.evidence_quote.lower()
    assert report.credential_owner is CredentialOwner.APPROVED_VENDOR


# --------------------------------------------------------------------------------------
# Milestone 3 — the adapter must not be repurposed
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "base_url",
    [
        "https://boards.greenhouse.io",
        "http://example.com",
        "http://10.0.0.5:8000",
        "http://[2001:db8::1]:8000",
    ],
)
def test_the_submitting_adapter_refuses_a_non_loopback_target(base_url: str) -> None:
    """An adapter that really submits is the one that must not be aimed elsewhere."""
    with pytest.raises(NonLoopbackTarget):
        LocalTestSubmissionAdapter(base_url, "token")


def test_a_non_loopback_target_disables_the_adapter_rather_than_raising_at_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BASE_URL_ENV, "https://boards.greenhouse.io")
    assert build_local_test_adapter() is None
    assert supported_targets() == frozenset()


# --------------------------------------------------------------------------------------
# Milestone 5 — the form engine never invents a value
# --------------------------------------------------------------------------------------


def test_a_sensitive_field_refuses_an_ai_draft() -> None:
    spec = FormSpec(
        fields=(
            FormField(
                "work_authorization",
                "Authorised to work?",
                kind=FieldKind.RADIO,
                required=True,
                options=("Yes", "No"),
                question_key="work_authorization",
            ),
        )
    )
    filled = fill_form(
        spec,
        {"work_authorization": AnswerValue("Yes", AnswerProvenance.AI_DRAFT)},
    )
    assert not filled.is_complete
    assert "needs your confirmation" in filled.blocking[0]


def test_a_tick_box_is_never_set_from_a_generated_answer() -> None:
    spec = FormSpec(
        fields=(
            FormField(
                "accept", "I confirm this is accurate", kind=FieldKind.CHECKBOX, required=True
            ),
        )
    )
    filled = fill_form(spec, {"accept": AnswerValue("Yes", AnswerProvenance.AI_DRAFT)})
    assert not filled.is_complete
    assert "your own answer" in filled.blocking[0]


def test_an_answer_outside_the_offered_options_is_reported_not_coerced() -> None:
    spec = FormSpec(
        fields=(
            FormField(
                "auth",
                "Authorised?",
                kind=FieldKind.SELECT,
                required=True,
                options=("Yes", "No"),
                question_key="work_authorization",
                sensitive=False,
            ),
        )
    )
    filled = fill_form(spec, {"work_authorization": _verified("Yes, with a visa")})
    assert not filled.is_complete
    assert "not one of the options" in filled.blocking[0]


def test_a_conditionally_required_field_only_blocks_when_its_controller_is_set() -> None:
    spec = FormSpec(
        fields=(
            FormField("needs_sponsorship", "Need sponsorship?", kind=FieldKind.CHECKBOX),
            FormField("detail", "Describe it", required_when="needs_sponsorship"),
        )
    )
    without = fill_form(spec, {"needs_sponsorship": _verified("No")})
    assert without.is_complete

    with_it = fill_form(spec, {"needs_sponsorship": _verified("Yes")})
    assert not with_it.is_complete
    assert "Describe it" in with_it.blocking[0]


@pytest.mark.parametrize(
    ("filename", "size", "fragment"),
    [
        ("resume.exe", 100, "not an accepted format"),
        ("resume.pdf", 0, "is empty"),
        ("resume.pdf", 99_000_000, "over the"),
    ],
)
def test_a_document_is_validated_before_any_dispatch(
    filename: str, size: int, fragment: str
) -> None:
    assert fragment in validate_document(filename, size, max_bytes=5 * 1024 * 1024)


def test_an_unreadable_form_blocks_before_a_single_field_is_typed() -> None:
    filled = fill_form(FormSpec(human_required_reason="a CAPTCHA needs a person"), {})
    assert filled.blocking == ["a CAPTCHA needs a person"]
    assert filled.values == {}


# --------------------------------------------------------------------------------------
# Milestone 6 — confirmation, and the three ways an attempt can end
# --------------------------------------------------------------------------------------


def test_a_submission_is_confirmed_only_after_independent_verification(
    configured: TestApplicationServer, session: Session, profile: CandidateProfile
) -> None:
    job = _job(session, configured, "BE-1")
    adapter = adapter_for_job(job)
    identity = CandidateIdentity.from_profile(profile)
    form = adapter.prepare_fields(job, identity, _complete_answers())
    content = b"%PDF-1.4 resume"
    attachment = adapter.attach_resume(
        job, ResumeDocument("resume.pdf", content, hashlib.sha256(content).hexdigest())
    )

    dispatched = adapter.submit(job, form, attachment, idempotency_key="k-1")
    assert dispatched.state is SubmissionState.SUBMISSION_IN_PROGRESS
    assert dispatched.confirmation_id == "", "submit must never confirm on its own"

    verified = adapter.verify_submission(dispatched)
    assert verified.state is SubmissionState.SUBMITTED_CONFIRMED
    assert verified.confirmation_id.startswith("CONF-")

    stored = configured.state.confirmed()
    assert len(stored) == 1
    assert stored[0].resume_filename == "resume.pdf"
    assert stored[0].resume_bytes == len(content)


def test_a_dropped_commit_is_recorded_as_unknown_not_submitted(
    ats_server: TestApplicationServer,
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
    profile: CandidateProfile,
) -> None:
    """A provider that replies 200 and commits nothing must not produce a sent application."""
    ats_server.state.behaviour = ServerBehaviour(drop_finish=True)
    monkeypatch.setenv(BASE_URL_ENV, ats_server.base_url)
    monkeypatch.setenv(TOKEN_ENV, SYNTHETIC_TOKEN)

    job = _job(session, ats_server, "BE-2")
    adapter = adapter_for_job(job)
    form = adapter.prepare_fields(job, CandidateIdentity.from_profile(profile), _complete_answers())
    result = adapter.submit(
        job, form, adapter.attach_resume(job, ResumeDocument("r.pdf", b"x")), idempotency_key="k-2"
    )

    assert result.state is SubmissionState.OUTCOME_UNKNOWN
    assert result.confirmation_id == ""
    assert "no confirmation" in result.reason
    assert configured_confirmations(ats_server) == 0


def test_a_connection_reset_mid_commit_is_unknown_rather_than_failed(
    ats_server: TestApplicationServer,
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
    profile: CandidateProfile,
) -> None:
    """The browser-crash case: the request left, so whether it arrived is genuinely unknown."""
    ats_server.state.behaviour = ServerBehaviour(reset_finish=True)
    monkeypatch.setenv(BASE_URL_ENV, ats_server.base_url)
    monkeypatch.setenv(TOKEN_ENV, SYNTHETIC_TOKEN)

    job = _job(session, ats_server, "BE-3")
    adapter = adapter_for_job(job)
    form = adapter.prepare_fields(job, CandidateIdentity.from_profile(profile), _complete_answers())
    result = adapter.submit(
        job, form, adapter.attach_resume(job, ResumeDocument("r.pdf", b"x")), idempotency_key="k-3"
    )

    assert result.state is SubmissionState.OUTCOME_UNKNOWN
    assert "check" in result.reason.lower()


def configured_confirmations(server: TestApplicationServer) -> int:
    return len(server.state.confirmed())


@pytest.mark.parametrize(
    ("behaviour", "expected", "fragment"),
    [
        (ServerBehaviour(require_captcha=True), SubmissionState.BLOCKED_MISSING_INFO, "CAPTCHA"),
        (ServerBehaviour(require_mfa=True), SubmissionState.BLOCKED_MISSING_INFO, "one-time code"),
        (ServerBehaviour(reject_token=True), SubmissionState.REQUIRES_USER_ACTION, "expired"),
        (ServerBehaviour(fail_upload=True), SubmissionState.FAILED, "rejected the resume"),
        (
            ServerBehaviour(rate_limit_after=0, form=None),
            SubmissionState.SUBMISSION_IN_PROGRESS,
            "",
        ),
    ],
)
def test_each_provider_failure_mode_lands_in_the_right_state(
    ats_server: TestApplicationServer,
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
    profile: CandidateProfile,
    behaviour: ServerBehaviour,
    expected: SubmissionState,
    fragment: str,
) -> None:
    ats_server.state.behaviour = behaviour
    monkeypatch.setenv(BASE_URL_ENV, ats_server.base_url)
    monkeypatch.setenv(TOKEN_ENV, SYNTHETIC_TOKEN)

    job = _job(session, ats_server, "BE-4")
    adapter = adapter_for_job(job)
    identity = CandidateIdentity.from_profile(profile)
    form = adapter.prepare_fields(job, identity, _complete_answers())
    attachment = adapter.attach_resume(job, ResumeDocument("r.pdf", b"resume"))
    result = adapter.submit(job, form, attachment, idempotency_key="k-4")

    assert result.state is expected, result.reason
    if fragment:
        assert fragment.lower() in result.reason.lower()


def test_a_rate_limited_provider_is_retryable_rather_than_terminal(
    ats_server: TestApplicationServer,
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
    profile: CandidateProfile,
) -> None:
    ats_server.state.behaviour = ServerBehaviour(rate_limit_after=1)
    monkeypatch.setenv(BASE_URL_ENV, ats_server.base_url)
    monkeypatch.setenv(TOKEN_ENV, SYNTHETIC_TOKEN)

    adapter = get_submission_adapter("local_test")
    identity = CandidateIdentity.from_profile(profile)
    states = []
    for index in range(3):
        job = _job(session, ats_server, f"RL-{index}", external_id=f"RL-{index}")
        form = adapter.prepare_fields(job, identity, _complete_answers())
        attachment = adapter.attach_resume(job, ResumeDocument("r.pdf", b"resume"))
        states.append(adapter.submit(job, form, attachment, idempotency_key=f"rl-{index}").state)

    assert SubmissionState.FAILED in states, states
    from app.submission.states import RETRYABLE_STATES

    assert SubmissionState.FAILED in RETRYABLE_STATES
    assert SubmissionState.OUTCOME_UNKNOWN not in RETRYABLE_STATES


def test_the_provider_honours_an_idempotency_key_so_a_retry_cannot_duplicate(
    configured: TestApplicationServer, session: Session, profile: CandidateProfile
) -> None:
    job = _job(session, configured, "BE-5")
    adapter = adapter_for_job(job)
    identity = CandidateIdentity.from_profile(profile)
    form = adapter.prepare_fields(job, identity, _complete_answers())
    attachment = adapter.attach_resume(job, ResumeDocument("r.pdf", b"resume"))

    first = adapter.verify_submission(
        adapter.submit(job, form, attachment, idempotency_key="same-key")
    )
    second = adapter.verify_submission(
        adapter.submit(job, form, attachment, idempotency_key="same-key")
    )

    assert first.confirmation_id == second.confirmation_id
    assert len(configured.state.applications) == 1


# --------------------------------------------------------------------------------------
# Milestone 2 — the orchestrator
# --------------------------------------------------------------------------------------


def _score(session: Session, job: Job, profile: CandidateProfile, score: float = 90.0) -> None:
    session.add(
        JobMatch(
            job_id=job.id,
            profile_id=profile.id,
            total_score=score,
            band="high",
            confidence="high",
            evidence_coverage=1.0,
            filtered_out=False,
        )
    )
    session.flush()


def test_a_dry_run_prepares_everything_and_sends_nothing(
    configured: TestApplicationServer,
    session: Session,
    verified_profile: CandidateProfile,
    profile: CandidateProfile,
    engine,
) -> None:
    for index in range(3):
        job = _job(session, configured, f"DRY-{index}", external_id=f"DRY-{index}")
        _score(session, job, profile)
    session.commit()

    service = AutoApplyService()
    targets = AutoApplyTargets(dry_run=True, min_score=50, max_submissions=10)
    run = service.create_run(session, profile, targets)
    session.commit()
    finished = service.execute(run.id, targets)

    assert finished.confirmed_count == 0
    assert configured.state.applications == {}, "a dry run contacted the provider"
    states = {attempt.state for attempt in finished.attempts}
    assert states == {SubmissionState.READY_TO_SUBMIT}, states


def test_a_live_run_confirms_each_submission_and_records_the_resume_hash(
    configured: TestApplicationServer,
    session: Session,
    verified_profile: CandidateProfile,
    profile: CandidateProfile,
    engine,
) -> None:
    for index in range(4):
        job = _job(session, configured, f"LIVE-{index}", external_id=f"LIVE-{index}")
        _score(session, job, profile)
    session.commit()

    service = AutoApplyService()
    targets = AutoApplyTargets(dry_run=False, min_score=50, max_submissions=10)
    run = service.create_run(session, profile, targets)
    session.commit()
    finished = service.execute(run.id, targets)

    assert finished.confirmed_count == 4, finished.message
    assert len(configured.state.confirmed()) == 4
    for attempt in finished.attempts:
        assert attempt.state is SubmissionState.SUBMITTED_CONFIRMED
        assert attempt.confirmation_id
        assert len(attempt.resume_sha256) == 64


def test_a_confirmed_submission_moves_the_application_to_confirmed(
    configured: TestApplicationServer,
    session: Session,
    verified_profile: CandidateProfile,
    profile: CandidateProfile,
    engine,
) -> None:
    """The tracker must reflect a submission that genuinely happened and was verified."""
    job = _job(session, configured, "TRACK-1", external_id="TRACK-1")
    _score(session, job, profile)
    session.commit()

    service = AutoApplyService()
    targets = AutoApplyTargets(dry_run=False, min_score=50, max_submissions=5)
    run = service.create_run(session, profile, targets)
    session.commit()
    service.execute(run.id, targets)

    session.expire_all()
    row = session.query(Application).filter(Application.job_id == job.id).one()
    assert row.status is ApplicationStatus.CONFIRMED
    assert row.submitted_by.startswith("joborbit-autoapply/")
    assert row.confirmation_evidence


def test_the_submission_ceiling_is_honoured_even_when_more_jobs_are_eligible(
    configured: TestApplicationServer,
    session: Session,
    verified_profile: CandidateProfile,
    profile: CandidateProfile,
    engine,
) -> None:
    for index in range(6):
        job = _job(session, configured, f"CAP-{index}", external_id=f"CAP-{index}")
        _score(session, job, profile)
    session.commit()

    service = AutoApplyService()
    targets = AutoApplyTargets(dry_run=False, min_score=50, max_submissions=2)
    run = service.create_run(session, profile, targets)
    session.commit()
    finished = service.execute(run.id, targets)

    assert finished.confirmed_count == 2
    assert len(configured.state.confirmed()) == 2


def test_an_unsupported_platform_is_recorded_per_job_without_ending_the_run(
    configured: TestApplicationServer,
    session: Session,
    verified_profile: CandidateProfile,
    profile: CandidateProfile,
    engine,
) -> None:
    good = _job(session, configured, "MIX-1", external_id="MIX-1")
    linkedin = persist_job(
        session,
        source=SourceName.LINKEDIN,
        external_id="MIX-LI",
        title="Backend Developer",
        company="Mixed Co",
        url="https://www.linkedin.com/jobs/view/999",
    )
    _score(session, good, profile)
    _score(session, linkedin, profile)
    session.commit()

    service = AutoApplyService()
    targets = AutoApplyTargets(dry_run=False, min_score=50, max_submissions=5)
    run = service.create_run(session, profile, targets)
    session.commit()
    finished = service.execute(run.id, targets)

    assert finished.confirmed_count == 1
    assert finished.unsupported_count == 1
    unsupported = [a for a in finished.attempts if a.state is SubmissionState.UNSUPPORTED_PLATFORM]
    assert "User Agreement" in unsupported[0].detail


def test_a_run_of_more_than_a_hundred_jobs_completes_and_counts_honestly(
    configured: TestApplicationServer,
    session: Session,
    verified_profile: CandidateProfile,
    profile: CandidateProfile,
    engine,
) -> None:
    """Milestone 8's volume case, driven against the real server rather than simulated."""
    for index in range(120):
        job = _job(session, configured, f"BULK-{index}", external_id=f"BULK-{index}")
        _score(session, job, profile)
    session.commit()

    service = AutoApplyService()
    targets = AutoApplyTargets(dry_run=False, min_score=50, max_submissions=120)
    run = service.create_run(session, profile, targets)
    session.commit()
    finished = service.execute(run.id, targets)

    assert finished.eligible_count == 120
    assert finished.confirmed_count == 120, finished.message
    assert len(configured.state.confirmed()) == 120
    assert finished.status is BatchStatus.COMPLETED


def test_resuming_an_interrupted_run_does_not_submit_anything_twice(
    configured: TestApplicationServer,
    session: Session,
    verified_profile: CandidateProfile,
    profile: CandidateProfile,
    engine,
) -> None:
    for index in range(5):
        job = _job(session, configured, f"RESUME-{index}", external_id=f"RESUME-{index}")
        _score(session, job, profile)
    session.commit()

    service = AutoApplyService()
    targets = AutoApplyTargets(dry_run=False, min_score=50, max_submissions=5)
    run = service.create_run(session, profile, targets)
    session.commit()
    service.execute(run.id, targets)
    after_first = len(configured.state.confirmed())

    service.resume(session, run.id)
    session.commit()
    finished = service.execute(run.id, targets)

    assert after_first == 5
    assert len(configured.state.confirmed()) == 5, "a resumed run re-sent an application"
    assert finished.confirmed_count == 5


def test_the_same_job_cannot_be_attempted_twice_across_runs(
    configured: TestApplicationServer,
    session: Session,
    verified_profile: CandidateProfile,
    profile: CandidateProfile,
    engine,
) -> None:
    """The idempotency key is unique table-wide, so a second run skips an attempted job."""
    job = _job(session, configured, "DUP-1", external_id="DUP-1")
    _score(session, job, profile)
    session.commit()

    service = AutoApplyService()
    targets = AutoApplyTargets(dry_run=False, min_score=50, max_submissions=5)
    first = service.create_run(session, profile, targets)
    session.commit()
    service.execute(first.id, targets)

    second = service.create_run(session, profile, targets)
    session.commit()
    finished = service.execute(second.id, targets)

    assert len(configured.state.confirmed()) == 1
    assert finished.attempts == []


def test_the_database_refuses_a_second_attempt_with_the_same_idempotency_key(
    session: Session, profile: CandidateProfile
) -> None:
    job = persist_job(session, external_id="IDEM-1")
    run = AutoApplyRun(profile_id=profile.id, targets={})
    session.add(run)
    session.flush()
    key = idempotency_key(profile.id, job.id)
    session.add(SubmissionAttempt(autoapply_run_id=run.id, job_id=job.id, idempotency_key=key))
    session.flush()

    other = AutoApplyRun(profile_id=profile.id, targets={})
    session.add(other)
    session.flush()
    session.add(SubmissionAttempt(autoapply_run_id=other.id, job_id=job.id, idempotency_key=key))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_the_database_refuses_a_confirmation_id_without_a_confirmed_state(
    session: Session, profile: CandidateProfile
) -> None:
    """A confirmation identifier is meaningless unless the state says it was confirmed."""
    job = persist_job(session, external_id="CHECK-1")
    run = AutoApplyRun(profile_id=profile.id, targets={})
    session.add(run)
    session.flush()
    session.add(
        SubmissionAttempt(
            autoapply_run_id=run.id,
            job_id=job.id,
            idempotency_key="check-1",
            state=SubmissionState.FAILED,
            confirmation_id="CONF-FAKE",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_a_blocked_answer_stops_its_own_job_and_no_other(
    ats_server: TestApplicationServer,
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
    profile: CandidateProfile,
    engine,
) -> None:
    """Milestone 4's rule: a missing answer blocks one application, never the batch."""
    ats_server.state.behaviour = ServerBehaviour(
        form={
            "accepts_resume": True,
            "accepts_cover_letter": False,
            "fields": [
                {"name": "full_name", "label": "Full name", "kind": "text", "required": True},
                {"name": "email", "label": "Email", "kind": "email", "required": True},
                {
                    "name": "visa_status",
                    "label": "Describe your visa status",
                    "kind": "text",
                    "required": True,
                    "question_key": "work_authorization",
                    "sensitive": True,
                },
            ],
        }
    )
    monkeypatch.setenv(BASE_URL_ENV, ats_server.base_url)
    monkeypatch.setenv(TOKEN_ENV, SYNTHETIC_TOKEN)

    job = _job(session, ats_server, "BLOCK-1", external_id="BLOCK-1")
    adapter = adapter_for_job(job)
    identity = CandidateIdentity.from_profile(profile)
    form = adapter.prepare_fields(job, identity, {})
    assert not form.is_complete
    assert "Describe your visa status" in form.blocking[0]

    result = adapter.submit(
        job, form, adapter.attach_resume(job, ResumeDocument("r.pdf", b"x")), idempotency_key="b-1"
    )
    assert result.state is SubmissionState.BLOCKED_MISSING_INFO
    assert ats_server.state.applications == {}


def test_cancelling_a_run_stops_it_and_leaves_the_rest_unsent(
    configured: TestApplicationServer,
    session: Session,
    profile: CandidateProfile,
    engine,
) -> None:
    for index in range(4):
        job = _job(session, configured, f"CANCEL-{index}", external_id=f"CANCEL-{index}")
        _score(session, job, profile)
    session.commit()

    service = AutoApplyService()
    targets = AutoApplyTargets(dry_run=False, min_score=50, max_submissions=4)
    run = service.create_run(session, profile, targets)
    session.commit()
    service.request_cancel(session, run.id)
    session.commit()
    finished = service.execute(run.id, targets)

    assert finished.status is BatchStatus.CANCELLED
    assert len(configured.state.confirmed()) == 0


def test_preview_separates_eligible_from_submittable(
    configured: TestApplicationServer, session: Session, profile: CandidateProfile
) -> None:
    local = _job(session, configured, "PRE-1", external_id="PRE-1")
    remote = persist_job(
        session,
        source=SourceName.LINKEDIN,
        external_id="PRE-LI",
        title="Backend Developer",
        company="Preview Co",
        url="https://www.linkedin.com/jobs/view/1",
    )
    _score(session, local, profile)
    _score(session, remote, profile)
    session.commit()

    plan = preview(session, profile, AutoApplyTargets(min_score=50, max_submissions=10))
    assert plan.eligible == 2
    assert plan.submittable == 1
    assert "linkedin" in plan.unsupported_reasons


# --------------------------------------------------------------------------------------
# Milestone 4 — credentials
# --------------------------------------------------------------------------------------


def test_a_credential_never_appears_in_its_own_representation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JA_SUBMISSION_LOCAL_TEST_TOKEN", "super-secret-value-123")
    credential = resolve("local_test")
    assert credential.present
    for rendering in (repr(credential), str(credential), credential.redacted()):
        assert "super-secret-value-123" not in rendering
    assert credential.redacted().endswith("(22 chars)")


def test_a_password_or_cookie_credential_is_refused_outright() -> None:
    for provider in ("naukri_password", "linkedin_cookie", "indeed_session_id"):
        with pytest.raises(CredentialRefused):
            resolve(provider)


def test_the_diagnostics_report_never_contains_a_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JA_SUBMISSION_LOCAL_TEST_TOKEN", "another-secret")
    report = describe_all(["local_test", "greenhouse", "naukri_password"])
    assert "another-secret" not in "".join(report.values())
    assert report["greenhouse"] == "(not set)"
    assert report["naukri_password"].startswith("refused:")


# --------------------------------------------------------------------------------------
# Milestone 6 — the state model's own guarantees
# --------------------------------------------------------------------------------------


def test_exactly_one_state_counts_as_a_sent_application() -> None:
    from app.submission.states import counts_as_sent

    sent = [state for state in SubmissionState if counts_as_sent(state)]
    assert sent == [SubmissionState.SUBMITTED_CONFIRMED]


def test_an_unknown_outcome_is_never_retried() -> None:
    """Retrying an unknown outcome is how one application silently becomes two."""
    from app.submission.states import RETRYABLE_STATES, TERMINAL_STATES

    assert SubmissionState.OUTCOME_UNKNOWN in TERMINAL_STATES
    assert SubmissionState.OUTCOME_UNKNOWN not in RETRYABLE_STATES


def test_the_default_form_exercises_every_input_kind_the_engine_supports() -> None:
    """Guards the test server itself: a form with no checkbox would not test the tick rule."""
    kinds = {field["kind"] for field in DEFAULT_FORM["fields"]}
    assert {"text", "email", "radio", "textarea", "checkbox"} <= kinds
