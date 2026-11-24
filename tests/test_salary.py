"""Salary normalisation: what a figure means, and every assumption behind it.

The property under test is not only that "12-18 LPA" becomes 1.2M-1.8M, but that nothing
is produced the text does not support: undisclosed salaries stay undisclosed, USD is never
priced in INR without a configured rate, and current CTC is never read as expected CTC.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import CandidateProfile
from app.services.salary import (
    BARE_LAKH_ASSUMPTION,
    compensation_from_amounts,
    detect_question_unit,
    format_for_unit,
    parse_compensation,
    salary_kind,
)
from tests.conftest import persist_job

L = 100_000

# text, currency, period, minimum, maximum, annual_min, annual_max, inr_min, inr_max, is_range
PARSE_CASES = [
    (
        "INR 12,00,000 per annum",
        "INR",
        "annual",
        12 * L,
        12 * L,
        12 * L,
        12 * L,
        12 * L,
        12 * L,
        False,
    ),
    ("12 LPA", "INR", "annual", 12 * L, 12 * L, 12 * L, 12 * L, 12 * L, 12 * L, False),
    ("12-18 LPA", "INR", "annual", 12 * L, 18 * L, 12 * L, 18 * L, 12 * L, 18 * L, True),
    ("12 - 18 lpa", "INR", "annual", 12 * L, 18 * L, 12 * L, 18 * L, 12 * L, 18 * L, True),
    (
        "₹ 15,00,000 - 20,00,000",
        "INR",
        "annual",
        15 * L,
        20 * L,
        15 * L,
        20 * L,
        15 * L,
        20 * L,
        True,
    ),
    ("1.2 Cr", "INR", "annual", 120 * L, 120 * L, 120 * L, 120 * L, 120 * L, 120 * L, False),
    ("15 lakhs p.a.", "INR", "annual", 15 * L, 15 * L, 15 * L, 15 * L, 15 * L, 15 * L, False),
    ("₹80k/month", "INR", "monthly", 80_000, 80_000, 960_000, 960_000, 960_000, 960_000, False),
    (
        "Rs. 50,000 per month",
        "INR",
        "monthly",
        50_000,
        50_000,
        600_000,
        600_000,
        600_000,
        600_000,
        False,
    ),
    ("₹ 40000 pm", "INR", "monthly", 40_000, 40_000, 480_000, 480_000, 480_000, 480_000, False),
    ("INR 60000/mo", "INR", "monthly", 60_000, 60_000, 720_000, 720_000, 720_000, 720_000, False),
    (
        "₹30,000 - 45,000 monthly",
        "INR",
        "monthly",
        30_000,
        45_000,
        360_000,
        540_000,
        360_000,
        540_000,
        True,
    ),
    ("USD 120k-150k", "USD", "annual", 120_000, 150_000, 120_000, 150_000, None, None, True),
    ("$60/hr", "USD", "hourly", 60, 60, 124_800, 124_800, None, None, False),
    ("$5,000 per month", "USD", "monthly", 5_000, 5_000, 60_000, 60_000, None, None, False),
    ("€70,000 per year", "EUR", "annual", 70_000, 70_000, 70_000, 70_000, None, None, False),
    ("CTC ₹ 8-12", "INR", "annual", 8 * L, 12 * L, 8 * L, 12 * L, 8 * L, 12 * L, True),
]


@pytest.mark.parametrize(
    ("text", "currency", "period", "low", "high", "a_low", "a_high", "i_low", "i_high", "is_range"),
    PARSE_CASES,
)
def test_parse_compensation_table(
    text, currency, period, low, high, a_low, a_high, i_low, i_high, is_range
) -> None:
    comp = parse_compensation(text, usd_inr_rate=None)
    assert comp.original == text
    assert comp.disclosed
    assert comp.currency == currency
    assert comp.period == period
    assert (comp.minimum, comp.maximum) == (low, high)
    assert (comp.annual_minimum, comp.annual_maximum) == (a_low, a_high)
    assert (comp.inr_annual_minimum, comp.inr_annual_maximum) == (i_low, i_high)
    assert comp.is_range is is_range


@pytest.mark.parametrize(
    "text",
    ["Not disclosed", "competitive", "Competitive salary", "Best in industry", "", "   ", None],
)
def test_undisclosed_salary_produces_no_numbers(text) -> None:
    comp = parse_compensation(text)
    assert not comp.disclosed
    assert comp.minimum is None and comp.maximum is None
    assert comp.annual_minimum is None and comp.inr_annual_minimum is None
    assert comp.assumptions, "the reason nothing was parsed must be stated"
    assert comp.original == (text or "")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12 LPA", "LPA = lakh per annum = ×100,000"),
        ("₹80k/month", "monthly × 12"),
        ("₹80k/month", "k = ×1,000"),
        ("1.2 Cr", "Cr = crore = ×10,000,000"),
        ("8-12", BARE_LAKH_ASSUMPTION),
        ("$60/hr", "hourly × 2,080 (40 h/week × 52 weeks)"),
    ],
)
def test_every_conversion_is_spelled_out(text: str, expected: str) -> None:
    assert expected in parse_compensation(text, usd_inr_rate=None).assumptions


def test_usd_without_rate_has_no_inr_and_says_why() -> None:
    comp = parse_compensation("USD 120k-150k", usd_inr_rate=None)
    assert comp.inr_annual_minimum is None and comp.inr_annual_maximum is None
    assert any("No USD→INR rate is configured" in note for note in comp.assumptions)


def test_usd_with_configured_rate_converts_and_records_rate() -> None:
    comp = parse_compensation("USD 120k-150k", usd_inr_rate=83.2)
    assert comp.inr_annual_minimum == pytest.approx(120_000 * 83.2)
    assert comp.inr_annual_maximum == pytest.approx(150_000 * 83.2)
    assert "USD→INR at configured rate 83.2" in comp.assumptions


def test_rate_defaults_to_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    assert parse_compensation("$100,000 per year").inr_annual_minimum is None
    monkeypatch.setattr(get_settings(), "usd_inr_rate", 80.0)
    assert parse_compensation("$100,000 per year").inr_annual_minimum == 8_000_000


def test_default_currency_is_reported_when_used() -> None:
    comp = parse_compensation("50,000 per month")
    assert comp.currency == "INR"
    assert not comp.currency_stated
    assert any("No currency was stated" in note for note in comp.assumptions)
    assert parse_compensation("50,000 per month", default_currency="USD").currency == "USD"


def test_bare_small_figure_without_period_is_not_annualised() -> None:
    comp = parse_compensation("₹80k")
    assert comp.disclosed and comp.minimum == 80_000
    assert comp.period is None
    assert comp.annual_minimum is None and comp.inr_annual_minimum is None


def test_upper_bound_only_does_not_invent_a_minimum() -> None:
    comp = parse_compensation("Up to ₹ 20 LPA")
    assert comp.minimum is None
    assert comp.maximum == 20 * L
    assert any("upper bound" in note for note in comp.assumptions)


def test_experience_range_is_not_read_as_salary() -> None:
    comp = parse_compensation("2-4 years, 10 LPA")
    assert (comp.minimum, comp.maximum) == (10 * L, 10 * L)
    assert not comp.is_range


# --------------------------------------------------------------------------------------
# Screening questions
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "unit"),
    [
        ("Expected CTC (in LPA)", "lpa"),
        ("Current CTC in lakhs", "lpa"),
        ("Expected CTC (in Lacs)", "lpa"),
        ("monthly salary expectation in INR", "inr_monthly"),
        ("Expected monthly in-hand salary", "inr_monthly"),
        ("Expected salary (USD)", "usd_annual"),
        ("Desired annual compensation in $", "usd_annual"),
        ("Expected CTC", "inr_annual"),
        ("Current salary in INR per annum", "inr_annual"),
        ("Expected salary", None),
        ("Salary expectations", None),
        ("Hourly rate (USD)", None),
        ("", None),
    ],
)
def test_detect_question_unit(label: str, unit: str | None) -> None:
    assert detect_question_unit(label) == unit


@pytest.mark.parametrize(
    ("label", "kind"),
    [
        ("Current CTC", "current"),
        ("What is your current salary?", "current"),
        ("Present salary (INR)", "current"),
        ("Last drawn salary", "current"),
        ("CCTC", "current"),
        ("Expected CTC", "expected"),
        ("ECTC (LPA)", "expected"),
        ("Desired salary", "expected"),
        ("Salary expectations", "expected"),
        ("What are your salary requirements?", "expected"),
        ("Expected hike over current CTC", None),
        ("Current location", None),
        ("Expected joining date", None),
        ("Salary", None),
        ("", None),
    ],
)
def test_salary_kind_never_confuses_current_and_expected(label: str, kind: str | None) -> None:
    assert salary_kind(label) == kind


# --------------------------------------------------------------------------------------
# Proposals in a form's unit
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "unit", "value", "exact"),
    [
        ("12 LPA", "lpa", "12", True),
        ("12.5 LPA", "lpa", "12.5", True),
        ("INR 12,00,000 per annum", "inr_annual", "1200000", True),
        ("Rs 50000 per month", "inr_monthly", "50000", True),
        ("USD 120000 per year", "usd_annual", "120000", True),
        ("12 LPA", "inr_annual", "1200000", False),
        ("12 LPA", "inr_monthly", "100000", False),
        ("INR 12,00,000 per annum", "lpa", "12", False),
        ("₹80k/month", "lpa", "9.6", False),
        ("₹80k/month", "inr_monthly", "80000", False),
        ("12-18 LPA", "lpa", "12", False),
        ("₹ 15,00,000 - 20,00,000", "inr_annual", "1500000", False),
        ("8-12", "lpa", "8", False),
        ("CTC ₹ 8-12", "lpa", "8", False),
    ],
)
def test_format_for_unit(text: str, unit: str, value: str, exact: bool) -> None:
    conversion = format_for_unit(parse_compensation(text, usd_inr_rate=None), unit)
    assert conversion.value == value
    assert conversion.exact is exact
    if not exact:
        assert conversion.assumptions


def test_format_for_unit_range_pick() -> None:
    comp = parse_compensation("12-18 LPA")
    assert format_for_unit(comp, "lpa", pick="maximum").value == "18"
    assert format_for_unit(comp, "lpa", pick="midpoint").value == "15"
    assert "The range's lower bound is proposed." in format_for_unit(comp, "lpa").assumptions


def test_format_for_unit_refuses_without_rate() -> None:
    usd = parse_compensation("USD 120k-150k", usd_inr_rate=None)
    proposal = format_for_unit(usd, "lpa", usd_inr_rate=None)
    assert proposal.value == "" and not proposal.exact

    inr = parse_compensation("12 LPA")
    proposal = format_for_unit(inr, "usd_annual", usd_inr_rate=None)
    assert proposal.value == "" and not proposal.exact
    assert any("JA_USD_INR_RATE" in note for note in proposal.assumptions)


def test_format_for_unit_with_rate_is_never_exact() -> None:
    usd = parse_compensation("USD 100000 per year", usd_inr_rate=80.0)
    proposal = format_for_unit(usd, "lpa", usd_inr_rate=80.0)
    assert proposal.value == "80"
    assert not proposal.exact
    assert "USD→INR at configured rate 80" in proposal.assumptions

    inr = parse_compensation("INR 8,00,000 per annum", usd_inr_rate=80.0)
    proposal = format_for_unit(inr, "usd_annual", usd_inr_rate=80.0)
    assert proposal.value == "10000" and not proposal.exact


@pytest.mark.parametrize("unit", ["lpa", "inr_annual", "inr_monthly", "usd_annual", "bogus"])
def test_format_for_unit_undisclosed_proposes_nothing(unit: str) -> None:
    proposal = format_for_unit(parse_compensation("Not disclosed"), unit)
    assert proposal.value == "" and not proposal.exact


def test_compensation_from_amounts_records_its_source() -> None:
    comp = compensation_from_amounts(800_000, 1_200_000, "INR", note="from your profile")
    assert comp.disclosed and comp.is_range
    assert comp.inr_annual_minimum == 800_000
    assert "from your profile" in comp.assumptions
    assert format_for_unit(comp, "inr_annual").exact is False  # range: a choice was made
    single = compensation_from_amounts(900_000, None, "INR", note="from your profile")
    assert format_for_unit(single, "inr_annual").value == "900000"
    assert format_for_unit(single, "inr_annual").exact is True
    assert not compensation_from_amounts(None, None, "INR", note="x").disclosed


# --------------------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------------------


def test_parse_endpoint_is_pure(client: TestClient) -> None:
    response = client.get("/api/research/salary/parse", params={"text": "12-18 LPA"})
    assert response.status_code == 200
    body = response.json()
    assert body["compensation"]["inr_annual_minimum"] == 12 * L
    assert body["proposals"]["lpa"]["value"] == "12"
    assert body["proposals"]["lpa"]["exact"] is False
    assert body["proposals"]["usd_annual"]["value"] == ""

    empty = client.get("/api/research/salary/parse").json()
    assert empty["compensation"]["disclosed"] is False


def test_job_salary_endpoint_compares_with_expectation(
    client: TestClient, session: Session, profile: CandidateProfile
) -> None:
    profile.salary_expectation_min = 1_000_000
    profile.salary_expectation_max = 1_400_000
    job = persist_job(session, salary_raw="12-18 LPA")
    undisclosed = persist_job(
        session,
        external_id="LI-2",
        title="Platform Engineer",
        url="https://jobs.example.com/view/2",
        salary_raw="Not disclosed",
    )
    session.commit()

    body = client.get(f"/api/research/jobs/{job.id}/salary").json()
    assert body["listing"]["inr_annual_minimum"] == 12 * L
    assert body["expectation"]["inr_annual_minimum"] == 1_000_000
    assert body["comparison"]["comparable"] is True
    assert "meets your minimum" in body["comparison"]["statement"]
    assert body["listing"]["assumptions"]

    body = client.get(f"/api/research/jobs/{undisclosed.id}/salary").json()
    assert body["listing"]["disclosed"] is False
    assert body["comparison"]["comparable"] is False

    assert client.get("/api/research/jobs/99999/salary").status_code == 404


def test_job_salary_usd_without_rate_is_not_compared(
    client: TestClient, session: Session, profile: CandidateProfile
) -> None:
    profile.salary_expectation_min = 1_000_000
    job = persist_job(session, salary_raw="USD 120k-150k")
    session.commit()
    body = client.get(f"/api/research/jobs/{job.id}/salary").json()
    assert body["listing"]["inr_annual_minimum"] is None
    assert body["comparison"]["comparable"] is False
