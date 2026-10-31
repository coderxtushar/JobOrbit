"""India-first discovery: location folding, remote fencing and entry-level eligibility.

Every case here was measured against a real listing before it was written. The locations
and phrasings are the ones the configured boards actually publish — "bangalore, in" from
SmartRecruiters, "Remote, Poland" from Ashby, "Graduate Engineer Trainee" from Indian
employers — rather than invented inputs, because a normalization table tuned to invented
spellings would pass its tests and still miss the data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db.models import CandidateProfile, Job, WorkArrangement
from app.services.filters import evaluate
from app.services.normalization import parse_experience
from app.services.text import (
    INDIA_CITIES,
    INDIA_REGIONS,
    is_india_location,
    normalize_location,
    remote_scope,
)

REAL_DATASET = Path(__file__).parent / "fixtures" / "eval_jobs_real.json"


# --------------------------------------------------------------------------------------
# Location folding
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Bangalore", "bengaluru"),
        ("Bangalore Urban", "bengaluru"),
        ("Gurgaon", "gurugram"),
        ("Secunderabad", "hyderabad"),
        ("Cochin", "kochi"),
        ("Vizag", "visakhapatnam"),
        ("Mysore", "mysuru"),
        ("Baroda", "vadodara"),
        ("Trivandrum", "thiruvananthapuram"),
        ("Delhi NCR", "delhi"),
    ],
)
def test_indian_city_aliases_fold_to_one_spelling(raw: str, expected: str) -> None:
    assert normalize_location(raw) == expected


def test_a_trailing_country_code_folds_to_the_country_name() -> None:
    """SmartRecruiters publishes the ISO-2 code, so "India" as a preference matched nothing."""
    assert normalize_location("bangalore, in") == "bengaluru, india"
    assert normalize_location("Pune, Maharashtra, IN") == "pune, maharashtra, india"


def test_a_bare_in_is_not_treated_as_a_country() -> None:
    """Only a trailing segment is a country code; a lone "in" is too ambiguous to fold."""
    assert normalize_location("in") == "in"


def test_parenthesised_and_dashed_locations_normalise_alike() -> None:
    """Boards write both for the same arrangement, and they must compare equal."""
    assert normalize_location("Remote (India)") == normalize_location("Remote - India")


@pytest.mark.parametrize(
    "raw",
    [
        "Bengaluru, Karnataka, India",
        "Pune, Maharashtra",
        "Noida",
        "bangalore, in",
        "Remote (India)",
        "Greater Noida, Uttar Pradesh",
    ],
)
def test_india_locations_are_recognised_without_the_country_written_out(raw: str) -> None:
    assert is_india_location(raw)


@pytest.mark.parametrize(
    "raw", ["London, UK", "San Francisco, CA", "Remote, Poland", "Amsterdam, Netherlands", ""]
)
def test_non_india_locations_are_not_misread_as_india(raw: str) -> None:
    assert not is_india_location(raw)


def test_the_city_and_region_tables_only_overlap_where_reality_does() -> None:
    """Delhi, Chandigarh and Goa are genuinely both a city and a region, so they appear in
    both tables. Anything else in both would be a copy-paste error, and since the predicate
    unions the two sets it would never be caught by a behavioural test."""
    assert {"chandigarh", "delhi", "goa"} == INDIA_CITIES & INDIA_REGIONS


# --------------------------------------------------------------------------------------
# Remote scope
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("location", "description", "expected"),
    [
        ("Remote - India", "", "india"),
        ("Bengaluru, India", "", "india"),
        ("Remote", "", "unstated"),
        ("Remote", "We are a distributed team.", "unstated"),
        ("Remote - Engineering", "", "unstated"),
        ("Remote (US only)", "", "elsewhere"),
        ("Remote, Poland", "", "elsewhere"),
        ("Remote - EMEA", "", "elsewhere"),
        ("Remote", "This role is remote within the United States only.", "elsewhere"),
        ("Remote", "Candidates must reside in the EU.", "elsewhere"),
        ("Remote", "You must be based in India to apply.", "india"),
    ],
)
def test_remote_scope_separates_india_from_elsewhere(
    location: str, description: str, expected: str
) -> None:
    assert remote_scope(location, description) == expected


def test_an_unstated_remote_role_is_never_guessed_to_be_restricted() -> None:
    """Most employers omit the fence; reading silence as a restriction would discard matches."""
    assert remote_scope("Remote", "Join our team. Apply today.") == "unstated"


# --------------------------------------------------------------------------------------
# Entry-level phrasing
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase",
    [
        "Fresher",
        "freshers welcome",
        "new grad",
        "New Graduate",
        "recent graduates",
        "university graduate",
        "college graduate",
        "Graduate Engineer Trainee",
        "campus hire",
        "campus placement",
        "apprenticeship",
        "Entry level",
        "Trainee",
    ],
)
def test_entry_level_phrasing_resolves_to_a_zero_year_floor(phrase: str) -> None:
    """Unparsed, these were unassessable — and an unassessable category has its weight
    redistributed, which is how a senior role escaped its seniority penalty."""
    assert parse_experience(phrase)[0] == 0.0


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("less than 1 year", (0.0, 1.0)),
        ("under 2 years", (0.0, 2.0)),
        ("up to 3 years of experience", (0.0, 3.0)),
    ],
)
def test_an_upper_bound_only_phrase_is_not_read_as_a_floor(
    phrase: str, expected: tuple[float, float]
) -> None:
    """ "less than 1 year" previously returned a one-year floor — the opposite of the text,
    and enough on its own to filter the listing out for a fresher."""
    assert parse_experience(phrase) == expected


def test_a_real_years_requirement_is_still_read_as_a_floor() -> None:
    """The control: widening the entry-level vocabulary must not soften a genuine bar."""
    assert parse_experience("5+ years") == (5.0, None)
    assert parse_experience("3 to 6 years")[0] == 3.0


# --------------------------------------------------------------------------------------
# The India work-eligibility constraint
# --------------------------------------------------------------------------------------


def _remote_job(session: Session, location: str, description: str = "") -> Job:
    job = Job(
        title="Backend Engineer",
        company="Example Co",
        location=location,
        company_normalized="example co",
        location_normalized=normalize_location(location),
        description=description,
        work_arrangement=WorkArrangement.REMOTE,
        url="https://jobs.example.com/remote-backend",
        fingerprint=f"fp-{location}-{len(description)}",
    )
    session.add(job)
    session.flush()
    return job


def _india_profile(session: Session, **overrides: object) -> CandidateProfile:
    profile = session.query(CandidateProfile).first()
    if profile is None:
        profile = CandidateProfile()
        session.add(profile)
    profile.target_titles = ["Backend Developer"]
    profile.technical_skills = ["python"]
    profile.preferred_locations = ["Remote", "Bengaluru", "Gurugram"]
    profile.work_arrangements = ["remote", "hybrid", "onsite"]
    profile.open_to_relocation = True
    for field, value in overrides.items():
        setattr(profile, field, value)
    session.flush()
    return profile


def test_a_fenced_remote_role_is_kept_until_the_constraint_is_switched_on(
    session: Session,
) -> None:
    """Default behaviour is unchanged: an unstated work authorization is not evidence of
    ineligibility, which is the project's own rule for every hard filter."""
    job = _remote_job(session, "Remote, Poland")
    profile = _india_profile(session, requires_india_work_eligibility=False)
    assert evaluate(job, profile).eligible


def test_a_fenced_remote_role_is_excluded_once_the_constraint_is_on(session: Session) -> None:
    job = _remote_job(session, "Remote, Poland")
    profile = _india_profile(session, requires_india_work_eligibility=True)
    outcome = evaluate(job, profile)
    assert not outcome.eligible
    assert any("location" in reason for reason in outcome.reasons), outcome.reasons


def test_the_constraint_keeps_remote_roles_that_are_open_or_india_based(
    session: Session,
) -> None:
    """The constraint must not collapse into "no remote jobs"."""
    profile = _india_profile(session, requires_india_work_eligibility=True)
    for location, description in [
        ("Remote", ""),
        ("Remote - India", ""),
        ("Remote", "You must be eligible to work in India."),
    ]:
        job = _remote_job(session, location, description)
        assert evaluate(job, profile).eligible, f"{location!r} should stay eligible"


def test_an_explicit_experience_ceiling_excludes_a_listing_above_it(session: Session) -> None:
    job = _remote_job(session, "Bengaluru, India")
    job.experience_min_years = 4.0
    profile = _india_profile(session, max_required_experience_years=2.0, years_experience=0.5)
    outcome = evaluate(job, profile)
    assert not outcome.eligible
    assert any("maximum you set" in reason for reason in outcome.reasons), outcome.reasons


def test_without_a_ceiling_the_relative_tolerance_still_applies(session: Session) -> None:
    """The control: the default stays relative to the candidate's own experience."""
    job = _remote_job(session, "Bengaluru, India")
    job.experience_min_years = 2.0
    profile = _india_profile(session, max_required_experience_years=None, years_experience=0.5)
    assert evaluate(job, profile).eligible


# --------------------------------------------------------------------------------------
# Coverage measurement over the real harvested listings
# --------------------------------------------------------------------------------------


def _real_rows() -> list[dict]:
    return json.loads(REAL_DATASET.read_text(encoding="utf-8"))["jobs"]


def test_the_real_dataset_records_how_little_of_it_is_india_located() -> None:
    """The headline coverage finding, asserted so it cannot quietly drift.

    The configured ATS boards are overwhelmingly US and EU employers. Measuring this is
    the point: the shortage of suitable Indian roles is a *source coverage* problem, and
    an assertion here stops a future ranking change being credited for fixing it.
    """
    rows = _real_rows()
    india = [row for row in rows if is_india_location(row["record"].get("location") or "")]
    assert len(rows) >= 150, "the benchmark is meant to hold at least 150 real listings"
    assert india, "the dataset must contain some India-located listings to measure against"
    assert len(india) / len(rows) < 0.5, (
        "if most of the harvested pool is India-located the coverage finding has changed "
        "and the validation report needs re-measuring"
    )


def test_every_remote_row_classifies_without_error() -> None:
    """A classifier that raises on real data is worse than one that returns 'unstated'."""
    scopes = {
        remote_scope(row["record"].get("location") or "", row["record"].get("description") or "")
        for row in _real_rows()
    }
    assert scopes <= {"india", "elsewhere", "unstated"}
    assert "elsewhere" in scopes, (
        "the harvested pool is known to contain region-fenced remote roles"
    )
