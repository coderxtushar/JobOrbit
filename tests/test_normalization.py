"""Normalization: salary, experience, dates, timezones and missing data."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.db.models import EmploymentType, WorkArrangement
from app.services.normalization import (
    extract_skills_from_description,
    normalize_record,
    parse_employment_type,
    parse_experience,
    parse_posted_at,
    parse_salary,
    parse_work_arrangement,
)
from app.services.text import normalize_company, normalize_location
from tests.conftest import make_record

REFERENCE = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("raw", "expected_min", "expected_max"),
    [
        ("6-10 LPA", 600_000, 1_000_000),
        ("₹12,00,000 per annum", 1_200_000, None),
        ("8 lakhs", 800_000, None),
        ("1.2 crore", 12_000_000, None),
        ("$120k - $150k", 120_000, 150_000),
        ("Not disclosed", None, None),
        ("Best in industry", None, None),
        ("", None, None),
    ],
)
def test_salary_parsing(raw: str, expected_min: int | None, expected_max: int | None) -> None:
    low, high, _ = parse_salary(raw)
    assert low == expected_min
    assert high == expected_max


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0-2 years", (0.0, 2.0)),
        ("2 to 5 yrs", (2.0, 5.0)),
        ("5+ years", (5.0, None)),
        ("Freshers welcome", (0.0, None)),
        ("entry-level", (0.0, None)),
        ("3 years", (3.0, 3.0)),
        ("Not specified", (None, None)),
        ("", (None, None)),
    ],
)
def test_experience_parsing(raw: str, expected: tuple) -> None:
    assert parse_experience(raw) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Remote role", WorkArrangement.REMOTE),
        ("Work from home", WorkArrangement.REMOTE),
        ("Hybrid in Bengaluru", WorkArrangement.HYBRID),
        ("Work from office", WorkArrangement.ONSITE),
        ("Bengaluru", WorkArrangement.UNKNOWN),
    ],
)
def test_work_arrangement_parsing(text: str, expected: WorkArrangement) -> None:
    assert parse_work_arrangement(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Summer internship", EmploymentType.INTERNSHIP),
        ("Full-time permanent role", EmploymentType.FULL_TIME),
        ("6 month contract", EmploymentType.CONTRACT),
        ("Part time work", EmploymentType.PART_TIME),
        ("Software Engineer", EmploymentType.UNKNOWN),
    ],
)
def test_employment_type_parsing(text: str, expected: EmploymentType) -> None:
    assert parse_employment_type(text) == expected


def test_relative_dates_resolve_against_the_reference_and_are_flagged_approximate() -> None:
    resolved, approximate = parse_posted_at("3 days ago", REFERENCE)
    assert resolved == REFERENCE - timedelta(days=3)
    assert approximate is True


def test_today_and_yesterday_resolve() -> None:
    today, approximate = parse_posted_at("Today", REFERENCE)
    assert today == REFERENCE and approximate
    yesterday, _ = parse_posted_at("yesterday", REFERENCE)
    assert yesterday == REFERENCE - timedelta(days=1)


def test_absolute_dates_are_exact_not_approximate() -> None:
    resolved, approximate = parse_posted_at("2026-10-01", REFERENCE)
    assert resolved == datetime(2026, 10, 1, tzinfo=UTC)
    assert approximate is False


def test_naive_datetimes_are_interpreted_as_utc() -> None:
    resolved, _ = parse_posted_at(datetime(2026, 10, 1, 9, 30), REFERENCE)
    assert resolved == datetime(2026, 10, 1, 9, 30, tzinfo=UTC)


def test_non_utc_datetimes_are_converted_to_utc() -> None:
    kolkata = timezone(timedelta(hours=5, minutes=30))
    resolved, _ = parse_posted_at(datetime(2026, 10, 1, 9, 30, tzinfo=kolkata), REFERENCE)
    assert resolved == datetime(2026, 10, 1, 4, 0, tzinfo=UTC)


def test_unparseable_date_becomes_none_rather_than_a_guess() -> None:
    assert parse_posted_at("sometime recently", REFERENCE) == (None, False)
    assert parse_posted_at(None, REFERENCE) == (None, False)
    assert parse_posted_at("", REFERENCE) == (None, False)


def test_missing_posted_date_is_warned_about_and_never_backfilled() -> None:
    """Discovery time must never stand in for the posting date."""
    normalized = normalize_record(make_record(posted_at=None), retrieved_at=REFERENCE)
    assert normalized.values["posted_at"] is None
    assert normalized.values["discovered_at"] == REFERENCE
    assert any("no posting date" in warning for warning in normalized.warnings)


def test_normalization_keeps_the_raw_salary_when_it_has_no_number() -> None:
    normalized = normalize_record(make_record(salary_raw="Competitive"), retrieved_at=REFERENCE)
    assert normalized.values["salary_raw"] == "Competitive"
    assert normalized.values["salary_min"] is None


def test_normalization_marks_inferred_skills_as_preferred_not_required() -> None:
    normalized = normalize_record(
        make_record(
            required_skills=[],
            preferred_skills=[],
            description="You will use Python and Docker daily, with some Kubernetes.",
        ),
        retrieved_at=REFERENCE,
    )
    assert normalized.values["required_skills"] == []
    assert "python" in normalized.values["preferred_skills"]
    assert any("inferred" in warning for warning in normalized.warnings)


def test_normalization_drops_an_unsafe_url_but_keeps_the_listing() -> None:
    normalized = normalize_record(
        make_record(url="javascript:alert(1)", external_id="X-1"), retrieved_at=REFERENCE
    )
    assert normalized.values["url"] == ""
    assert normalized.values["title"]
    assert any("url rejected" in warning for warning in normalized.warnings)


def test_skills_are_canonicalised_across_spellings() -> None:
    normalized = normalize_record(
        make_record(required_skills=["NodeJS", "React.js", "Postgres", "K8s", "GoLang"]),
        retrieved_at=REFERENCE,
    )
    assert set(normalized.values["required_skills"]) == {
        "node.js",
        "react",
        "postgresql",
        "kubernetes",
        "go",
    }


def test_description_skill_extraction_only_matches_known_vocabulary() -> None:
    found = extract_skills_from_description("We use Python, Kubernetes and Blorptron 9000.")
    assert "python" in found
    assert "kubernetes" in found
    assert not any("blorptron" in skill for skill in found)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Bengaluru, Karnataka, India", "bengaluru, karnataka, india"),
        ("Bangalore", "bengaluru"),
        ("Work From Home", "remote"),
        ("Gurgaon/Noida", "gurugram, noida"),
        ("", ""),
    ],
)
def test_location_normalization(raw: str, expected: str) -> None:
    assert normalize_location(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Acme Technologies Pvt Ltd", "acme"),
        ("Acme Tech", "acme"),
        ("Infosys Limited", "infosys"),
        ("Zeta Solutions India Private Limited", "zeta"),
    ],
)
def test_company_normalization_converges(raw: str, expected: str) -> None:
    assert normalize_company(raw) == expected
