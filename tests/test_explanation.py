"""Grounded match explanations.

These assert what the *user* is told, which is a separate guarantee from what the scorer
computes: a job can be correctly demoted and still be useless if the screen does not say
why. Every case below is one of the false positives the ranking work was built to catch.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.db.models import CandidateProfile, Job
from app.services.evidence import analyse_description
from app.services.explanation import (
    STATUS_IN_PROFILE,
    STATUS_NOT_IN_LISTING,
    STATUS_NOT_IN_PROFILE,
    STATUS_RELATED,
    StoredMatch,
    build_explanation,
)
from app.services.matching import score_job
from tests.conftest import persist_job


def _explain(session: Session, profile: CandidateProfile, **overrides: Any):
    job = persist_job(session, **overrides)
    match = score_job(job, profile)
    return job, match, build_explanation(job, profile, match)


def _section(explanation, key: str):
    for section in explanation.sections:
        if section.key == key:
            return section
    raise AssertionError(f"no section {key!r}")


def _text(explanation, key: str) -> str:
    return " ".join(
        finding.statement + " " + finding.quote for finding in _section(explanation, key).findings
    ).lower()


def test_every_section_is_present_for_a_scored_job(
    session: Session, profile: CandidateProfile
) -> None:
    _job, _match, explanation = _explain(
        session,
        profile,
        title="Backend Engineer",
        required_skills=["Python", "SQL"],
        description="Requirements\n- Python and SQL\n",
    )

    assert [section.key for section in explanation.sections] == [
        "strong_matches",
        "missing_requirements",
        "experience_fit",
        "location_fit",
        "evidence_quality",
        "resume_relevance",
        "downgrades",
    ]


def test_a_matched_skill_is_quoted_from_the_listings_own_words(
    session: Session, profile: CandidateProfile
) -> None:
    profile.technical_skills = ["Python"]
    _job, _match, explanation = _explain(
        session,
        profile,
        external_id="Q-1",
        title="Python Developer",
        required_skills=["Python"],
        description="Requirements\n- Strong commercial Python experience\n",
    )

    strong = _section(explanation, "strong_matches")
    quoted = [finding for finding in strong.findings if finding.quote]
    assert quoted, "a listing-sourced finding must carry the span it was read from"
    assert "strong commercial python experience" in quoted[0].quote.lower()
    assert quoted[0].source == "listing"


def test_a_skill_sharing_only_a_name_is_reported_as_related_not_matched(
    session: Session, profile: CandidateProfile
) -> None:
    """Holding React is not holding React Native, and the screen must not blur the two."""
    profile.technical_skills = ["React"]
    _job, _match, explanation = _explain(
        session,
        profile,
        external_id="Q-2",
        title="Frontend Developer",
        required_skills=["React Native"],
        description="Requirements\n- React Native in production\n",
    )

    statuses = {finding.skill: finding.status for finding in explanation.skills}
    assert statuses["react native"] == STATUS_RELATED
    related = next(item for item in explanation.skills if item.skill == "react native")
    assert related.related_to == "react"
    assert "not counted as a match" in related.note
    assert "react native" in _text(explanation, "missing_requirements")


def test_profile_skills_the_listing_never_mentions_are_their_own_category(
    session: Session, profile: CandidateProfile
) -> None:
    profile.technical_skills = ["Python", "Terraform"]
    _job, _match, explanation = _explain(
        session,
        profile,
        external_id="Q-3",
        required_skills=["Python"],
        description="Requirements\n- Python\n",
    )

    by_skill = {finding.skill: finding.status for finding in explanation.skills}
    assert by_skill["python"] == STATUS_IN_PROFILE
    assert by_skill["terraform"] == STATUS_NOT_IN_LISTING


def test_a_support_role_naming_ai_says_which_discipline_it_belongs_to(
    session: Session, profile: CandidateProfile
) -> None:
    _job, match, explanation = _explain(
        session,
        profile,
        external_id="Q-4",
        title="AI Agent Support Specialist",
        description=(
            "About the role\nYou will triage tickets for our AI agent platform.\n"
            "Requirements\n- Excellent written communication\n"
        ),
    )

    downgrades = _text(explanation, "downgrades")
    assert "support" in downgrades
    assert "not among the kinds of work" in downgrades
    assert match.band != "high"


def test_a_senior_bar_written_in_prose_is_quoted_in_the_experience_section(
    session: Session, profile: CandidateProfile
) -> None:
    _job, _match, explanation = _explain(
        session,
        profile,
        external_id="Q-5",
        title="Software Engineer",
        experience_raw="",
        description=(
            "Requirements\n- At least 8 years of professional experience building "
            "distributed systems\n"
        ),
    )

    text = _text(explanation, "experience_fit")
    assert "8 years" in text
    quotes = [finding.quote for finding in _section(explanation, "experience_fit").findings]
    assert any("8 years" in quote for quote in quotes if quote)


def test_a_content_free_listing_reports_thin_evidence_rather_than_a_confident_match(
    session: Session, profile: CandidateProfile
) -> None:
    _job, match, explanation = _explain(
        session,
        profile,
        external_id="Q-6",
        title="Software Engineer",
        description="We are hiring a software engineer. Apply now.",
        location="",
        posted_at=None,
    )

    quality = _text(explanation, "evidence_quality")
    assert "confidence" in quality
    assert "words" in quality
    assert match.confidence != "high"
    if match.total_score >= 80:
        assert match.band == "review"
        assert "held at" in _text(explanation, "downgrades")


def test_a_foreign_location_names_the_place_and_the_preference_it_missed(
    session: Session, profile: CandidateProfile
) -> None:
    _job, _match, explanation = _explain(
        session,
        profile,
        external_id="Q-7",
        title="Backend Engineer",
        location="Zurich, Switzerland",
        required_skills=["Python"],
        description="Requirements\n- Python\n",
    )

    text = _text(explanation, "location_fit")
    assert "zurich" in text
    assert "preferences" in text


def test_an_incidental_mention_is_labelled_as_passing_not_as_a_requirement(
    session: Session, profile: CandidateProfile
) -> None:
    profile.technical_skills = ["Python"]
    _job, _match, explanation = _explain(
        session,
        profile,
        external_id="Q-8",
        title="Software Engineer",
        required_skills=[],
        preferred_skills=["Python"],
        description=(
            "About us\nOur customers automate their work with Python scripts.\n"
            "Responsibilities\n- Talk to customers daily\n"
        ),
    )

    python = next(item for item in explanation.skills if item.skill == "python")
    assert python.evidence_class == "incidental"
    assert "only in passing" in python.note


def test_a_filtered_job_states_the_filter_reason(
    session: Session, profile: CandidateProfile
) -> None:
    profile.excluded_companies = ["BadCorp"]
    _job, match, explanation = _explain(
        session,
        profile,
        external_id="Q-9",
        company="BadCorp",
        title="Backend Engineer",
    )

    assert match.filtered_out
    assert "excluded by your filters" in _text(explanation, "downgrades")


def test_nothing_held_back_says_so_instead_of_rendering_an_empty_list(
    session: Session, profile: CandidateProfile
) -> None:
    profile.technical_skills = ["Python", "SQL"]
    _job, _match, explanation = _explain(
        session,
        profile,
        external_id="Q-10",
        title="Backend Developer",
        location="Bengaluru, India",
        required_skills=["Python", "SQL"],
        description="Requirements\n- Python and SQL\n",
    )

    downgrades = _section(explanation, "downgrades")
    if not downgrades.findings:
        assert downgrades.empty_note


def test_an_unknown_experience_bar_is_reported_as_unknown_not_as_open(
    session: Session, profile: CandidateProfile
) -> None:
    _job, _match, explanation = _explain(
        session,
        profile,
        external_id="Q-11",
        title="Software Engineer",
        experience_raw="",
        description="Requirements\n- Enthusiasm\n",
    )

    text = _text(explanation, "experience_fit")
    assert "unknown" in text


def test_the_explanation_never_invents_a_skill_the_profile_does_not_record(
    session: Session, profile: CandidateProfile
) -> None:
    profile.technical_skills = ["Python"]
    _job, _match, explanation = _explain(
        session,
        profile,
        external_id="Q-12",
        required_skills=["Python", "Rust", "Elixir"],
        description="Requirements\n- Python, Rust and Elixir\n",
    )

    claimed = {item.skill for item in explanation.skills if item.status == STATUS_IN_PROFILE}
    assert claimed == {"python"}
    absent = {item.skill for item in explanation.skills if item.status == STATUS_NOT_IN_PROFILE}
    assert {"rust", "elixir"} <= absent
    for finding in explanation.skills:
        if finding.status == STATUS_NOT_IN_PROFILE:
            assert "not found in your profile" in finding.note


def test_a_stored_match_row_explains_the_same_score_it_recorded(
    session: Session, profile: CandidateProfile
) -> None:
    """The screen must describe the stored score, not a freshly computed different one."""
    from app.services.scoring import ScoringService

    job = persist_job(session, external_id="Q-13", required_skills=["Python"])
    row = ScoringService(session).score_one(job, profile)
    session.flush()

    view = StoredMatch.from_row(row)
    assert view.total_score == row.total_score
    assert view.band == row.band
    assert view.confidence == row.confidence

    explanation = build_explanation(job, profile, view)
    assert explanation.job_id == job.id
    assert _section(explanation, "evidence_quality").findings


def test_spans_are_clipped_so_one_long_paragraph_cannot_flood_the_screen() -> None:
    long_line = "Requirements\n- " + ("Python " * 200)
    evidence = analyse_description(long_line)

    assert evidence.spans["python"].endswith("…")
    assert len(evidence.spans["python"]) <= 220


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("Requirements\n- at least 5 years of experience\n", "5 years"),
        ("Requirements\n- minimum of 3 years\n", "3 years"),
        ("Requirements\n- 7+ years of relevant experience\n", "7 years"),
    ],
)
def test_the_experience_phrase_is_reported_with_the_number(description: str, expected: str) -> None:
    evidence = analyse_description(description)

    assert evidence.years_phrase is not None
    assert expected.split()[0] in evidence.years_phrase


def test_the_api_returns_grounded_sections_for_a_scored_job(client, session: Session) -> None:
    job = persist_job(session, external_id="API-1", required_skills=["Python"])
    session.commit()

    scored = client.post("/api/jobs/score", json={"job_ids": [job.id]})
    assert scored.status_code == 200

    response = client.get(f"/api/jobs/{job.id}/explanation")
    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == job.id
    assert {section["key"] for section in body["sections"]} == {
        "strong_matches",
        "missing_requirements",
        "experience_fit",
        "location_fit",
        "evidence_quality",
        "resume_relevance",
        "downgrades",
    }
    for section in body["sections"]:
        for finding in section["findings"]:
            assert finding["source"] in {"listing", "profile", "scoring"}


def test_the_api_refuses_to_explain_an_unscored_job(client, session: Session) -> None:
    job = persist_job(session, external_id="API-2")
    session.commit()

    response = client.get(f"/api/jobs/{job.id}/explanation")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_scored"


def test_explaining_a_missing_job_is_a_404(client) -> None:
    response = client.get("/api/jobs/999999/explanation")

    assert response.status_code == 404


def test_explanation_quotes_are_escaped_when_rendered(session: Session, profile) -> None:
    """Job text is untrusted; the quote carried to the UI must be inert markup."""
    job: Job = persist_job(
        session,
        external_id="API-3",
        required_skills=["Python"],
        description="Requirements\n- <script>alert(1)</script> Python\n",
    )
    match = score_job(job, profile)
    explanation = build_explanation(job, profile, match)

    quotes = [item.quote for item in explanation.skills if item.quote]
    assert any("<script>" in quote for quote in quotes), "the raw span is preserved as data"

    from ui.theme import esc

    assert "&lt;script&gt;" in esc(quotes[0])
