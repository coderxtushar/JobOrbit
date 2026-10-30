"""Job normalization.

Turns a :class:`RawJobRecord` from any adapter into the canonical column values stored on
:class:`app.db.models.Job`. Two rules hold throughout:

* An unparseable field becomes ``UNKNOWN``/``None`` and the raw string is preserved, so a
  salary like "Best in industry" is never silently turned into a number.
* ``posted_at`` is only ever set from what the source said. Relative phrases ("3 days ago")
  are resolved against the retrieval time and flagged ``posted_at_is_approximate``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.db.models import EmploymentType, WorkArrangement, utcnow
from app.schemas.job import RawJobRecord
from app.services.resume_parser import KNOWN_SKILL_VOCABULARY
from app.services.text import (
    canonical_skills,
    collapse_whitespace,
    normalize_company,
    normalize_location,
)
from app.services.url_safety import canonicalize_url, inspect_url

_REMOTE_HINTS = ("remote", "work from home", "wfh", "anywhere", "telecommute", "distributed")
_HYBRID_HINTS = ("hybrid", "partially remote", "flexible location", "2 days from office")
_ONSITE_HINTS = ("on-site", "onsite", "in office", "in-office", "work from office", "wfo")

_EMPLOYMENT_HINTS: tuple[tuple[EmploymentType, tuple[str, ...]], ...] = (
    (
        EmploymentType.INTERNSHIP,
        ("internship", "intern,", "summer intern", "trainee", "apprentice"),
    ),
    (EmploymentType.CONTRACT, ("contract", "contractual", "freelance", "consultant", "c2h")),
    (EmploymentType.TEMPORARY, ("temporary", "temp ", "seasonal")),
    (EmploymentType.PART_TIME, ("part-time", "part time", "parttime")),
    (EmploymentType.FULL_TIME, ("full-time", "full time", "fulltime", "permanent", "regular")),
)

_CURRENCY_SYMBOLS = {
    "₹": "INR",
    "rs": "INR",
    "inr": "INR",
    "$": "USD",
    "usd": "USD",
    "€": "EUR",
    "£": "GBP",
}

_RELATIVE_DATE = re.compile(
    r"\b(?:posted\s+)?(?:(\d{1,3})\s*\+?\s*(minute|min|hour|hr|day|week|month)s?\s+ago"
    r"|(today|just now|yesterday|a\s+(?:day|week|month)\s+ago))\b",
    re.IGNORECASE,
)
_ABSOLUTE_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
)

_RELATIVE_UNIT_DELTAS = {
    "minute": timedelta(minutes=1),
    "min": timedelta(minutes=1),
    "hour": timedelta(hours=1),
    "hr": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
}


@dataclass(slots=True)
class NormalizedJob:
    """Canonical job values plus the provenance fields for its source reference."""

    values: dict[str, Any]
    source_metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def parse_work_arrangement(*texts: str) -> WorkArrangement:
    haystack = " ".join(text.lower() for text in texts if text)
    if any(hint in haystack for hint in _HYBRID_HINTS):
        return WorkArrangement.HYBRID
    if any(hint in haystack for hint in _REMOTE_HINTS):
        return WorkArrangement.REMOTE
    if any(hint in haystack for hint in _ONSITE_HINTS):
        return WorkArrangement.ONSITE
    return WorkArrangement.UNKNOWN


def parse_employment_type(*texts: str) -> EmploymentType:
    haystack = " ".join(text.lower() for text in texts if text)
    for employment_type, hints in _EMPLOYMENT_HINTS:
        if any(hint in haystack for hint in hints):
            return employment_type
    return EmploymentType.UNKNOWN


def parse_salary(raw: str) -> tuple[int | None, int | None, str | None]:
    """Parse a salary string into (min, max, currency).

    Handles the Indian lakh/crore and the generic ``k`` conventions. Returns ``None`` values
    whenever the string carries no number, which keeps "Not disclosed" out of the numeric
    columns.
    """
    text = (raw or "").lower().replace(",", "")
    if not text.strip():
        return None, None, None

    currency = None
    for symbol, code in _CURRENCY_SYMBOLS.items():
        if symbol in text:
            currency = code
            break

    numbers: list[float] = []
    for match in re.finditer(
        r"(\d+(?:\.\d+)?)\s*(lakhs?|lacs?|lpa|crores?|cr|k|thousand|million|mn)?", text
    ):
        value = float(match.group(1))
        unit = (match.group(2) or "").strip()
        if unit in ("lakh", "lakhs", "lac", "lacs", "lpa"):
            value *= 100_000
        elif unit in ("crore", "crores", "cr"):
            value *= 10_000_000
        elif unit in ("k", "thousand"):
            value *= 1_000
        elif unit in ("million", "mn"):
            value *= 1_000_000
        elif value < 100:
            # A bare small number in a salary field is a lakh figure in Indian postings.
            value *= 100_000
        numbers.append(value)

    plausible = [number for number in numbers if 1_000 <= number <= 100_000_000]
    if not plausible:
        return None, None, currency
    if currency is None:
        currency = "INR"
    low, high = int(min(plausible)), int(max(plausible))
    return low, (high if high != low else None), currency


#: Seniority labels published instead of year ranges, mapped to conservative bounds. The
#: lower bound is what matters: it is what an eligibility check compares against, so each
#: is set to the least experience a listing with that label plausibly expects.
_SENIORITY_LABEL_YEARS: tuple[tuple[str, tuple[float | None, float | None]], ...] = (
    (r"\binternship\b", (0.0, 1.0)),
    (r"\bassociate\b", (1.0, 3.0)),
    (r"\bmid[\s-]?senior\b", (3.0, 8.0)),
    (r"\bmid[\s-]?level\b", (2.0, 5.0)),
    (r"\bdirector\b", (8.0, None)),
    (r"\bexecutive\b", (10.0, None)),
    (r"\bsenior\b", (5.0, None)),
)


def parse_experience(raw: str) -> tuple[float | None, float | None]:
    """Parse a required-experience string into (min_years, max_years)."""
    text = (raw or "").lower()
    if not text.strip():
        return None, None
    if re.search(
        r"\b(freshers?|fresh graduates?|no (?:prior )?experience|entry[\s-]?level|"
        r"0\s*(?:-|to)?\s*(?:0|1)?\s*yr|graduate trainee|trainee)\b",
        text,
    ):
        return 0.0, None

    range_match = re.search(r"(\d{1,2}(?:\.\d)?)\s*(?:-|–|to)\s*(\d{1,2}(?:\.\d)?)", text)
    if range_match:
        low, high = float(range_match.group(1)), float(range_match.group(2))
        return (low, high) if low <= high else (high, low)

    plus_match = re.search(r"(\d{1,2}(?:\.\d)?)\s*\+", text)
    if plus_match:
        return float(plus_match.group(1)), None

    single = re.search(r"(\d{1,2}(?:\.\d)?)\s*(?:\+)?\s*(?:years?|yrs?)", text)
    if single:
        return float(single.group(1)), float(single.group(1))

    # Workable and LinkedIn publish a seniority label instead of a year range. Without
    # these, experience eligibility was unassessable for every such listing, and an
    # unassessable category has its weight redistributed to the others - which is how a
    # director-level role came through with no seniority penalty at all.
    for pattern, bounds in _SENIORITY_LABEL_YEARS:
        if re.search(pattern, text):
            return bounds
    return None, None


def parse_posted_at(
    raw: str | datetime | None, reference: datetime | None = None
) -> tuple[datetime | None, bool]:
    """Resolve a posting date. Returns (timestamp, is_approximate)."""
    if raw is None:
        return None, False
    if isinstance(raw, datetime):
        resolved = raw if raw.tzinfo else raw.replace(tzinfo=UTC)
        return resolved.astimezone(UTC), False

    text = str(raw).strip()
    if not text:
        return None, False
    now = reference or utcnow()

    relative = _RELATIVE_DATE.search(text)
    if relative:
        if relative.group(3):
            phrase = relative.group(3).lower()
            if phrase in ("today", "just now"):
                return now, True
            if phrase == "yesterday":
                return now - timedelta(days=1), True
            for unit, delta in _RELATIVE_UNIT_DELTAS.items():
                if unit in phrase:
                    return now - delta, True
            return now, True
        quantity = int(relative.group(1))
        unit = relative.group(2).lower()
        return now - _RELATIVE_UNIT_DELTAS.get(unit, timedelta(days=1)) * quantity, True

    iso_candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso_candidate)
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).astimezone(UTC), False
    except ValueError:
        pass

    for fmt in _ABSOLUTE_DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=UTC), False
        except ValueError:
            continue
    return None, False


def extract_skills_from_description(description: str, limit: int = 40) -> list[str]:
    """Find known skill names mentioned in a description.

    Only exact vocabulary hits count. The result is labelled 'inferred' upstream and is
    never treated as the employer's explicit requirement list.
    """
    if not description:
        return []
    haystack = f" {re.sub(r'[^a-z0-9+#. ]+', ' ', description.lower())} "
    found = [skill for skill in KNOWN_SKILL_VOCABULARY if f" {skill} " in haystack]
    return found[:limit]


def normalize_record(record: RawJobRecord, retrieved_at: datetime | None = None) -> NormalizedJob:
    """Convert one raw record into canonical job values."""
    retrieved_at = retrieved_at or utcnow()
    warnings: list[str] = []

    title = collapse_whitespace(record.title)[:400]
    company = collapse_whitespace(record.company)[:300]
    location = collapse_whitespace(record.location)[:300]
    description = record.description.strip()

    verdict = inspect_url(record.url)
    url = record.url.strip() if verdict.safe else ""
    if record.url.strip() and not verdict.safe:
        warnings.append(f"url rejected ({verdict.reason}); the listing was kept without a link")

    arrangement = (
        WorkArrangement(record.work_arrangement)
        if record.work_arrangement in {member.value for member in WorkArrangement}
        else parse_work_arrangement(location, title, description[:2000])
    )
    employment = (
        EmploymentType(record.employment_type)
        if record.employment_type in {member.value for member in EmploymentType}
        else parse_employment_type(title, description[:2000], record.experience_raw)
    )

    salary_min, salary_max, currency = record.salary_min, record.salary_max, record.salary_currency
    if salary_min is None and salary_max is None:
        salary_min, salary_max, parsed_currency = parse_salary(record.salary_raw)
        currency = currency or parsed_currency

    experience_min, experience_max = record.experience_min_years, record.experience_max_years
    if experience_min is None and experience_max is None:
        experience_min, experience_max = parse_experience(record.experience_raw or title)

    posted_at, approximate = parse_posted_at(record.posted_at, retrieved_at)
    if posted_at is None:
        warnings.append(
            "no posting date was provided; freshness cannot be scored and the listing is "
            "not treated as new"
        )
    elif record.posted_at_is_approximate:
        approximate = True

    required = canonical_skills(record.required_skills)
    preferred = canonical_skills(record.preferred_skills)
    if not required and not preferred:
        inferred = canonical_skills(extract_skills_from_description(description))
        preferred = [skill for skill in inferred if skill not in required]
        if preferred:
            warnings.append(
                "no skill list was supplied; skills shown were inferred from the description "
                "and are reported as preferred, not required"
            )

    values: dict[str, Any] = {
        "title": title,
        "company": company,
        "company_normalized": normalize_company(company),
        "location": location,
        "location_normalized": normalize_location(location),
        "work_arrangement": arrangement,
        "employment_type": employment,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": currency,
        "salary_raw": collapse_whitespace(record.salary_raw)[:200],
        "experience_min_years": experience_min,
        "experience_max_years": experience_max,
        "experience_raw": collapse_whitespace(record.experience_raw)[:200],
        "required_skills": required,
        "preferred_skills": preferred,
        "education_requirements": [item[:200] for item in record.education_requirements][:10],
        "description": description,
        "url": url,
        "canonical_url": canonicalize_url(url),
        "application_method": record.application_method,
        "posted_at": posted_at,
        "posted_at_is_approximate": approximate,
        "discovered_at": retrieved_at,
        "raw_payload": record.model_dump(mode="json"),
    }
    return NormalizedJob(values=values, source_metadata=record.source_metadata, warnings=warnings)
