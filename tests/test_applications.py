"""Application preparation and lifecycle: provenance, truthfulness, state transitions."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.db.models import (
    AnswerProvenance,
    Application,
    ApplicationStatus,
    CandidateProfile,
    Resume,
)
from app.db.repositories import (
    ApplicationRepository,
    DuplicateApplicationError,
    ProfileRepository,
    ResumeRepository,
)
from app.llm.null_provider import EchoProvider, NullProvider
from app.services import questions as question_service
from app.services import resume_variants
from app.services.application_prep import ApplicationPreparationService, generate_cover_letter
from app.services.tracking import (
    ApplicationTracker,
    AutomatedSubmissionBlocked,
    InvalidTransition,
    TransitionRequest,
    blocking_questions,
    can_transition,
)
from tests.conftest import make_record, persist_job

SENSITIVE_QUESTION_KEYS = {
    "work_authorization",
    "requires_sponsorship",
    "salary_expectation",
    "notice_period",
    "graduation_date",
    "education",
    "years_experience",
    "relocation",
}


def _resume_for(session: Session, profile: CandidateProfile) -> Resume:
    return ResumeRepository(session).add(
        Resume(
            profile_id=profile.id,
            label="base",
            original_filename="resume.docx",
            stored_path="/tmp/resume.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            file_size_bytes=1024,
            sha256="a" * 64,
            extracted_text="Python FastAPI PostgreSQL",
            extracted_fields={
                "skills": ["python", "fastapi", "postgresql", "docker"],
                "projects": [
                    {
                        "name": "Job Matcher",
                        "description": "FastAPI service ranking jobs",
                        "technologies": ["python", "fastapi"],
                    }
                ],
                "education": [{"degree": "B.Tech", "institution": "NIT", "end_year": "2026"}],
                "certifications": ["AWS Certified Cloud Practitioner"],
                "full_name": "Test Candidate",
                "email": "test@example.com",
            },
            is_primary=True,
        )
    )


# --------------------------------------------------------------------------------------
# Question mapping and provenance
# --------------------------------------------------------------------------------------


def test_unanswered_sensitive_questions_are_flagged_and_never_drafted(
    session: Session, profile: CandidateProfile
) -> None:
    job = persist_job(session, make_record(external_id="Q-1"))
    answers = question_service.build_question_set(job, profile)

    for answer in answers:
        if answer.question_key in SENSITIVE_QUESTION_KEYS and not answer.answer:
            assert answer.requires_user_input
            assert answer.provenance is AnswerProvenance.NEEDS_USER_INPUT
            assert answer.flag_reason


def test_verified_profile_values_are_used_with_verified_provenance(
    session: Session, profile: CandidateProfile
) -> None:
    ProfileRepository(session).update(
        profile,
        {
            "work_authorization": "Indian citizen, authorised to work in India",
            "requires_sponsorship": False,
            "notice_period_days": 0,
            "graduation_date": "2026",
            "open_to_relocation": True,
            "salary_expectation_min": 800_000,
            "salary_expectation_max": 1_400_000,
            "education": [{"degree": "B.Tech", "institution": "NIT", "end_year": "2026"}],
            "phone": "+91 98765 43210",
            "links": ["https://github.com/test"],
        },
    )
    session.commit()

    job = persist_job(session, make_record(external_id="Q-2"))
    answers = question_service.build_question_set(job, profile)
    by_key = {answer.question_key: answer for answer in answers}

    assert by_key["work_authorization"].provenance is AnswerProvenance.PROFILE_VERIFIED
    assert by_key["notice_period"].answer == "Immediately available"
    assert by_key["salary_expectation"].answer.startswith("INR 800,000")
    assert by_key["requires_sponsorship"].answer == "No"
    assert not any(answer.requires_user_input for answer in answers)


def test_questions_found_in_the_description_become_answerable_items(
    session: Session, profile: CandidateProfile
) -> None:
    job = persist_job(
        session,
        make_record(
            external_id="Q-3",
            description=(
                "About the role.\n"
                "Why do you want to work here?\n"
                "- What is your proudest engineering achievement?\n"
                "Apply now."
            ),
        ),
    )
    answers = question_service.build_question_set(job, profile)
    found = [answer.question for answer in answers]

    assert any("Why do you want to work here?" in question for question in found)
    assert any("proudest engineering achievement" in question for question in found)


@pytest.mark.parametrize(
    ("question", "expected_key"),
    [
        ("Do you require visa sponsorship?", "work_authorization"),
        ("What is your expected CTC?", "salary_expectation"),
        ("What is your notice period?", "notice_period"),
        ("How many years of experience do you have with Go?", "years_experience"),
        ("Have you ever been convicted of a felony?", "criminal_record"),
        ("Do you have a disability?", "disability"),
        ("What is your date of birth?", "date_of_birth"),
        ("I certify that the above is true", "legal_declaration"),
    ],
)
def test_sensitive_and_legal_questions_are_classified_as_such(
    question: str, expected_key: str
) -> None:
    key, sensitive = question_service.classify_question(question)
    assert key == expected_key
    assert sensitive is True


def test_an_ordinary_open_question_is_not_marked_sensitive() -> None:
    key, sensitive = question_service.classify_question("Why do you want to join us?")
    assert sensitive is False
    assert key


def test_an_unknown_question_requires_user_input_rather_than_a_guess(
    session: Session, profile: CandidateProfile
) -> None:
    job = persist_job(session, make_record(external_id="Q-4"))
    answers = question_service.build_question_set(
        job, profile, extra_questions=["What is your favourite build tool and why?"]
    )
    unknown = next(answer for answer in answers if "favourite build tool" in answer.question)
    assert unknown.answer == ""
    assert unknown.requires_user_input
    assert unknown.provenance is AnswerProvenance.NEEDS_USER_INPUT


# --------------------------------------------------------------------------------------
# Cover letters and variants
# --------------------------------------------------------------------------------------


def test_cover_letter_without_an_llm_is_rule_based_and_claims_nothing_extra(
    session: Session, profile: CandidateProfile
) -> None:
    job = persist_job(session, make_record(external_id="CL-1"))
    letter, generated_by, warnings = generate_cover_letter(
        job, profile, ["python", "fastapi"], NullProvider()
    )

    assert generated_by == "rule_based"
    assert warnings == []
    assert "python" in letter.lower()
    assert "years of experience" not in letter.lower()
    assert "salary" not in letter.lower()
    assert "visa" not in letter.lower()


def test_an_llm_draft_that_invents_a_sensitive_claim_is_discarded(
    session: Session, profile: CandidateProfile
) -> None:
    """A model asserting experience that is not in the facts must not reach the user."""
    job = persist_job(session, make_record(external_id="CL-2"))
    liar = EchoProvider(
        reply="I have 8 years of experience and hold a Kubernetes certification, "
        "and my expected salary is negotiable."
    )
    letter, generated_by, warnings = generate_cover_letter(job, profile, ["python"], liar)

    assert generated_by == "rule_based"
    assert "8 years" not in letter
    assert warnings
    assert any("discarded" in warning for warning in warnings)


def test_an_acceptable_llm_draft_is_used_and_labelled(
    session: Session, profile: CandidateProfile
) -> None:
    job = persist_job(session, make_record(external_id="CL-3"))
    honest = EchoProvider(
        reply="I would like to apply for the Backend Developer role at Acme Technologies. "
        "I have built services with Python and FastAPI."
    )
    letter, generated_by, warnings = generate_cover_letter(job, profile, ["python"], honest)

    assert generated_by.startswith("ai_draft")
    assert "Python" in letter
    assert any("Read it before use" in warning for warning in warnings)


def test_a_variant_only_contains_skills_present_in_the_resume_or_profile(
    session: Session, profile: CandidateProfile
) -> None:
    resume = _resume_for(session, profile)
    draft = resume_variants.build_variant(
        resume, profile, "genai", emphasise=["Python", "Rust", "COBOL"]
    )

    assert resume_variants.audit_variant(draft, resume, profile) == []
    assert "rust" not in draft.content.lower().split("## projects")[0]
    assert draft.included_items["omitted_requested_skills"] == ["cobol", "rust"]
    assert any("not in your resume" in warning for warning in draft.warnings)


def test_the_variant_audit_detects_an_unsourced_skill(
    session: Session, profile: CandidateProfile
) -> None:
    resume = _resume_for(session, profile)
    draft = resume_variants.build_variant(resume, profile, "backend")
    draft.content += "\n**Most relevant:** haskell, prolog\n"

    problems = resume_variants.audit_variant(draft, resume, profile)
    assert len(problems) == 2
    assert any("haskell" in problem for problem in problems)


@pytest.mark.parametrize(
    ("title", "family"),
    [
        ("Generative AI Engineer", "genai"),
        ("Agentic AI Engineer", "genai"),
        ("Machine Learning Engineer", "ai_ml"),
        ("Backend Developer", "backend"),
        ("Frontend Developer", "frontend"),
        ("Full-Stack Developer", "fullstack"),
        ("DevOps Engineer", "cloud_devops"),
        ("Cloud Engineer", "cloud_devops"),
        ("Data Engineer", "data"),
        ("Software Engineer", "general_software"),
    ],
)
def test_job_family_inference(title: str, family: str) -> None:
    assert resume_variants.infer_job_family(title) == family


# --------------------------------------------------------------------------------------
# Preparation and lifecycle
# --------------------------------------------------------------------------------------


def test_preparation_reaches_review_but_never_submits(
    session: Session, profile: CandidateProfile
) -> None:
    _resume_for(session, profile)
    job = persist_job(session, make_record(external_id="P-1"))
    prepared = ApplicationPreparationService(session, NullProvider()).prepare(job, profile)

    assert prepared.application.status is ApplicationStatus.READY_FOR_REVIEW
    assert prepared.application.submitted_at is None
    assert prepared.application.submitted_by == ""
    assert prepared.variant is not None
    assert prepared.application.resume_version_label
    assert prepared.blocking_questions


def test_preparation_without_a_resume_warns_rather_than_failing(
    session: Session, profile: CandidateProfile
) -> None:
    job = persist_job(session, make_record(external_id="P-2"))
    prepared = ApplicationPreparationService(session, NullProvider()).prepare(job, profile)

    assert prepared.variant is None
    assert any("No resume" in warning for warning in prepared.warnings)


def test_preparing_twice_refreshes_the_same_application(
    session: Session, profile: CandidateProfile
) -> None:
    _resume_for(session, profile)
    job = persist_job(session, make_record(external_id="P-3"))
    service = ApplicationPreparationService(session, NullProvider())
    first = service.prepare(job, profile)
    second = service.prepare(job, profile)

    assert first.application.id == second.application.id
    assert second.application.cover_letter_version == 2


def test_a_duplicate_application_is_prevented_at_the_repository(
    session: Session, profile: CandidateProfile
) -> None:
    job = persist_job(session, make_record(external_id="P-4"))
    repository = ApplicationRepository(session)
    repository.create(Application(job_id=job.id, profile_id=profile.id, platform="manual"))

    with pytest.raises(DuplicateApplicationError):
        repository.create(Application(job_id=job.id, profile_id=profile.id, platform="linkedin"))


def test_preparing_a_job_already_submitted_is_refused(
    session: Session, profile: CandidateProfile
) -> None:
    _resume_for(session, profile)
    job = persist_job(session, make_record(external_id="P-5"))
    service = ApplicationPreparationService(session, NullProvider())
    prepared = service.prepare(job, profile)
    prepared.application.status = ApplicationStatus.SUBMITTED
    session.flush()

    with pytest.raises(DuplicateApplicationError):
        service.prepare(job, profile)


def test_editing_an_answer_marks_it_as_user_entered(
    session: Session, profile: CandidateProfile
) -> None:
    _resume_for(session, profile)
    job = persist_job(session, make_record(external_id="P-6"))
    service = ApplicationPreparationService(session, NullProvider())
    application = service.prepare(job, profile).application

    target = next(
        answer for answer in application.answers if answer.question_key == "work_authorization"
    )
    service.apply_answer_edits(application, {target.id: "Indian citizen"})

    assert target.answer == "Indian citizen"
    assert target.provenance is AnswerProvenance.USER_ENTERED
    assert target.requires_user_input is False


# --------------------------------------------------------------------------------------
# State machine
# --------------------------------------------------------------------------------------


def _ready_application(session: Session, profile: CandidateProfile, suffix: str) -> Application:
    _resume_for(session, profile)
    ProfileRepository(session).update(
        profile,
        {
            "work_authorization": "Indian citizen",
            "requires_sponsorship": False,
            "notice_period_days": 0,
            "graduation_date": "2026",
            "open_to_relocation": True,
            "salary_expectation_min": 800_000,
            "education": [{"degree": "B.Tech", "institution": "NIT", "end_year": "2026"}],
            "phone": "+91 98765 43210",
            "links": ["https://github.com/test"],
        },
    )
    session.commit()
    job = persist_job(session, make_record(external_id=f"SM-{suffix}"))
    return ApplicationPreparationService(session, NullProvider()).prepare(job, profile).application


def test_approval_requires_explicit_user_approval(
    session: Session, profile: CandidateProfile
) -> None:
    application = _ready_application(session, profile, "1")
    tracker = ApplicationTracker(session)

    with pytest.raises(InvalidTransition, match="explicit user approval"):
        tracker.transition(application, TransitionRequest(ApplicationStatus.APPROVED))


def test_approval_is_blocked_while_questions_need_input(
    session: Session, profile: CandidateProfile
) -> None:
    _resume_for(session, profile)
    job = persist_job(session, make_record(external_id="SM-2"))
    application = (
        ApplicationPreparationService(session, NullProvider()).prepare(job, profile).application
    )
    application.user_approved = True
    session.flush()

    assert blocking_questions(application)
    with pytest.raises(InvalidTransition, match="need your input"):
        ApplicationTracker(session).transition(
            application, TransitionRequest(ApplicationStatus.APPROVED)
        )


def test_a_non_human_actor_cannot_record_a_submission(
    session: Session, profile: CandidateProfile
) -> None:
    """Defence in depth: nothing in this codebase submits, and the guard proves it."""
    application = _ready_application(session, profile, "3")
    tracker = ApplicationTracker(session)
    application.user_approved = True
    tracker.transition(application, TransitionRequest(ApplicationStatus.APPROVED))

    with pytest.raises(AutomatedSubmissionBlocked):
        tracker.transition(
            application,
            TransitionRequest(
                ApplicationStatus.SUBMITTED, actor="scheduler", submitted_by="scheduler"
            ),
        )


def test_recording_a_submission_requires_naming_the_submitter(
    session: Session, profile: CandidateProfile
) -> None:
    application = _ready_application(session, profile, "4")
    tracker = ApplicationTracker(session)
    application.user_approved = True
    tracker.transition(application, TransitionRequest(ApplicationStatus.APPROVED))

    with pytest.raises(InvalidTransition, match="who submitted it"):
        tracker.transition(application, TransitionRequest(ApplicationStatus.SUBMITTED))


def test_confirmation_requires_evidence_not_just_a_click(
    session: Session, profile: CandidateProfile
) -> None:
    application = _ready_application(session, profile, "5")
    tracker = ApplicationTracker(session)
    application.user_approved = True
    tracker.transition(application, TransitionRequest(ApplicationStatus.APPROVED))
    tracker.transition(
        application, TransitionRequest(ApplicationStatus.SUBMITTED, submitted_by="Test Candidate")
    )

    with pytest.raises(InvalidTransition, match="evidence"):
        tracker.transition(application, TransitionRequest(ApplicationStatus.CONFIRMED))


def test_an_uncertain_outcome_is_recorded_as_unknown(
    session: Session, profile: CandidateProfile
) -> None:
    application = _ready_application(session, profile, "6")
    tracker = ApplicationTracker(session)
    application.user_approved = True
    tracker.transition(application, TransitionRequest(ApplicationStatus.APPROVED))
    tracker.transition(application, TransitionRequest(ApplicationStatus.SUBMISSION_UNKNOWN))

    assert application.status is ApplicationStatus.SUBMISSION_UNKNOWN
    assert application.confirmed_at is None


def test_the_happy_path_records_every_transition(
    session: Session, profile: CandidateProfile
) -> None:
    application = _ready_application(session, profile, "7")
    tracker = ApplicationTracker(session)
    application.user_approved = True

    tracker.transition(application, TransitionRequest(ApplicationStatus.APPROVED))
    tracker.transition(
        application,
        TransitionRequest(ApplicationStatus.SUBMITTED, submitted_by="Test Candidate"),
    )
    tracker.transition(
        application,
        TransitionRequest(
            ApplicationStatus.CONFIRMED, confirmation_evidence="Confirmation email ref 123"
        ),
    )

    assert application.status is ApplicationStatus.CONFIRMED
    assert application.submitted_by == "Test Candidate"
    assert application.confirmation_evidence == "Confirmation email ref 123"
    assert application.confirmed_at is not None
    transitions = [(event.from_status, event.to_status) for event in application.events]
    assert (ApplicationStatus.APPROVED, ApplicationStatus.SUBMITTED) in transitions
    assert (ApplicationStatus.SUBMITTED, ApplicationStatus.CONFIRMED) in transitions


def test_confirmed_is_terminal(session: Session, profile: CandidateProfile) -> None:
    assert can_transition(ApplicationStatus.CONFIRMED, ApplicationStatus.SKIPPED) is False
    application = _ready_application(session, profile, "8")
    tracker = ApplicationTracker(session)
    application.user_approved = True
    tracker.transition(application, TransitionRequest(ApplicationStatus.APPROVED))
    tracker.transition(
        application, TransitionRequest(ApplicationStatus.SUBMITTED, submitted_by="Me")
    )
    tracker.transition(
        application, TransitionRequest(ApplicationStatus.CONFIRMED, confirmation_evidence="ref")
    )

    with pytest.raises(InvalidTransition, match="final"):
        tracker.transition(application, TransitionRequest(ApplicationStatus.SKIPPED))


@pytest.mark.parametrize(
    ("current", "target", "allowed"),
    [
        (ApplicationStatus.SHORTLISTED, ApplicationStatus.READY_FOR_REVIEW, True),
        (ApplicationStatus.SHORTLISTED, ApplicationStatus.SUBMITTED, False),
        (ApplicationStatus.READY_FOR_REVIEW, ApplicationStatus.APPROVED, True),
        (ApplicationStatus.READY_FOR_REVIEW, ApplicationStatus.CONFIRMED, False),
        (ApplicationStatus.APPROVED, ApplicationStatus.SUBMITTED, True),
        (ApplicationStatus.SUBMITTED, ApplicationStatus.CONFIRMED, True),
        (ApplicationStatus.SKIPPED, ApplicationStatus.SHORTLISTED, True),
        (ApplicationStatus.CONFIRMED, ApplicationStatus.SUBMITTED, False),
    ],
)
def test_transition_table(
    current: ApplicationStatus, target: ApplicationStatus, allowed: bool
) -> None:
    assert can_transition(current, target) is allowed


def test_a_transition_to_the_same_status_is_a_no_op(
    session: Session, profile: CandidateProfile
) -> None:
    application = _ready_application(session, profile, "9")
    before = len(application.events)
    ApplicationTracker(session).transition(
        application, TransitionRequest(ApplicationStatus.READY_FOR_REVIEW)
    )
    assert len(application.events) == before
