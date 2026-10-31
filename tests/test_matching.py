"""Matching and filtering: scoring, edge cases, and fresher versus senior roles."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.db.models import CandidateProfile, JobStatus, utcnow
from app.db.repositories import ProfileRepository
from app.schemas.profile import ScoringWeights
from app.services.filters import FilterContext, evaluate
from app.services.matching import (
    INFERRED_SKILLS_CEILING,
    MINIMUM_COVERAGE_FOR_HIGH,
    REVIEW_BAND_MINIMUM,
    band_for,
    score_job,
)
from app.services.scoring import ScoringService
from tests.conftest import make_record, persist_job

_DISTINCT_TITLES = ("payments", "billing", "search", "identity", "messaging")


def test_a_well_matched_fresher_job_scores_high(
    session: Session, profile: CandidateProfile
) -> None:
    job = persist_job(
        session,
        make_record(
            title="Backend Developer",
            location="Bengaluru",
            required_skills=["Python", "FastAPI", "PostgreSQL"],
            preferred_skills=["Docker", "AWS"],
            experience_raw="0-2 years",
            posted_at=utcnow() - timedelta(days=1),
            description="Hybrid in Bengaluru. Full-time.",
        ),
    )
    result = score_job(job, profile)

    assert result.total_score >= 80
    assert result.band == "high"
    assert not result.filtered_out
    assert {"python", "fastapi", "postgresql"} <= set(result.matched_skills)
    assert result.missing_required_skills == []


def test_a_senior_role_is_filtered_out_for_a_fresher(
    session: Session, profile: CandidateProfile
) -> None:
    job = persist_job(
        session,
        make_record(
            title="Senior Principal Machine Learning Architect",
            company="DeepCorp",
            location="Bengaluru",
            required_skills=["Kubernetes", "PyTorch"],
            experience_raw="10+ years",
            external_id="SR-1",
        ),
    )
    result = score_job(job, profile)

    assert result.filtered_out
    assert any("seniority" in reason for reason in result.filter_reasons)
    assert any("10 years" in reason or "10+" in reason for reason in result.filter_reasons)


def test_missing_skills_are_phrased_as_absent_from_the_profile_not_as_a_deficiency(
    session: Session, profile: CandidateProfile
) -> None:
    job = persist_job(
        session,
        make_record(required_skills=["Python", "Rust", "Erlang"], external_id="MS-1"),
    )
    result = score_job(job, profile)

    assert set(result.missing_required_skills) == {"rust", "erlang"}
    explanation = " ".join(result.explanation).lower()
    assert "not in your profile" in explanation
    assert "not a judgement that you lack them" in explanation


def test_an_unassessable_category_is_excluded_from_the_weighting(
    session: Session, profile: CandidateProfile
) -> None:
    """A job with no posting date must not be dragged toward the neutral midpoint."""
    job = persist_job(
        session,
        make_record(
            title="Backend Developer",
            location="Bengaluru",
            required_skills=["Python", "FastAPI"],
            posted_at=None,
            external_id="NF-1",
        ),
    )
    result = score_job(job, profile)
    freshness = result.category_scores["freshness"]

    assert freshness["assessable"] is False
    assert freshness["weight"] == 0.0
    assert sum(category["weight"] for category in result.category_scores.values()) == pytest.approx(
        1.0
    )


def test_a_job_with_no_stated_skills_cannot_be_scored_on_skills(
    session: Session, profile: CandidateProfile
) -> None:
    job = persist_job(
        session,
        make_record(required_skills=[], preferred_skills=[], description="", external_id="NS-1"),
    )
    result = score_job(job, profile)
    assert result.category_scores["skills"]["assessable"] is False


def test_an_empty_profile_does_not_crash_and_reports_what_it_cannot_assess(
    session: Session,
) -> None:
    blank = ProfileRepository(session).get_or_create_default()
    session.commit()
    job = persist_job(session, make_record(external_id="EB-1"))
    result = score_job(job, blank)

    assert 0 <= result.total_score <= 100
    assert result.category_scores["skills"]["assessable"] is False
    assert result.category_scores["title"]["assessable"] is False
    assert "no technical skills" in result.category_scores["skills"]["detail"]


def test_inferred_requirements_are_reported_as_uncertain(
    session: Session, profile: CandidateProfile
) -> None:
    job = persist_job(
        session,
        make_record(
            required_skills=[],
            preferred_skills=[],
            description="You will work with Python, Docker and Kubernetes every day.",
            external_id="UC-1",
        ),
    )
    result = score_job(job, profile)

    assert result.uncertain_requirements
    assert any("inferred" in line for line in result.explanation)


def test_freshness_decays_with_age(session: Session, profile: CandidateProfile) -> None:
    fresh = persist_job(
        session, make_record(external_id="F-1", posted_at=utcnow() - timedelta(days=1))
    )
    older = persist_job(
        session,
        make_record(
            external_id="F-2",
            title="Backend Engineer",
            company="Beta Corp",
            url="https://jobs.example.com/view/2",
            description="A different role entirely, building Python services at Beta.",
            posted_at=utcnow() - timedelta(days=25),
        ),
    )
    assert (
        score_job(fresh, profile).category_scores["freshness"]["score"]
        > score_job(older, profile).category_scores["freshness"]["score"]
    )


def test_configurable_weights_change_the_total(session: Session, profile: CandidateProfile) -> None:
    job = persist_job(
        session,
        make_record(
            title="Completely Unrelated Librarian Role",
            required_skills=["Python", "FastAPI", "PostgreSQL"],
            location="Bengaluru",
            external_id="W-1",
        ),
    )
    baseline = score_job(job, profile).total_score

    ProfileRepository(session).update(
        profile,
        {
            "scoring_weights": ScoringWeights(
                skills=90, title=1, experience=1, location=1, freshness=1, preferences=1
            ).model_dump()
        },
    )
    session.commit()
    skills_heavy = score_job(job, profile).total_score

    assert skills_heavy > baseline


def test_weights_are_normalized_so_absolute_magnitude_does_not_matter(
    session: Session, profile: CandidateProfile
) -> None:
    job = persist_job(session, make_record(external_id="N-1", location="Bengaluru"))
    ProfileRepository(session).update(
        profile,
        {
            "scoring_weights": ScoringWeights(
                skills=35, title=25, experience=15, location=10, freshness=10, preferences=5
            ).model_dump()
        },
    )
    session.commit()
    small = score_job(job, profile).total_score

    ProfileRepository(session).update(
        profile,
        {
            "scoring_weights": ScoringWeights(
                skills=70, title=50, experience=30, location=20, freshness=20, preferences=10
            ).model_dump()
        },
    )
    session.commit()
    doubled = score_job(job, profile).total_score

    assert small == pytest.approx(doubled)


def test_all_zero_weights_are_rejected() -> None:
    with pytest.raises(ValueError):
        ScoringWeights(skills=0, title=0, experience=0, location=0, freshness=0, preferences=0)


@pytest.mark.parametrize(
    ("score", "band"),
    [
        (100.0, "high"),
        (80.0, "high"),
        (79.9, "review"),
        (65.0, "review"),
        (64.9, "low"),
        (0.0, "low"),
    ],
)
def test_band_thresholds(score: float, band: str) -> None:
    assert band_for(score) == band
    assert REVIEW_BAND_MINIMUM == 65.0


# --------------------------------------------------------------------------------------
# Hard filters
# --------------------------------------------------------------------------------------


def test_excluded_company_is_filtered_regardless_of_legal_suffix(
    session: Session, profile: CandidateProfile
) -> None:
    ProfileRepository(session).update(profile, {"excluded_companies": ["Acme"]})
    session.commit()
    job = persist_job(session, make_record(company="Acme Technologies Pvt Ltd", external_id="X-1"))
    outcome = evaluate(job, profile)

    assert not outcome.eligible
    assert any("excluded company" in reason for reason in outcome.reasons)


def test_excluded_keyword_in_the_description_is_filtered(
    session: Session, profile: CandidateProfile
) -> None:
    ProfileRepository(session).update(profile, {"excluded_keywords": ["unpaid"]})
    session.commit()
    job = persist_job(
        session,
        make_record(description="This is an unpaid internship opportunity.", external_id="X-2"),
    )
    assert not evaluate(job, profile).eligible


def test_already_applied_jobs_are_filtered(session: Session, profile: CandidateProfile) -> None:
    job = persist_job(session, make_record(external_id="X-3"))
    outcome = evaluate(job, profile, FilterContext(already_applied=True))

    assert not outcome.eligible
    assert any("already applied" in reason for reason in outcome.reasons)


def test_expired_jobs_are_filtered(session: Session, profile: CandidateProfile) -> None:
    job = persist_job(session, make_record(external_id="X-4"))
    job.status = JobStatus.EXPIRED
    session.flush()
    assert not evaluate(job, profile).eligible


def test_a_stale_posting_is_filtered_by_the_age_limit(
    session: Session, profile: CandidateProfile
) -> None:
    job = persist_job(
        session, make_record(external_id="X-5", posted_at=utcnow() - timedelta(days=120))
    )
    outcome = evaluate(job, profile)

    assert not outcome.eligible
    assert any("older than your 30-day limit" in reason for reason in outcome.reasons)


def test_a_missing_posting_date_is_noted_but_never_causes_rejection(
    session: Session, profile: CandidateProfile
) -> None:
    """Absence of a date is not evidence of staleness."""
    job = persist_job(session, make_record(external_id="X-6", posted_at=None, location="Bengaluru"))
    outcome = evaluate(job, profile)

    assert outcome.eligible
    assert any("no posting date" in note for note in outcome.notes)


def test_unknown_location_does_not_cause_rejection(
    session: Session, profile: CandidateProfile
) -> None:
    job = persist_job(session, make_record(external_id="X-7", location=""))
    assert evaluate(job, profile).eligible


def test_remote_jobs_pass_the_location_filter_when_remote_is_acceptable(
    session: Session, profile: CandidateProfile
) -> None:
    job = persist_job(
        session,
        make_record(external_id="X-8", location="Remote", description="Fully remote role."),
    )
    assert evaluate(job, profile).eligible


def test_relocation_willingness_rescues_an_out_of_area_job(
    session: Session, profile: CandidateProfile
) -> None:
    job = persist_job(session, make_record(external_id="X-9", location="Chennai"))
    assert not evaluate(job, profile).eligible

    ProfileRepository(session).update(profile, {"open_to_relocation": True})
    session.commit()
    assert evaluate(job, profile).eligible


def test_unwanted_employment_type_is_filtered_but_unknown_is_not(
    session: Session, profile: CandidateProfile
) -> None:
    contract = persist_job(
        session,
        make_record(
            external_id="X-10",
            location="Bengaluru",
            title="Backend Developer",
            description="This is a 6 month contract role.",
        ),
    )
    outcome = evaluate(contract, profile)
    assert not outcome.eligible
    assert any("employment type" in reason for reason in outcome.reasons)

    unknown = persist_job(
        session,
        make_record(
            external_id="X-11",
            location="Bengaluru",
            title="Backend Developer",
            company="Other Co",
            url="https://jobs.example.com/view/11",
            description="A role building Python services with no stated engagement type.",
        ),
    )
    assert evaluate(unknown, profile).eligible


def test_filtered_jobs_are_still_scored_and_explained(
    session: Session, profile: CandidateProfile
) -> None:
    """An excluded job must say why, not silently vanish."""
    job = persist_job(session, make_record(external_id="X-12", location="Chennai"))
    result = score_job(job, profile)

    assert result.filtered_out
    assert result.filter_reasons
    assert result.total_score >= 0
    assert result.explanation


# --------------------------------------------------------------------------------------
# Scoring honesty: inferred evidence and partial coverage (release-hardening regressions)
# --------------------------------------------------------------------------------------


def test_inferred_skills_cannot_score_a_perfect_match(
    session: Session, profile: CandidateProfile
) -> None:
    """A listing that published no requirements must not yield a full skills score.

    Regression: a job with an empty requirement list had its skills inferred from the
    description by keyword match, then scored 100/100 on "0/0 stated requirements", which
    turned absence of data into apparent certainty.
    """
    job = persist_job(
        session,
        make_record(
            external_id="INF-1",
            title="Cloud Engineer",
            location="Bengaluru",
            required_skills=[],
            preferred_skills=[],
            description="Platform tooling with AWS and Docker.",
        ),
    )
    result = score_job(job, profile)
    skills = result.category_scores["skills"]

    assert skills["score"] <= INFERRED_SKILLS_CEILING
    assert "capped" in skills["detail"]
    assert "inferred" in skills["detail"]


def test_stated_requirements_are_not_capped(session: Session, profile: CandidateProfile) -> None:
    """The cap must apply only to inferred evidence, never to a real requirement list."""
    job = persist_job(
        session,
        make_record(
            external_id="INF-2",
            location="Bengaluru",
            required_skills=["Python", "FastAPI", "PostgreSQL"],
        ),
    )
    skills = score_job(job, profile).category_scores["skills"]
    assert skills["score"] == 100.0
    assert "capped" not in skills["detail"]


def test_a_score_from_a_minority_of_the_signal_is_not_called_a_high_match(
    session: Session, profile: CandidateProfile
) -> None:
    """Regression: a listing stating only a title ranked first as a confident high match."""
    job = persist_job(
        session,
        make_record(
            external_id="COV-1",
            title="Python Developer",
            location="",
            required_skills=["Python", "FastAPI"],
            experience_raw="",
            posted_at=None,
            description="",
        ),
    )
    result = score_job(job, profile)
    assessable = [name for name, data in result.category_scores.items() if data["assessable"]]

    assert len(assessable) < len(result.category_scores)
    assert result.total_score >= 80, "the number itself must be left untouched"
    assert result.band != "high"
    assert any("could be assessed" in line for line in result.explanation)


def test_full_coverage_still_earns_a_high_band(session: Session, profile: CandidateProfile) -> None:
    """The demotion must not punish a job that supplied everything needed to judge it."""
    job = persist_job(
        session,
        make_record(
            external_id="COV-2",
            title="Backend Developer",
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
    unassessable = [name for name, data in result.category_scores.items() if not data["assessable"]]

    assert unassessable == []
    assert result.total_score >= 80
    assert result.band == "high"
    assert MINIMUM_COVERAGE_FOR_HIGH < 1.0


def test_scoring_new_only_makes_progress_instead_of_rescoring_the_same_jobs(
    session: Session, profile: CandidateProfile
) -> None:
    """Regression: "Score new only" never progressed past the first batch.

    The query listed DISCOVERED, SCORED and FILTERED_OUT, which includes everything
    already scored, so each call returned the same first page by discovery date. On a
    7,791-job database that left 5,791 jobs permanently unscored while every response
    reported success.
    """
    service = ScoringService(session)
    for index in range(5):
        persist_job(
            session,
            make_record(
                external_id=f"PROG-{index}",
                title=f"Backend Developer {_DISTINCT_TITLES[index]}",
                description=f"Build {_DISTINCT_TITLES[index]} services with Python.",
                url=f"https://jobs.example.com/prog/{index}",
            ),
        )

    first = service.score_many(profile)
    assert first.scored == 5
    assert first.remaining == 0

    second = service.score_many(profile)
    assert second.scored == 0, "already-scored jobs must not be returned again"

    persist_job(
        session,
        make_record(
            external_id="PROG-new",
            title="Python Developer",
            url="https://jobs.example.com/prog/new",
        ),
    )
    third = service.score_many(profile)
    assert third.scored == 1, "a newly discovered job must be picked up"


def test_rescore_all_still_revisits_every_job(session: Session, profile: CandidateProfile) -> None:
    service = ScoringService(session)
    for index in range(3):
        persist_job(
            session,
            make_record(
                external_id=f"RE-{index}",
                title=f"Backend Developer {_DISTINCT_TITLES[index]}",
                description=f"Build {_DISTINCT_TITLES[index]} services with Python.",
                url=f"https://jobs.example.com/re/{index}",
            ),
        )
    service.score_many(profile)
    again = service.score_many(profile, rescore_all=True)
    assert again.scored == 3


def test_within_a_band_a_low_confidence_row_ranks_below_a_well_evidenced_one(
    session: Session, profile: CandidateProfile
) -> None:
    """Regression: three rows whose fields were each one character topped the review band.

    They scored 100.0 from the single category that could be assessed (20% coverage, low
    confidence) and sat above fully-assessed matches at 71-77 on real data. The band gate
    had already demoted them; ordering inside the band was still score-only.
    """
    from app.db.repositories import JobQuery, JobRepository

    content_free = persist_job(
        session,
        make_record(
            external_id="ORD-1",
            title="z",
            company="y",
            location="r",
            description="",
            required_skills=[],
            preferred_skills=[],
            url="https://jobs.example.com/ord/1",
        ),
    )
    evidenced = persist_job(
        session,
        make_record(
            external_id="ORD-2",
            title="Backend Developer",
            company="Acme Systems",
            location="Bengaluru, India",
            required_skills=["python", "fastapi", "postgresql"],
            preferred_skills=["docker"],
            description=(
                "Requirements\n- Python\n- FastAPI\n- PostgreSQL\nNice to have\n- Docker\n"
            ),
            posted_at=utcnow() - timedelta(days=2),
            url="https://jobs.example.com/ord/2",
        ),
    )
    ScoringService(session).score_many(profile, job_ids=[content_free.id, evidenced.id])
    session.flush()

    ordered = JobRepository(session).list(
        JobQuery(limit=10, sort_by="score", profile_id=profile.id)
    )
    positions = {job.id: index for index, job in enumerate(ordered)}
    assert positions[evidenced.id] < positions[content_free.id], (
        "a fully-evidenced match must outrank a content-free one in the same band"
    )
