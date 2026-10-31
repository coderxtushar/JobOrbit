"""Truthfulness audits for generated material and reusable answers.

Two questions are asked here, both of which a bulk run makes higher-stakes:

1. Does tailoring stay factual? A resume variant may only reorder and emphasise what the
   resume already says, and a cover letter may only assert facts from a closed list. At one
   application the user would notice a fabrication; at a hundred they will not.
2. Can an unverified answer become a verified one? The answer bank exists to reuse an
   answer across every application, so a draft leaking into it would repeat one unreviewed
   claim to every employer.

The fixtures mirror the real candidate: a 2026 B.Tech graduate with roughly five months of
professional experience, no stated salary, notice period or work authorization.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy.orm import Session

from app.db.models import (
    AnswerProvenance,
    ApplicationArtifact,
    CandidateProfile,
    Resume,
    SavedAnswer,
)
from app.db.repositories import ProfileRepository, SavedAnswerRepository, UnbankableAnswerError
from app.services import resume_variants
from app.services.answer_bank import AnswerBankService, apply_saved_answer
from app.services.application_prep import ApplicationPreparationService
from app.services.questions import SENSITIVE_KEYS
from tests.conftest import make_record, persist_job

RESUME_TEXT = "\n".join(
    [
        "TUSHAR GAUTAM",
        "Gurgaon, Haryana | +91 90000 00000 | candidate@example.com",
        "EDUCATION",
        "Invertis University",
        "Bachelor of Technology in Computer Science Engineering",
        "Aug 2022 - Jun 2026",
        "WORK EXPERIENCE",
        "Software Engineer, Ethara AI",
        "May 2026 - Present",
        "- Contribute to the Long Horizon Terminal Benchmarking project.",
        "PROJECTS / OPEN-SOURCE",
        "BrandBot AI Agent",
        "Python, FastAPI, Langchain, React.js, Tailwind CSS",
        "- Built an autonomous LinkedIn AI agent using LangChain and Google Gemini.",
        "Snap UI",
        "Next.js, React.js, Typescript, Tailwind CSS",
        "- Developed an AI-driven UI builder.",
        "TECHNICAL SKILLS",
        "Languages: Python, JavaScript, C++",
        "Backend: Node.js, Express.js, FastAPI, MongoDB, PostgreSQL",
        "Tools: Docker, Kubernetes, AWS, GitHub Actions, Linux",
    ]
)

#: Claims a generated document must never make for this candidate, because the resume does
#: not contain them. Each is a real screening question with legal or financial weight.
UNSUPPORTED_CLAIM_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b\d+\+?\s*(?:years?|yrs?)\s+(?:of\s+)?experience", "a years-of-experience figure"),
    (r"\b(?:salary|ctc|compensation|lpa)\b", "a salary statement"),
    (r"\b(?:visa|sponsorship|work permit|authoris|authoriz)", "a work-authorization claim"),
    (r"\bnotice period\b", "a notice-period claim"),
    (r"\b(?:certified|certification)\b", "a certification claim"),
    (r"\b(?:cgpa|gpa|percentile)\b", "an academic score"),
)


@pytest.fixture
def real_profile(session: Session) -> CandidateProfile:
    repository = ProfileRepository(session)
    profile = repository.get_or_create_default()
    repository.update(
        profile,
        {
            "full_name": "Tushar Gautam",
            "email": "candidate@example.com",
            "experience_level": "fresher",
            "years_experience": 0.4,
            "graduation_date": "2026",
            "target_titles": [
                "Software Engineer",
                "Backend Developer",
                "Python Developer",
                "Frontend Developer",
                "Generative AI Engineer",
                "Cloud Engineer",
                "DevOps Engineer",
            ],
            "technical_skills": [
                "python",
                "fastapi",
                "node.js",
                "express.js",
                "mongodb",
                "postgresql",
                "docker",
                "kubernetes",
                "aws",
                "react",
                "next.js",
                "typescript",
                "langchain",
                "llm",
            ],
            "projects": [
                {
                    "name": "BrandBot AI Agent",
                    "description": "Autonomous LinkedIn AI agent using LangChain.",
                    "technologies": ["python", "fastapi", "langchain"],
                },
                {
                    "name": "Snap UI",
                    "description": "AI-driven UI builder.",
                    "technologies": ["next.js", "react", "typescript"],
                },
            ],
            "education": [
                {
                    "degree": "Bachelor of Technology",
                    "field_of_study": "Computer Science Engineering",
                    "institution": "Invertis University",
                    "start_year": "2022",
                    "end_year": "2026",
                    "grade": "",
                }
            ],
            "preferred_locations": ["Remote", "Gurgaon", "Bengaluru"],
            "work_arrangements": ["remote", "hybrid", "onsite"],
            "employment_types": ["full_time", "internship"],
        },
    )
    session.add(
        Resume(
            profile_id=profile.id,
            label="Primary",
            original_filename="Tushar_Gautam_resume.pdf",
            stored_path="Tushar_Gautam_resume.pdf",
            content_type="application/pdf",
            file_size_bytes=len(RESUME_TEXT),
            sha256="a" * 64,
            extracted_text=RESUME_TEXT,
            is_primary=True,
        )
    )
    session.flush()
    return profile


def _prepare(session: Session, profile: CandidateProfile, **overrides):
    job = persist_job(session, **overrides)
    return ApplicationPreparationService(session).prepare(job, profile)


# --------------------------------------------------------------------------------------
# Tailoring factual accuracy
# --------------------------------------------------------------------------------------


def test_a_cover_letter_asserts_nothing_the_resume_does_not_support(
    session: Session, real_profile: CandidateProfile
) -> None:
    jobs = [
        ("Backend Developer", "Zeta Platform Labs", ["Python", "FastAPI"]),
        ("Generative AI Engineer", "Sentient Stack", ["Python", "LangChain", "LLM"]),
        ("Cloud Engineer", "Stratus Cloudworks", ["AWS", "Docker", "Kubernetes"]),
        ("Frontend Developer", "Pixelforge", ["React", "Next.js", "TypeScript"]),
    ]
    for index, (title, company, skills) in enumerate(jobs):
        prepared = _prepare(
            session,
            real_profile,
            record=make_record(
                external_id=f"TAILOR-{index}",
                title=title,
                company=company,
                required_skills=skills,
                url=f"https://jobs.example.com/tailor/{index}",
            ),
        )
        letter = prepared.application.cover_letter
        assert letter, f"{title} produced no cover letter"
        for pattern, label in UNSUPPORTED_CLAIM_PATTERNS:
            assert not re.search(pattern, letter, re.IGNORECASE), (
                f"the letter for {title} @ {company} asserts {label}: {letter[:200]}"
            )
    session.flush()


def test_a_cover_letter_names_its_own_job_and_company(
    session: Session, real_profile: CandidateProfile
) -> None:
    """A hundred letters that all name the wrong employer is the obvious bulk failure."""
    pairs = [
        ("Backend Developer", "Alpha Systems"),
        ("Frontend Developer", "Beta Interfaces"),
        ("Cloud Engineer", "Gamma Cloudworks"),
    ]
    letters: dict[str, str] = {}
    for index, (title, company) in enumerate(pairs):
        prepared = _prepare(
            session,
            real_profile,
            record=make_record(
                external_id=f"NAME-{index}",
                title=title,
                company=company,
                url=f"https://jobs.example.com/name/{index}",
            ),
        )
        letter = prepared.application.cover_letter
        assert title.lower() in letter.lower(), f"{title} not named in its own letter"
        assert company.lower() in letter.lower(), f"{company} not named in its own letter"
        letters[company] = letter

    for company, letter in letters.items():
        others = [name for name in letters if name != company]
        for other in others:
            assert other.lower() not in letter.lower(), (
                f"the letter for {company} also names {other}"
            )
    session.flush()


def test_a_resume_variant_adds_no_fact_absent_from_the_resume(
    session: Session, real_profile: CandidateProfile
) -> None:
    """Variants may reorder and emphasise, never introduce."""
    from app.db.repositories import ResumeRepository

    resume = ResumeRepository(session).get_primary(real_profile.id)
    assert resume is not None
    for family in ("backend", "genai", "frontend", "cloud_devops", "general_software"):
        draft = resume_variants.build_variant(resume, real_profile, family)
        problems = resume_variants.audit_variant(draft, resume, real_profile)
        assert not problems, f"variant '{family}' failed its own audit: {problems}"
        for pattern, label in UNSUPPORTED_CLAIM_PATTERNS:
            assert not re.search(pattern, draft.content, re.IGNORECASE), (
                f"variant '{family}' asserts {label}"
            )


def test_the_selected_variant_matches_the_job_family(
    session: Session, real_profile: CandidateProfile
) -> None:
    expectations = [
        ("Backend Developer", ["Python", "FastAPI", "PostgreSQL"], "backend"),
        ("Generative AI Engineer", ["LangChain", "LLM", "Python"], "genai"),
        ("Frontend Developer", ["React", "Next.js", "TypeScript"], "frontend"),
        ("DevOps Engineer", ["Docker", "Kubernetes", "AWS"], "cloud_devops"),
    ]
    for index, (title, skills, family) in enumerate(expectations):
        prepared = _prepare(
            session,
            real_profile,
            record=make_record(
                external_id=f"FAMILY-{index}",
                title=title,
                company=f"Family Co {index}",
                required_skills=skills,
                url=f"https://jobs.example.com/family/{index}",
            ),
        )
        assert prepared.variant is not None, f"{title} selected no variant"
        assert prepared.variant.job_family == family, (
            f"{title} got variant family '{prepared.variant.job_family}', expected '{family}'"
        )
    session.flush()


def test_each_application_keeps_its_own_artifact_rows(
    session: Session, real_profile: CandidateProfile
) -> None:
    """Two backend jobs legitimately share a variant, but each keeps its own snapshot row.

    Sharing a row would make it impossible to say what a given employer received once the
    variant is regenerated.
    """
    applications = []
    for index, company in enumerate(("First Backend Co", "Second Backend Co")):
        prepared = _prepare(
            session,
            real_profile,
            record=make_record(
                external_id=f"ART-{index}",
                title="Backend Developer",
                company=company,
                required_skills=["Python", "FastAPI"],
                url=f"https://jobs.example.com/art/{index}",
            ),
        )
        applications.append(prepared.application)
    session.flush()

    for application in applications:
        rows = (
            session.query(ApplicationArtifact)
            .filter(ApplicationArtifact.application_id == application.id)
            .all()
        )
        kinds = {row.kind for row in rows}
        assert "cover_letter" in kinds, f"application {application.id} snapshotted no letter"
        for row in rows:
            assert row.application_id == application.id
            assert len(row.content_sha256) == 64
            assert row.byte_size == len(row.content.encode("utf-8"))

    letters = {
        application.id: next(
            row.content
            for row in session.query(ApplicationArtifact)
            .filter(
                ApplicationArtifact.application_id == application.id,
                ApplicationArtifact.kind == "cover_letter",
            )
            .all()
        )
        for application in applications
    }
    assert len(set(letters.values())) == len(letters), (
        "two applications to different companies stored an identical cover letter"
    )


# --------------------------------------------------------------------------------------
# Answer provenance
# --------------------------------------------------------------------------------------


def test_no_sensitive_answer_is_ever_pre_filled_without_the_user(
    session: Session, real_profile: CandidateProfile
) -> None:
    """Salary, notice period, sponsorship and authorization must stay unanswered.

    The profile fixture deliberately records none of them, exactly like the real resume.
    """
    prepared = _prepare(
        session,
        real_profile,
        record=make_record(external_id="SENS-1", company="Sensitive Co"),
    )
    session.flush()
    must_be_blank = {
        "work_authorization",
        "requires_sponsorship",
        "salary_expectation",
        "notice_period",
        "relocation",
    }
    seen = set()
    for answer in prepared.application.answers:
        if answer.question_key not in must_be_blank:
            continue
        seen.add(answer.question_key)
        assert answer.answer == "", f"{answer.question_key} was filled in: {answer.answer!r}"
        assert answer.requires_user_input is True
        assert answer.provenance is AnswerProvenance.NEEDS_USER_INPUT
        assert answer.flag_reason
    assert seen == must_be_blank, f"questions missing from the set: {must_be_blank - seen}"


def test_every_sensitive_question_is_marked_sensitive(
    session: Session, real_profile: CandidateProfile
) -> None:
    prepared = _prepare(
        session,
        real_profile,
        record=make_record(external_id="SENS-2", company="Flagging Co"),
    )
    session.flush()
    for answer in prepared.application.answers:
        if answer.question_key in SENSITIVE_KEYS:
            assert answer.is_sensitive is True, f"{answer.question_key} is not flagged sensitive"


def test_an_ai_draft_cannot_be_promoted_to_a_verified_answer(
    session: Session, real_profile: CandidateProfile
) -> None:
    """Both the service and the database must refuse it, independently."""
    bank = SavedAnswerRepository(session)
    for provenance in (
        AnswerProvenance.AI_DRAFT,
        AnswerProvenance.NEEDS_USER_INPUT,
        AnswerProvenance.RESUME_EXTRACTED,
    ):
        with pytest.raises(UnbankableAnswerError):
            bank.upsert(
                profile_id=real_profile.id,
                question_key="why_this_role",
                question="Why this role?",
                answer="A plausible sentence.",
                provenance=provenance,
            )

    from sqlalchemy.exc import IntegrityError

    session.add(
        SavedAnswer(
            profile_id=real_profile.id,
            question_key="smuggled",
            answer="bypassing the service layer",
            provenance=AnswerProvenance.AI_DRAFT,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_a_banked_answer_keeps_its_provenance_when_reused(
    session: Session, real_profile: CandidateProfile
) -> None:
    """Reuse must not launder a typed answer into a profile-verified one."""
    service = AnswerBankService(session)
    saved = service.save(
        real_profile,
        question_key="notice_period",
        answer="30 days",
        question="What is your notice period?",
    )
    assert saved.provenance is AnswerProvenance.USER_ENTERED

    prepared = _prepare(
        session,
        real_profile,
        record=make_record(external_id="REUSE-1", company="Reuse Co"),
    )
    session.flush()
    answer = next(
        row for row in prepared.application.answers if row.question_key == "notice_period"
    )
    assert answer.answer == "30 days"
    assert answer.provenance is AnswerProvenance.USER_ENTERED
    assert answer.source_field == "answer_bank:notice_period"


def test_applying_a_banked_answer_never_marks_it_profile_verified() -> None:
    """Unit-level guard on the copy helper itself."""
    saved = SavedAnswer(
        profile_id=1,
        question_key="notice_period",
        answer="Immediately available",
        provenance=AnswerProvenance.USER_ENTERED,
    )
    from app.db.models import ApplicationAnswer

    row = ApplicationAnswer(
        application_id=1,
        question="Notice period?",
        question_key="notice_period",
        requires_user_input=True,
        provenance=AnswerProvenance.NEEDS_USER_INPUT,
    )
    apply_saved_answer(row, saved)
    assert row.provenance is AnswerProvenance.USER_ENTERED
    assert row.provenance is not AnswerProvenance.PROFILE_VERIFIED
    assert row.requires_user_input is False


def test_an_edited_answer_becomes_user_entered_not_verified(
    session: Session, real_profile: CandidateProfile
) -> None:
    prepared = _prepare(
        session,
        real_profile,
        record=make_record(external_id="EDIT-1", company="Edit Co"),
    )
    session.flush()
    service = ApplicationPreparationService(session)
    target = next(
        row for row in prepared.application.answers if row.question_key == "work_authorization"
    )
    service.apply_answer_edits(prepared.application, {target.id: "Yes, Indian citizen"})
    session.flush()
    assert target.provenance is AnswerProvenance.USER_ENTERED
    assert target.requires_user_input is False
    assert target.flag_reason == ""
