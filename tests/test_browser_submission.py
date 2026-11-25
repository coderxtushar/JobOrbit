"""Browser submission, driven in a real headless Chrome against loopback copies of the
Greenhouse, Lever and Ashby forms (:mod:`tests.support.ats_forms`).

Nothing here is mocked below the adapter: the page is real HTML, the typing and clicking
are real, the file upload is real, and the server records what actually arrived. The
cases that matter most are the refusals — wrong job, CAPTCHA, a confirmation phrase that
was already on the page, an unanswered required question, an un-agreed declaration —
because each is a way an automated submission could misrepresent the candidate.

Skipped when Chrome cannot be started (for example on a machine without it).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.browser.dom import Pacing
from app.browser.labels import classify_label
from app.browser.session import BrowserUnavailable, BrowserWorker
from app.config import reset_settings_cache
from app.db.models import (
    AnswerProvenance,
    Application,
    ApplicationStatus,
    CandidateProfile,
    Job,
    JobMatch,
    Resume,
    SubmissionAttempt,
    SubmissionState,
)
from app.db.repositories import SavedAnswerRepository
from app.services.answer_bank import AnswerBankService
from app.services.autoapply import AutoApplyService, AutoApplyTargets
from app.submission.base import CandidateIdentity, ResumeDocument
from app.submission.browser_ats import (
    BrowserFormAdapter,
    ashby_apply_url,
    greenhouse_apply_url,
    lever_apply_url,
)
from app.submission.forms import AnswerValue
from app.submission.registry import ASHBY, GREENHOUSE, LEVER
from tests.conftest import make_pdf, persist_job
from tests.support.ats_forms import FormServer

IDENTITY = CandidateIdentity(
    full_name="Test Candidate",
    email="test@example.com",
    phone="+91 90000 00000",
    links=("https://www.linkedin.com/in/test-candidate", "https://github.com/test-candidate"),
)


@pytest.fixture(scope="module")
def browser(tmp_path_factory: pytest.TempPathFactory) -> Iterator[BrowserWorker]:
    try:
        worker = BrowserWorker(
            profile_dir=tmp_path_factory.mktemp("chrome-profile"),
            channel="chrome",
            headless=True,
            page_timeout_s=20,
        )
    except BrowserUnavailable as error:
        pytest.skip(f"Chrome is not available here: {error}")
    yield worker
    worker.close()


@pytest.fixture(scope="module")
def forms() -> Iterator[FormServer]:
    with FormServer() as server:
        yield server


@pytest.fixture
def resume(tmp_path: Path) -> ResumeDocument:
    content = make_pdf(["Test Candidate", "Backend developer. Python, FastAPI."])
    return ResumeDocument(filename="Test_Candidate_resume.pdf", content=content)


def _adapter(browser: BrowserWorker, provider: str, data_dir: Path) -> BrowserFormAdapter:
    target, url_for = {
        "greenhouse": (GREENHOUSE, greenhouse_apply_url),
        "lever": (LEVER, lever_apply_url),
        "ashby": (ASHBY, ashby_apply_url),
    }[provider]
    return BrowserFormAdapter(
        target,
        apply_url=url_for,
        browser=lambda: browser,
        data_dir=data_dir,
        pacing=Pacing(0, 0),
        confirmation_timeout_s=6,
    )


def _user(value: str) -> AnswerValue:
    return AnswerValue(value=value, provenance=AnswerProvenance.USER_ENTERED)


def _profile(value: str) -> AnswerValue:
    return AnswerValue(value=value, provenance=AnswerProvenance.PROFILE_VERIFIED)


def _answers(company: str) -> dict[str, AnswerValue]:
    return {
        "current_location": _user("Gurugram"),
        classify_label(f"Do you have a relative working at {company}?").key: _user("No"),
        classify_label("Are you willing to work from the office five days a week?").key: _user(
            "Yes"
        ),
        "work_authorization": _profile("Yes"),
        "requires_sponsorship": _profile("No"),
    }


def _apply(
    adapter: BrowserFormAdapter, job: Job, answers: dict[str, AnswerValue], resume: ResumeDocument
):
    adapter.inspect_application(job)
    form = adapter.prepare_fields(job, IDENTITY, answers)
    assert form.is_complete, form.blocking
    attachment = adapter.attach_resume(job, resume)
    assert attachment.ok, attachment.reason
    result = adapter.submit(job, form, attachment, idempotency_key=f"test-{job.title}-{id(job)}")
    if result.state is SubmissionState.SUBMISSION_IN_PROGRESS:
        result = adapter.verify_submission(result)
    adapter.release(job, keep_open=False)
    return result


def _received(forms: FormServer, job_id: str) -> list[dict]:
    return [item for item in forms.received if item["job_id"] == job_id]


# --------------------------------------------------------------------------------------
# Reading the three providers' forms
# --------------------------------------------------------------------------------------


def test_greenhouse_form_is_read_with_its_combobox_choices(browser, forms, tmp_path) -> None:
    job = Job(
        title="Backend Developer",
        company="acme",
        url=forms.url("greenhouse", "acme", "GH-READ", "Backend Developer"),
    )
    adapter = _adapter(browser, "greenhouse", tmp_path)
    spec = adapter.inspect_application(job)
    by_key = {field.question_key: field for field in spec.fields}
    assert spec.human_required_reason == ""
    assert spec.accepts_resume, "the input labelled only 'Attach' is the resume upload"
    assert {"first_name", "last_name", "email", "phone", "current_location", "linkedin"} <= set(
        by_key
    )
    relative = by_key[classify_label("Do you have a relative working at acme?").key]
    assert relative.required and relative.options == ("Yes", "No")
    adapter.release(job, keep_open=False)


def test_ashby_yes_no_buttons_are_questions_and_the_autofill_upload_is_ignored(
    browser, forms, tmp_path
) -> None:
    job = Job(
        title="Backend Developer",
        company="acme",
        url=forms.url("ashby", "acme", "AB-READ", "Backend Developer"),
    )
    adapter = _adapter(browser, "ashby", tmp_path)
    spec = adapter.inspect_application(job)
    by_key = {field.question_key: field for field in spec.fields}
    assert by_key["work_authorization"].options == ("Yes", "No")
    assert by_key["work_authorization"].required, "Ashby marks required with a class, not '*'"
    assert by_key["requires_sponsorship"].options == ("Yes", "No")
    assert spec.accepts_resume
    assert not any(field.kind.value == "file" for field in spec.fields)
    adapter.release(job, keep_open=False)


# --------------------------------------------------------------------------------------
# Submitting, and reading the outcome back
# --------------------------------------------------------------------------------------


def test_greenhouse_application_is_submitted_and_confirmed(
    browser, forms, tmp_path, resume
) -> None:
    job = Job(
        title="Backend Developer",
        company="acme",
        url=forms.url("greenhouse", "acme", "GH-OK", "Backend Developer"),
    )
    result = _apply(_adapter(browser, "greenhouse", tmp_path), job, _answers("acme"), resume)

    assert result.state is SubmissionState.SUBMITTED_CONFIRMED, result.reason
    assert result.confirmation_id.startswith("greenhouse-")
    [sent] = _received(forms, "GH-OK")
    fields = sent["fields"]
    assert fields["first_name"] == "Test" and fields["last_name"] == "Candidate"
    assert fields["email"] == "test@example.com"
    assert fields["candidate-location"] == "Gurugram, Haryana, India", (
        "the city suggestion was chosen"
    )
    assert fields["combo:relative"] == "No"
    assert fields["question_li"] == "https://www.linkedin.com/in/test-candidate"
    assert fields["file:resume"].startswith("Test_Candidate_resume.pdf|")


def test_lever_application_with_a_radio_question_is_confirmed(
    browser, forms, tmp_path, resume
) -> None:
    job = Job(
        title="Backend Developer",
        company="acme",
        url=forms.url("lever", "acme", "LV-OK", "Backend Developer"),
    )
    result = _apply(_adapter(browser, "lever", tmp_path), job, _answers("acme"), resume)

    assert result.state is SubmissionState.SUBMITTED_CONFIRMED, result.reason
    [sent] = _received(forms, "LV-OK")
    assert sent["fields"]["name"] == "Test Candidate"
    assert sent["fields"]["cards[c0][field0]"] == "Yes"
    assert sent["fields"]["urls[GitHub]"] == "https://github.com/test-candidate"
    assert "cards[c0][field2]" not in sent["fields"], (
        "an optional question nobody answered stays empty"
    )
    assert sent["fields"]["file:resume"].startswith("Test_Candidate_resume.pdf|")


def test_ashby_application_presses_the_right_buttons_and_is_confirmed(
    browser, forms, tmp_path, resume
) -> None:
    job = Job(
        title="Backend Developer",
        company="acme",
        url=forms.url("ashby", "acme", "AB-OK", "Backend Developer"),
    )
    result = _apply(_adapter(browser, "ashby", tmp_path), job, _answers("acme"), resume)

    assert result.state is SubmissionState.SUBMITTED_CONFIRMED, result.reason
    [sent] = _received(forms, "AB-OK")
    assert sent["fields"]["pressed:eligible"] == "Yes"
    assert sent["fields"]["pressed:sponsor"] == "No"
    assert sent["fields"]["file:_systemfield_resume"].startswith("Test_Candidate_resume.pdf|")
    assert not any(key == "file:file" for key in sent["fields"]), (
        "the autofill upload was left alone"
    )


# --------------------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------------------


def test_an_unanswered_required_question_sends_nothing_and_asks_once(
    browser, forms, tmp_path
) -> None:
    job = Job(
        title="Backend Developer",
        company="acme",
        url=forms.url("lever", "acme", "LV-ESSAY", "Backend Developer", essay=1),
    )
    adapter = _adapter(browser, "lever", tmp_path)
    adapter.inspect_application(job)
    form = adapter.prepare_fields(job, IDENTITY, _answers("acme"))
    adapter.release(job, keep_open=False)

    assert not form.is_complete
    assert any("Why do you want to join us?" in reason for reason in form.blocking)
    [question] = form.questions
    assert question.question_key.startswith("essay:")
    assert _received(forms, "LV-ESSAY") == []


def test_a_declaration_is_ticked_only_from_the_users_own_answer(
    browser, forms, tmp_path, resume
) -> None:
    url = forms.url("greenhouse", "acme", "GH-BGV", "Backend Developer", consent=1)
    consent_key = classify_label("I consent to a background verification check").key

    drafted = _answers("acme") | {consent_key: AnswerValue("Yes", AnswerProvenance.AI_DRAFT)}
    adapter = _adapter(browser, "greenhouse", tmp_path)
    job = Job(title="Backend Developer", company="acme", url=url)
    adapter.inspect_application(job)
    form = adapter.prepare_fields(job, IDENTITY, drafted)
    adapter.release(job, keep_open=False)
    assert not form.is_complete, "a generated 'Yes' must never agree to a declaration"
    assert [q.question_key for q in form.questions] == [consent_key]
    assert _received(forms, "GH-BGV") == []

    agreed = _answers("acme") | {consent_key: _user("Yes")}
    result = _apply(
        _adapter(browser, "greenhouse", tmp_path),
        Job(title="Backend Developer", company="acme", url=url),
        agreed,
        resume,
    )
    assert result.state is SubmissionState.SUBMITTED_CONFIRMED, result.reason


def test_a_captcha_is_handed_to_the_user_and_never_solved(browser, forms, tmp_path, resume) -> None:
    job = Job(
        title="Backend Developer",
        company="acme",
        url=forms.url("greenhouse", "acme", "GH-CAP", "Backend Developer", captcha=1),
    )
    result = _apply(_adapter(browser, "greenhouse", tmp_path), job, _answers("acme"), resume)

    assert result.state is SubmissionState.REQUIRES_USER_ACTION, result.reason
    assert "captcha" in result.reason.casefold()
    assert result.confirmation_id == ""
    assert _received(forms, "GH-CAP") == []


def test_a_thank_you_already_on_the_page_is_not_a_confirmation(
    browser, forms, tmp_path, resume
) -> None:
    """The page says "thank you for applying" before Submit, and the submit goes nowhere."""
    job = Job(
        title="Backend Developer",
        company="acme",
        url=forms.url("greenhouse", "acme", "GH-PRE", "Backend Developer", preexisting=1, silent=1),
    )
    result = _apply(_adapter(browser, "greenhouse", tmp_path), job, _answers("acme"), resume)

    assert result.state is SubmissionState.OUTCOME_UNKNOWN, result.reason
    assert result.confirmation_id == ""


def test_a_rejected_submission_is_a_failure_with_the_employers_reason(
    browser, forms, tmp_path, resume
) -> None:
    job = Job(
        title="Backend Developer",
        company="acme",
        url=forms.url("lever", "acme", "LV-REJ", "Backend Developer", reject=1),
    )
    result = _apply(_adapter(browser, "lever", tmp_path), job, _answers("acme"), resume)

    assert result.state is SubmissionState.FAILED, result.reason
    assert "Email address is invalid" in result.reason


def test_the_wrong_job_is_never_filled(browser, forms, tmp_path) -> None:
    """The queued job is a Data Scientist role; the page that opens is a different job."""
    url = forms.url("lever", "acme", "LV-WRONG", "Senior Sales Manager")
    job = Job(title="Data Scientist", company="acme", url=url)
    adapter = _adapter(browser, "lever", tmp_path)
    spec = adapter.inspect_application(job)
    adapter.release(job, keep_open=False)

    assert spec.human_required_reason.startswith("wrong page"), spec.human_required_reason
    assert _received(forms, "LV-WRONG") == []


def test_a_page_that_changes_before_submit_is_not_submitted(
    browser, forms, tmp_path, resume
) -> None:
    job = Job(
        title="Backend Developer",
        company="acme",
        url=forms.url("lever", "acme", "LV-SWAP", "Backend Developer"),
    )
    adapter = _adapter(browser, "lever", tmp_path)
    adapter.inspect_application(job)
    form = adapter.prepare_fields(job, IDENTITY, _answers("acme"))
    attachment = adapter.attach_resume(job, resume)

    opened = adapter._open[adapter._job_key(job)]
    browser.call(
        lambda _ctx: opened.page.evaluate(
            "() => { document.title = 'globex - Head of Marketing';"
            " document.querySelector('h2').innerText = 'Head of Marketing'; }"
        )
    )
    result = adapter.submit(job, form, attachment, idempotency_key="swap")
    adapter.release(job, keep_open=False)

    assert result.state is SubmissionState.FAILED
    assert "does not show the queued title" in result.reason
    assert _received(forms, "LV-SWAP") == []


def test_a_closed_posting_is_reported_as_closed(browser, forms, tmp_path) -> None:
    job = Job(
        title="Backend Developer", company="acme", url=f"{forms.base_url}/greenhouse/acme/gone"
    )
    adapter = _adapter(browser, "greenhouse", tmp_path)
    spec = adapter.inspect_application(job)
    adapter.release(job, keep_open=False)
    assert "closed" in spec.human_required_reason


def test_a_dry_run_fills_the_form_and_saves_a_screenshot_without_submitting(
    browser, forms, tmp_path, resume
) -> None:
    job = Job(
        title="Backend Developer",
        company="acme",
        url=forms.url("ashby", "acme", "AB-DRY", "Backend Developer"),
    )
    adapter = _adapter(browser, "ashby", tmp_path)
    adapter.inspect_application(job)
    form = adapter.prepare_fields(job, IDENTITY, _answers("acme"))
    shot = adapter.preview_fill(job, form, adapter.attach_resume(job, resume), label="dry")
    adapter.release(job, keep_open=False)

    assert Path(shot).is_file() and Path(shot).stat().st_size > 1000
    assert _received(forms, "AB-DRY") == []


# --------------------------------------------------------------------------------------
# The whole loop through the orchestrator: ask once, answer, apply, never twice
# --------------------------------------------------------------------------------------


def test_a_run_asks_the_new_question_then_applies_after_it_is_answered(
    browser,
    forms,
    tmp_path,
    session: Session,
    profile: CandidateProfile,
    engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JA_BROWSER_SUBMISSION_ENABLED", "true")
    monkeypatch.setenv("JA_BROWSER_BETWEEN_APPLICATIONS_MIN_S", "0")
    monkeypatch.setenv("JA_BROWSER_BETWEEN_APPLICATIONS_MAX_S", "0")
    reset_settings_cache()

    profile.work_authorization = "Yes"
    profile.requires_sponsorship = False
    profile.notice_period_days = 15
    profile.open_to_relocation = True
    profile.salary_expectation_min = 600000
    profile.salary_expectation_max = 600000
    profile.phone = "+91 90000 00000"
    profile.graduation_date = "2026-06"
    profile.education = [{"degree": "B.Tech", "institution": "Test Institute", "end_year": "2026"}]
    profile.links = ["https://github.com/test-candidate"]
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(make_pdf(["Test Candidate", "Backend developer. Python, FastAPI."]))
    session.add(
        Resume(
            profile_id=profile.id,
            label="base",
            original_filename="Test_Candidate_resume.pdf",
            stored_path=str(pdf),
            content_type="application/pdf",
            file_size_bytes=pdf.stat().st_size,
            sha256="0" * 64,
            extracted_text="Backend developer with Python and FastAPI experience.",
            is_primary=True,
        )
    )
    job = persist_job(session, title="Backend Developer", company="Testcorp", external_id="ORCH-1")
    job.url = forms.url("lever", "testcorp", "LV-ORCH", "Backend Developer")
    session.add(
        JobMatch(
            job_id=job.id,
            profile_id=profile.id,
            total_score=90.0,
            band="high",
            confidence="high",
            evidence_coverage=1.0,
            filtered_out=False,
        )
    )
    session.commit()

    adapter = _adapter(browser, "lever", tmp_path)
    monkeypatch.setattr("app.services.autoapply.adapter_for_job", lambda _job: adapter)
    service = AutoApplyService()
    targets = AutoApplyTargets(dry_run=False, min_score=50, max_submissions=5)

    # Run 1: the form asks something nothing on file answers. Nothing is sent; the
    # question lands in the Action inbox.
    first = service.execute(service.create_run(session, profile, targets).id, targets)
    session.expire_all()
    [attempt] = first.attempts
    assert attempt.state is SubmissionState.BLOCKED_MISSING_INFO, attempt.detail
    assert _received(forms, "LV-ORCH") == []
    radio_key = classify_label("Are you willing to work from the office five days a week?").key
    application = session.get(Application, attempt.application_id)
    assert application is not None
    asked = [a for a in application.answers if a.question_key == radio_key]
    assert asked and asked[0].requires_user_input
    assert "choose one of: Yes / No" in asked[0].question

    # The user answers once, in the inbox.
    AnswerBankService(session).resolve_from_inbox(profile, question_key=radio_key, answer="Yes")
    session.commit()
    assert SavedAnswerRepository(session).list(profile.id)

    # Run 2: the same job is retried and submitted with the user's PDF.
    second = service.execute(service.create_run(session, profile, targets).id, targets)
    session.expire_all()
    [attempt] = second.attempts
    assert attempt.state is SubmissionState.SUBMITTED_CONFIRMED, attempt.detail
    [sent] = _received(forms, "LV-ORCH")
    assert sent["fields"]["cards[c0][field0]"] == "Yes"
    assert sent["fields"]["file:resume"].startswith("Test_Candidate_resume.pdf|")
    application = session.get(Application, attempt.application_id)
    assert application is not None and application.status is ApplicationStatus.CONFIRMED

    # Run 3: a confirmed job is never queued again.
    third = service.execute(service.create_run(session, profile, targets).id, targets)
    assert third.attempts == []
    assert len(_received(forms, "LV-ORCH")) == 1
    total = session.query(SubmissionAttempt).filter(SubmissionAttempt.job_id == job.id).count()
    assert total == 2, "the first, blocked attempt keeps its history"


# --------------------------------------------------------------------------------------
# What may be submitted to at all
# --------------------------------------------------------------------------------------


def test_browser_targets_exist_only_when_switched_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Off by default; on, exactly the three hosted-form providers and nothing else."""
    from app.submission import adapter_for_job, supported_targets
    from app.submission.registry import BROWSER_TARGET_KEYS

    assert supported_targets() == frozenset(), "a default install submits nowhere"

    monkeypatch.setenv("JA_BROWSER_SUBMISSION_ENABLED", "true")
    reset_settings_cache()
    assert supported_targets() == BROWSER_TARGET_KEYS == frozenset({"greenhouse", "lever", "ashby"})
    for url in (
        "https://www.linkedin.com/jobs/view/1",
        "https://www.naukri.com/job-listings-x",
        "https://in.indeed.com/viewjob?jk=1",
        "https://wellfound.com/jobs/1",
        "https://jobs.smartrecruiters.com/acme/1",
        "https://apply.workable.com/acme/j/1",
        "https://careers.example.com/jobs/1",
    ):
        adapter = adapter_for_job(Job(title="", company="", url=url))
        assert adapter.check_capability(Job(title="", company="", url=url)).supported is False, url


# --------------------------------------------------------------------------------------
# Verification codes, checkpoints and evidence
# --------------------------------------------------------------------------------------


def test_a_verification_code_after_submit_is_handed_to_the_user(
    browser, forms, tmp_path, resume
) -> None:
    """An emailed security code is the user's to enter; JobOrbit never reads it."""
    job = Job(
        title="Backend Developer",
        company="acme",
        url=forms.url("greenhouse", "acme", "GH-MFA", "Backend Developer", mfa=1),
    )
    result = _apply(_adapter(browser, "greenhouse", tmp_path), job, _answers("acme"), resume)

    assert result.state is SubmissionState.REQUIRES_USER_ACTION, result.reason
    assert "verification" in result.reason.casefold()
    assert result.response_metadata.get("failure_category") == "mfa"
    assert result.confirmation_id == ""
    assert _received(forms, "GH-MFA") == []


def test_a_verification_prompt_on_arrival_stops_before_anything_is_typed(
    browser, forms, tmp_path
) -> None:
    adapter = _adapter(browser, "greenhouse", tmp_path)
    job = Job(
        title="Backend Developer",
        company="acme",
        url=forms.url("greenhouse", "acme", "GH-MFA2", "Backend Developer", mfa_on_load=1),
    )
    spec = adapter.inspect_application(job)
    assert spec.human_required_reason
    assert adapter.blocked_condition(job) == ("mfa", spec.human_required_reason)
    adapter.release(job, keep_open=False)


def test_submit_reports_each_checkpoint_before_the_step_it_names(
    browser, forms, tmp_path, resume
) -> None:
    """``submit_requested`` must be reported before Submit is pressed, not after."""
    adapter = _adapter(browser, "lever", tmp_path)
    job = Job(
        title="Backend Developer",
        company="acme",
        url=forms.url("lever", "acme", "LV-CHK", "Backend Developer"),
    )
    seen: list[tuple[str, int]] = []
    adapter.checkpoint_hook = lambda name, _detail: seen.append(
        (name, len(_received(forms, "LV-CHK")))
    )
    result = _apply(adapter, job, _answers("acme"), resume)

    assert result.state is SubmissionState.SUBMITTED_CONFIRMED, result.reason
    assert [name for name, _ in seen] == ["form_filled", "submit_requested", "submit_clicked"]
    assert dict(seen)["submit_requested"] == 0, "the employer had the form before the checkpoint"
    shot = str(result.response_metadata.get("screenshot") or "")
    assert shot.endswith(".png") and Path(shot).is_file()
    assert (Path(shot).stat().st_mode & 0o777) == 0o600, "evidence must be owner-only"


def test_a_stop_at_the_last_checkpoint_means_submit_is_never_pressed(
    browser, forms, tmp_path, resume
) -> None:
    from app.services.autoapply_control import EmergencyStopActive

    adapter = _adapter(browser, "greenhouse", tmp_path)
    job = Job(
        title="Backend Developer",
        company="acme",
        url=forms.url("greenhouse", "acme", "GH-STOP", "Backend Developer"),
    )

    def hook(name: str, _detail: str) -> None:
        if name == "submit_requested":
            raise EmergencyStopActive("stopped")

    adapter.checkpoint_hook = hook
    with pytest.raises(EmergencyStopActive):
        _apply(adapter, job, _answers("acme"), resume)
    assert _received(forms, "GH-STOP") == []
    adapter.release(job, keep_open=False)


def test_a_custom_domain_greenhouse_job_routes_to_the_greenhouse_embed_form() -> None:
    """A job listed on the company's careers site is still a Greenhouse application."""
    from app.db.models import JobSourceReference, SourceName
    from app.submission.browser_ats import greenhouse_apply_url
    from app.submission.registry import target_for_job

    def job(url: str, board: str | None, external_id: str = "8349259") -> Job:
        row = Job(title="Software Engineer 3", company="MongoDB", url=url)
        if board is not None:
            row.source_references = [
                JobSourceReference(
                    source=SourceName.GREENHOUSE,
                    external_id=external_id,
                    source_metadata={"board": board},
                )
            ]
        return row

    custom = job("https://www.mongodb.com/careers/job/?gh_jid=8349259", "mongodb")
    assert target_for_job(custom).key == "greenhouse"
    assert greenhouse_apply_url(custom) == (
        "https://job-boards.greenhouse.io/embed/job_app?for=mongodb&token=8349259"
    )

    hosted = job("https://job-boards.greenhouse.io/groww/jobs/123", "groww", "123")
    assert greenhouse_apply_url(hosted) == "https://job-boards.greenhouse.io/groww/jobs/123"

    # No Greenhouse discovery behind it, or no usable id: still an unknown form.
    assert target_for_job(job("https://careers.example.com/role/9", None)).key == "unknown"
    assert target_for_job(job("https://careers.example.com/role/9", "acme", "abc")).key == "unknown"


def test_a_form_rebuilt_after_it_was_read_is_matched_again_and_filled(
    browser, forms, tmp_path, resume
) -> None:
    """Regression: Rubrik's embed form re-rendered after inspection and the fill timed out."""
    import time

    adapter = _adapter(browser, "greenhouse", tmp_path)
    job = Job(
        title="Backend Developer",
        company="acme",
        url=forms.url("greenhouse", "acme", "GH-RR", "Backend Developer", rerender=1),
    )
    adapter.inspect_application(job)
    time.sleep(2.5)  # the page rebuilds its form 1.5 s after load
    opened = adapter._open[adapter._job_key(job)]
    tags = adapter._call(lambda _ctx: opened.page.locator("[data-jo-field]").count())
    assert tags == 0, "the fixture should have dropped the tags before filling starts"
    result = _apply(adapter, job, _answers("acme"), resume)

    assert result.state is SubmissionState.SUBMITTED_CONFIRMED, result.reason
    assert len(_received(forms, "GH-RR")) == 1


def test_a_form_that_rerenders_when_the_resume_is_attached_is_still_filled(
    browser, forms, tmp_path, resume
) -> None:
    """Regression: Rubrik's form replaced the file input on upload and the fill hung 45 s."""
    job = Job(
        title="Backend Developer",
        company="acme",
        url=forms.url("greenhouse", "acme", "GH-UR", "Backend Developer", upload_rerender=1),
    )
    result = _apply(_adapter(browser, "greenhouse", tmp_path), job, _answers("acme"), resume)

    assert result.state is SubmissionState.SUBMITTED_CONFIRMED, result.reason
    assert len(_received(forms, "GH-UR")) == 1
