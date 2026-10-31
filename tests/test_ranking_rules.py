"""Regression tests for the ranking rules added after the real-listing benchmark.

Each test names the defect it locks down. Every one of those defects was measured on
``tests/fixtures/eval_jobs_real.json`` rather than imagined: the benchmark's false-positive
rate and its high band are what exposed them.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.db.models import CandidateProfile, utcnow
from app.services.evidence import (
    SPARSE_DESCRIPTION_WORDS,
    EvidenceClass,
    analyse_description,
)
from app.services.matching import (
    INCIDENTAL_SKILLS_CEILING,
    INFERRED_SKILLS_CEILING,
    score_job,
)
from tests.conftest import make_record, persist_job

# --------------------------------------------------------------------------------------
# The evidence classifier
# --------------------------------------------------------------------------------------


def test_a_requirements_heading_separates_requirements_from_passing_mentions() -> None:
    evidence = analyse_description(
        "About us\n"
        "We are a Python shop and our customers love our Docker-based tooling.\n"
        "Requirements\n"
        "- Strong React and TypeScript\n"
        "Nice to have\n"
        "- Exposure to Kubernetes\n"
    )

    assert "react" in evidence.required
    assert "typescript" in evidence.required
    assert "kubernetes" in evidence.preferred
    assert "python" in evidence.incidental
    assert "docker" in evidence.incidental
    assert evidence.has_requirements_section is True


def test_preferred_qualifications_is_not_read_as_a_hard_requirement() -> None:
    """ "Preferred Qualifications" contains the word "qualifications"; order matters."""
    evidence = analyse_description("Preferred Qualifications\n- Go\n- Rust\n")

    assert evidence.required == []
    assert "go" in evidence.preferred


def test_a_responsibilities_heading_closes_a_requirements_block() -> None:
    """Without the neutral cues, a Requirements heading captures the whole rest of the ad."""
    evidence = analyse_description(
        "Requirements\n- Python\nResponsibilities\n- Work with AWS and Kubernetes daily\n"
    )

    assert evidence.required == ["python"]
    assert "aws" in evidence.incidental
    assert "kubernetes" in evidence.incidental


def test_a_skill_is_credited_to_its_strongest_section_only() -> None:
    evidence = analyse_description("About us\nWe write Python.\nRequirements\n- Python expertise\n")

    assert evidence.required == ["python"]
    assert "python" not in evidence.incidental
    assert evidence.classify("python") is EvidenceClass.REQUIRED


def test_the_smallest_stated_experience_bar_is_the_one_that_counts() -> None:
    """ "3+ years required, 8+ preferred" has a bar of three, not eight."""
    evidence = analyse_description(
        "Requirements\n- 3+ years of professional experience\nNice to have\n- 8+ years leading teams\n"
    )

    assert evidence.stated_min_years == 3.0


def test_a_prose_experience_bar_is_detected() -> None:
    evidence = analyse_description("At least 7 + years of relevant professional experience.")
    assert evidence.stated_min_years == 7.0


def test_an_explicit_fresher_opening_is_recorded() -> None:
    evidence = analyse_description("Freshers welcome. 2 years of internships count.")
    assert evidence.mentions_fresher_opening is True


def test_a_short_description_is_reported_as_sparse() -> None:
    assert analyse_description("Remote software engineer. Apply now.").is_sparse is True
    assert analyse_description(" ".join(["word"] * SPARSE_DESCRIPTION_WORDS)).is_sparse is False
    assert analyse_description("").is_sparse is True


# --------------------------------------------------------------------------------------
# Role-family mismatch
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "Sales Engineer, Enterprise",
        "Field Engineer, Healthcare",
        "AI Agent Support Specialist",
        "Recruiting Operations Manager",
        "PCB Design Expert",
        "Automotive Diagnostic Engineer",
    ],
)
def test_a_role_from_another_discipline_cannot_earn_title_credit(
    session: Session, profile: CandidateProfile, title: str
) -> None:
    """Regression: "AI Agent Support Specialist" scored 66.8, above the 65 threshold.

    Its title contains "AI Agent", which is one of the candidate's own skills, so token
    overlap rated it a partial title match for a customer-support job.
    """
    job = persist_job(
        session,
        make_record(
            title=title,
            external_id=f"FAM-{abs(hash(title)) % 10000}",
            location="Remote",
            required_skills=[],
            preferred_skills=[],
            description="A role at a software company.",
        ),
    )
    result = score_job(job, profile)
    title_score = result.category_scores["title"]
    detail = str(title_score["detail"])

    assert float(title_score["score"]) <= 12.0, title_score
    assert "not among the kinds of work" in detail or "shares no significant words" in detail, (
        detail
    )
    assert result.total_score < 65.0, "it must not clear the candidate's own threshold"


@pytest.mark.parametrize(
    "title",
    ["Partner Solutions Engineer", "Demo Engineer", "Revenue Systems Engineer"],
)
def test_an_unrecognised_non_software_title_still_falls_to_the_generic_cap(
    session: Session, profile: CandidateProfile, title: str
) -> None:
    """The family list is not exhaustive, so the generic-token cap remains the backstop.

    These titles name no family marker the list knows about, so they are not capped at the
    role-family level. What must still hold is that sharing only "Engineer" cannot carry
    them over the candidate's own application threshold.
    """
    job = persist_job(
        session,
        make_record(
            title=title,
            external_id=f"GEN-{abs(hash(title)) % 10000}",
            location="Remote",
            required_skills=[],
            preferred_skills=[],
            description="A role at a software company.",
        ),
    )
    result = score_job(job, profile)
    title_score = result.category_scores["title"]

    assert float(title_score["score"]) <= 25.0, title_score
    assert result.total_score < 65.0, "it must not clear the candidate's own threshold"


@pytest.mark.parametrize(
    "title",
    [
        "Software Engineer",
        "Backend Developer",
        "Python Developer",
        "Frontend Developer",
        "Full-Stack Developer",
        "AI Engineer",
        "Machine Learning Engineer",
        "Cloud Engineer",
        "DevOps Engineer",
        "Site Reliability Engineer",
        "Platform Engineer",
    ],
)
def test_software_adjacent_titles_are_not_punished_by_the_family_rule(
    session: Session, profile: CandidateProfile, title: str
) -> None:
    """The rule must fire on other disciplines only, never on adjacency within software."""
    job = persist_job(
        session,
        make_record(
            title=title,
            external_id=f"OK-{abs(hash(title)) % 10000}",
            location="Bengaluru",
            required_skills=["Python"],
            description="Build services.",
        ),
    )
    title_score = score_job(job, profile).category_scores["title"]

    assert "not among the kinds of work" not in str(title_score["detail"]), title_score
    assert float(title_score["score"]) > 12.0, title_score


# --------------------------------------------------------------------------------------
# Incidental skill mentions
# --------------------------------------------------------------------------------------


def test_skills_mentioned_only_in_passing_earn_far_less_than_requirements(
    session: Session, profile: CandidateProfile
) -> None:
    """Regression: a sales role scored 50 on skills because its customers use Python.

    The listing publishes no requirement list, so the matcher infers skills from the text.
    Before this rule every mention counted equally, which is how a tool named in a company
    blurb earned the same credit as a stated requirement.
    """
    incidental = persist_job(
        session,
        make_record(
            title="Revenue Operations Analyst",
            external_id="INC-1",
            location="Bengaluru",
            required_skills=[],
            preferred_skills=[],
            description=(
                "About us\n"
                "Our customers analyse their data with Python and SQL on AWS.\n"
                "Responsibilities\n"
                "- Own the revenue reporting calendar\n"
            ),
        ),
    )
    result = score_job(incidental, profile)
    skills = result.category_scores["skills"]

    assert float(skills["score"]) <= INCIDENTAL_SKILLS_CEILING
    assert "incidental mention" in str(skills["detail"])
    assert "mentioned only in passing" in str(skills["detail"])


def test_inferred_skills_under_a_requirements_heading_keep_the_higher_ceiling(
    session: Session, profile: CandidateProfile
) -> None:
    """Inference from a real requirements block is weak evidence, not negligible evidence."""
    job = persist_job(
        session,
        make_record(
            title="Backend Developer",
            external_id="INC-2",
            location="Bengaluru",
            required_skills=[],
            preferred_skills=[],
            description=("Requirements\n- Strong Python\n- FastAPI and PostgreSQL\n- Docker\n"),
        ),
    )
    skills = score_job(job, profile).category_scores["skills"]

    assert float(skills["score"]) > INCIDENTAL_SKILLS_CEILING
    assert float(skills["score"]) <= INFERRED_SKILLS_CEILING
    assert "under a requirements heading" in str(skills["detail"])


def test_a_published_requirement_list_is_still_taken_at_its_word(
    session: Session, profile: CandidateProfile
) -> None:
    """No ceiling and no evidence weighting apply when the employer stated requirements."""
    job = persist_job(
        session,
        make_record(
            external_id="INC-3",
            location="Bengaluru",
            required_skills=["Python", "FastAPI", "PostgreSQL"],
        ),
    )
    skills = score_job(job, profile).category_scores["skills"]

    assert float(skills["score"]) == 100.0
    assert "capped" not in str(skills["detail"])


# --------------------------------------------------------------------------------------
# Experience bars written in prose, and ATS seniority labels
# --------------------------------------------------------------------------------------


def test_an_experience_bar_written_in_prose_is_enforced(
    session: Session, profile: CandidateProfile
) -> None:
    """Regression: roles asking 5-7 years ranked in the high band for a 0.4-year candidate.

    Those listings carried no structured experience field, so the bar existed only in the
    description and was never read.
    """
    job = persist_job(
        session,
        make_record(
            title="Software Engineer - Backend",
            external_id="EXP-1",
            location="Remote",
            required_skills=["Python", "FastAPI", "PostgreSQL", "Docker", "AWS"],
            experience_raw="",
            posted_at=utcnow() - timedelta(days=1),
            description=(
                "Requirements\n"
                "- At least 7+ years of relevant professional experience\n"
                "- Python, FastAPI, PostgreSQL, Docker and AWS\n"
            ),
        ),
    )
    result = score_job(job, profile)
    experience = result.category_scores["experience"]

    assert bool(experience["assessable"]) is True
    assert float(experience["score"]) < 50.0, experience
    assert "the description asks for 7+ years" in str(experience["detail"])
    assert result.filtered_out is True
    assert any(
        "states in its description that it requires at least 7 years" in reason
        for reason in result.filter_reasons
    ), result.filter_reasons


def test_a_fresher_opening_overrides_a_years_figure_in_the_boilerplate(
    session: Session, profile: CandidateProfile
) -> None:
    job = persist_job(
        session,
        make_record(
            title="Backend Developer",
            external_id="EXP-2",
            location="Bengaluru",
            required_skills=["Python", "FastAPI"],
            experience_raw="",
            posted_at=utcnow() - timedelta(days=1),
            description=(
                "Freshers welcome.\n"
                "Our team has 10 years of combined experience building Python services.\n"
            ),
        ),
    )
    experience = score_job(job, profile).category_scores["experience"]

    assert float(experience["score"]) >= 50.0, experience


def test_a_source_supplied_seniority_label_is_used_when_no_years_are_stated(
    session: Session, profile: CandidateProfile
) -> None:
    """SmartRecruiters, Himalayas and Jobicy return a level label instead of years.

    Before this was read, the experience category was unassessable for those sources, its
    weight was redistributed, and a director-level role escaped any seniority penalty.
    """
    director = persist_job(
        session,
        make_record(
            title="Platform Specialist",
            external_id="EXP-3",
            location="Remote",
            required_skills=["Python"],
            experience_raw="Director",
            description="Own the platform.",
        ),
    )
    entry = persist_job(
        session,
        make_record(
            title="Platform Specialist",
            company="Other Co",
            external_id="EXP-4",
            location="Remote",
            required_skills=["Python"],
            experience_raw="Entry Level",
            description="Own the platform.",
        ),
    )

    director_experience = score_job(director, profile).category_scores["experience"]
    entry_experience = score_job(entry, profile).category_scores["experience"]

    assert bool(director_experience["assessable"]) is True
    assert float(director_experience["score"]) < float(entry_experience["score"])
    assert "years" in str(director_experience["detail"])


def test_the_not_applicable_level_is_treated_as_no_signal(
    session: Session, profile: CandidateProfile
) -> None:
    """SmartRecruiters returns "Not Applicable", which must not be read as a seniority."""
    job = persist_job(
        session,
        make_record(
            title="Software Engineer",
            external_id="EXP-5",
            location="Remote",
            required_skills=["Python"],
            experience_raw="Not Applicable",
            description="Build services.",
        ),
    )
    experience = score_job(job, profile).category_scores["experience"]

    assert bool(experience["assessable"]) is False


# --------------------------------------------------------------------------------------
# Relevance versus confidence
# --------------------------------------------------------------------------------------


def test_a_high_score_from_a_teaser_description_is_reported_as_low_confidence(
    session: Session, profile: CandidateProfile
) -> None:
    """Remote OK returns a truncated teaser, which can still score highly.

    The score is left alone so it stays auditable; what changes is that the result says the
    evidence behind it was thin, and the band is not allowed to claim a confident match.
    """
    job = persist_job(
        session,
        make_record(
            title="Software Engineer",
            external_id="CONF-1",
            location="Remote",
            required_skills=[],
            preferred_skills=[],
            posted_at=utcnow() - timedelta(days=1),
            description="Remote - we are hiring a Python software engineer. Apply now.",
        ),
    )
    result = score_job(job, profile)

    assert result.confidence == "low"
    assert result.band != "high"
    assert any("words" in reason for reason in result.confidence_reasons)


def test_full_evidence_earns_high_confidence(session: Session, profile: CandidateProfile) -> None:
    job = persist_job(
        session,
        make_record(
            title="Backend Developer",
            external_id="CONF-2",
            location="Bengaluru",
            required_skills=["Python", "FastAPI", "PostgreSQL"],
            preferred_skills=["Docker", "AWS"],
            experience_raw="0-2 years",
            salary_raw="8 LPA",
            posted_at=utcnow() - timedelta(days=1),
            description="Hybrid full-time role in Bengaluru building Python services.",
        ),
    )
    result = score_job(job, profile)

    assert result.confidence == "high"
    assert result.confidence_reasons == []
    assert result.evidence_coverage == 1.0
    assert result.band == "high"


def test_confidence_and_score_are_independent(session: Session, profile: CandidateProfile) -> None:
    """A listing can look like a strong match and still be impossible to judge."""
    job = persist_job(
        session,
        make_record(
            title="Python Developer",
            external_id="CONF-3",
            location="",
            required_skills=["Python", "FastAPI"],
            experience_raw="",
            posted_at=None,
            description="",
        ),
    )
    result = score_job(job, profile)

    assert result.total_score >= 80.0, "the number must be left untouched"
    assert result.confidence == "low"
    assert result.evidence_coverage < 0.7
    assert result.band == "review"


# --------------------------------------------------------------------------------------
# Defects found by expanding the benchmark to 190 real listings
# --------------------------------------------------------------------------------------


def test_a_tie_between_target_titles_prefers_the_specific_overlap(
    session: Session, profile: CandidateProfile
) -> None:
    """Regression: "Backend Engineer - Python" scored 25/100 on title.

    It tied at 42.5 against "Software Engineer", "Backend Developer" and
    "Python Developer". Keeping the first left the match resting on the generic word
    "engineer", so the generic-overlap cap applied to a genuine backend role.
    """
    job = persist_job(
        session,
        make_record(
            title="Backend Engineer - Python",
            external_id="TIE-1",
            location="Remote",
            required_skills=[],
            preferred_skills=[],
            description="Build and operate backend services for our platform team.",
        ),
    )
    result = score_job(job, profile)
    title = result.category_scores["title"]
    assert title["score"] > 40.0, f"title still capped: {title['detail']}"
    assert "generic" not in title["detail"]


def test_interchangeable_role_nouns_are_not_treated_as_different_roles(
    session: Session, profile: CandidateProfile
) -> None:
    """A listing saying "Engineer" must match a target saying "Developer"."""
    engineer = persist_job(
        session,
        make_record(
            title="Backend Engineer",
            external_id="SYN-1",
            location="Remote",
            required_skills=[],
            preferred_skills=[],
            description="Backend services work.",
        ),
    )
    developer = persist_job(
        session,
        make_record(
            title="Backend Developer",
            external_id="SYN-2",
            location="Remote",
            required_skills=[],
            preferred_skills=[],
            description="Backend services work.",
        ),
    )
    assert (
        score_job(engineer, profile).category_scores["title"]["score"]
        == score_job(developer, profile).category_scores["title"]["score"]
    )


@pytest.mark.parametrize("off_discipline", ["Technical Support Engineer", "Sales Engineer"])
def test_collapsing_role_nouns_does_not_rescue_an_off_discipline_title(
    session: Session, profile: CandidateProfile, off_discipline: str
) -> None:
    """The safety claim behind the synonym table, asserted rather than assumed."""
    job = persist_job(
        session,
        make_record(
            title=off_discipline,
            external_id=f"SYN-{abs(hash(off_discipline)) % 10000}",
            location="Remote",
            required_skills=[],
            preferred_skills=[],
            description="A role at a software company.",
        ),
    )
    result = score_job(job, profile)
    assert result.category_scores["title"]["score"] <= 25.0
    assert result.total_score < (profile.minimum_match_score or 65.0)


def test_a_prose_bar_is_enforced_even_when_a_weaker_structured_field_exists(
    session: Session, profile: CandidateProfile
) -> None:
    """Regression: a Bosch listing carried experienceLevel "Associate" and asked for 3 years.

    "Associate" normalises to a 1-year minimum, and the filter took the structured field
    whenever it existed, so the weaker figure masked the stronger and a role three years
    above the candidate stayed eligible.
    """
    job = persist_job(
        session,
        make_record(
            title="Software Engineer - Python",
            external_id="BAR-1",
            location="Bengaluru, India",
            experience_raw="Associate",
            required_skills=["python"],
            preferred_skills=[],
            description=(
                "Requirements\n"
                "- 3 years of professional software development experience\n"
                "- Strong Python\n"
            ),
            posted_at=utcnow() - timedelta(days=3),
        ),
    )
    assert job.experience_min_years is not None and job.experience_min_years < 3.0, (
        "fixture precondition: the structured field must be the weaker of the two figures"
    )
    result = score_job(job, profile)
    assert result.filtered_out
    assert any("3 years" in reason for reason in result.filter_reasons), result.filter_reasons


def test_a_listing_welcoming_freshers_overrides_a_boilerplate_years_figure(
    session: Session, profile: CandidateProfile
) -> None:
    job = persist_job(
        session,
        make_record(
            title="Software Engineer",
            external_id="BAR-2",
            location="Bengaluru, India",
            required_skills=["python"],
            preferred_skills=[],
            description=(
                "Freshers welcome. Requirements\n- 3 years of experience preferred\n- Python\n"
            ),
            posted_at=utcnow() - timedelta(days=3),
        ),
    )
    result = score_job(job, profile)
    assert not result.filtered_out, result.filter_reasons


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Staff+ Software Engineer, Memory & Search", 4),
        ("Sr. Controls Software Engineer - MBD", 3),
        ("Jr. Developer", 1),
        ("Software Engineer", None),
    ],
)
def test_trailing_punctuation_does_not_hide_a_seniority_marker(
    title: str, expected: int | None
) -> None:
    """Regression: "Staff+" and "Sr." escaped the seniority filter entirely.

    ``normalize_text`` keeps ``+`` and ``.`` so that "c++" and "node.js" survive as
    skills, which left these titles as the tokens ``staff+`` and ``sr.``. Neither matched
    a marker, so both senior roles reached the review band on real discovered listings.
    """
    from app.services.text import seniority_level

    assert seniority_level(title) == expected


def test_a_staff_plus_role_is_filtered_for_a_fresher(
    session: Session, profile: CandidateProfile
) -> None:
    job = persist_job(
        session,
        make_record(
            title="Staff+ Software Engineer, Memory & Search",
            external_id="SEN-1",
            location="Remote",
            required_skills=["python"],
            preferred_skills=[],
            description="Work on memory and search systems.",
            posted_at=utcnow() - timedelta(days=3),
        ),
    )
    result = score_job(job, profile)
    assert result.filtered_out
    assert any("seniority" in reason for reason in result.filter_reasons), result.filter_reasons
