"""Rebuild ``tests/fixtures/eval_jobs_real.json`` from listings already discovered.

Run with ``python -m tests.build_eval_dataset``. Every row keeps the URL it was fetched
from and the stated evidence the label was assigned on, so a label can be re-checked
against the employer's own wording rather than taken on trust.

Labels are assigned from facts quoted out of the listing — its title, its location and the
smallest experience bar its own text states — not from the score the ranker gives it. The
candidate profile the labels assume is the verified one: 0.4 years, India/remote, target
titles across software, backend/Python, frontend, GenAI and cloud/DevOps.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from app.services.evidence import _stated_min_years

CANDIDATE_YEARS = 0.4

#: The project's documented tolerance: a bar more than two years above the candidate is an
#: exclusion, not a ranking penalty. Mirrors ``app/services/filters.py``.
EXPERIENCE_TOLERANCE_YEARS = 2.0

FAMILY_PATTERNS: dict[str, str] = {
    "genai_agentic": r"\b(ai engineer|ml engineer|machine learning|genai|generative ai|llm|agentic|nlp|applied ai|ai research)\b",
    "cloud_devops": r"\b(devops|sre|site reliability|platform engineer|cloud engineer|infrastructure engineer|kubernetes)\b",
    "frontend": r"\b(frontend|front-end|react|angular|vue|ui engineer|web developer)\b",
    "backend_python": r"\b(backend|back-end|python|django|flask|fastapi)\b",
    "software_general": r"(software (engineer|developer)|\bsde\b|full.?stack|associate engineer|graduate engineer|software dev)",
}

SENIOR_MARKERS = r"\b(senior|staff|principal|lead|head of|director|manager|architect|vp|sr\.?)\b"

INDIA_PLACES = (
    r"\b(india|bengaluru|bangalore|hyderabad|pune|chennai|mumbai|delhi|noida|gurgaon|"
    r"gurugram|coimbatore|kolkata|ahmedabad|indore|nashik|vadodara|jaipur|chandigarh|"
    r"adugodi|verna|goa)\b"
)

SUPPORT_MARKERS = (
    r"\b(support|helpdesk|help desk|service desk|technical support|customer service)\b"
)


def job_family(title: str) -> str | None:
    lowered = (title or "").lower()
    for family, pattern in FAMILY_PATTERNS.items():
        if re.search(pattern, lowered):
            return family
    return None


def where(location: str) -> str:
    lowered = (location or "").lower()
    if re.search(INDIA_PLACES, lowered):
        return "india"
    if "remote" in lowered:
        return "remote"
    return "other"


#: Wordings by which a remote listing restricts who may apply. Collected by reading the
#: harvested listings; each alternative appears verbatim in at least one of them.
_LOCATION_RESTRICTION = re.compile(
    r"(us candidates only|u\.?s\.?[- ]based|based in the (us|united states)|"
    r"authorized to work in the (us|united states)|must reside in|"
    r"located in the (us|united states|uk|eu)|eligible to work in the (us|uk|eu)|"
    r"within the (us|united states|uk|eu)|(us|uk|eu|canada)[- ]only)",
    re.IGNORECASE,
)


def _stated_location_restriction(text: str) -> str:
    found = _LOCATION_RESTRICTION.search(text or "")
    return found.group(0) if found else ""


def classify(row: dict[str, Any]) -> tuple[str, str, str]:
    """Return ``(label, expectation, why)`` for one listing, quoting the deciding fact."""
    title, location, description = row["title"], row["location"], row["description"] or ""
    family = job_family(title)
    place = where(location)
    stated = _stated_min_years(description)
    structured = row.get("experience_min_years")
    bar = max([value for value in (stated, structured) if value is not None], default=None)

    if family is None:
        if re.search(SUPPORT_MARKERS, (title or "").lower()):
            return (
                "support",
                "below_threshold",
                f"support role ('{title}'), not a software engineering discipline",
            )
        if place == "india":
            return (
                "adversarial",
                "below_threshold",
                f"India-located ('{location}') but '{title}' is a different discipline, so "
                "location and any generic title token look right while the role does not",
            )
        return ("irrelevant", "below_threshold", f"'{title}' is a different discipline")

    if re.search(SENIOR_MARKERS, (title or "").lower()):
        return (
            "senior",
            "below_threshold",
            f"title states seniority ('{title}'), incompatible with 0.4 years",
        )

    if bar is not None and bar > CANDIDATE_YEARS + EXPERIENCE_TOLERANCE_YEARS:
        return (
            "over_experience_bar",
            "excluded",
            f"states a bar of {bar:g} years, more than "
            f"{EXPERIENCE_TOLERANCE_YEARS:g} above the candidate's {CANDIDATE_YEARS:g}",
        )

    if (row.get("employment_type") or "").lower() in {"contract", "temporary", "freelance"}:
        return (
            "preference_mismatch",
            "excluded",
            f"employment type '{row['employment_type']}' is not among the profile's "
            "accepted types (full_time, internship)",
        )

    if place == "other":
        # The profile lists "Remote" and accepts remote work, so a remote role is a
        # legitimate target wherever the employer sits — unless the listing itself states a
        # geographic restriction. The app has no rule for that wording today, so those rows
        # are scored on neither precision nor recall and are reported as a known gap
        # instead of penalising the ranker for a rule it does not have.
        if (row.get("work_arrangement") or "").lower() == "remote":
            restriction = _stated_location_restriction(f"{title}\n{description}")
            if restriction:
                return (
                    "location_restricted",
                    "known_gap",
                    f"remote but states a geographic restriction: '{restriction}'",
                )
            return (
                "relevant",
                "high_or_review",
                f"{family} remote role stating no geographic restriction and no bar above "
                f"{CANDIDATE_YEARS + EXPERIENCE_TOLERANCE_YEARS:g} years",
            )
        return (
            "preference_mismatch",
            "excluded",
            f"non-remote role in '{location}', which the profile neither lists nor accepts",
        )

    if len((description or "").split()) < 25:
        return (
            "sparse",
            "not_confident",
            f"description is only {len((description or '').split())} words, so there is too "
            "little evidence to judge the role confidently",
        )

    return (
        "relevant",
        "high_or_review",
        f"{family} role in '{location}' stating no bar above "
        f"{CANDIDATE_YEARS + EXPERIENCE_TOLERANCE_YEARS:g} years",
    )


def harvest(database: Path, target_total: int = 190) -> list[dict[str, Any]]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    rows = [
        dict(row)
        for row in connection.execute(
            """select id, title, company, location, description, experience_raw,
                      experience_min_years, experience_max_years, posted_at, url,
                      employment_type, work_arrangement, required_skills, preferred_skills
               from job order by id"""
        )
    ]
    connection.close()

    # Only listings an employer actually published are eligible. Rows whose URL points at
    # the synthetic ``example.com`` host come from the hand-written adversarial fixture in
    # ``eval_jobs.json``; including them here would let a listing written to fail a rule
    # count as evidence that the rule works.
    SYNTHETIC_HOSTS = ("example.com", "example.org", "localhost")

    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        url = row["url"] or ""
        if not url.startswith("http") or any(host in url for host in SYNTHETIC_HOSTS):
            continue
        label, expect, why = classify(row)
        family = job_family(row["title"]) or "non_target"
        key = f"{label}:{family}:{where(row['location'])}"
        buckets.setdefault(key, []).append({**row, "_label": label, "_expect": expect, "_why": why})

    # Bounded slices keep the mix honest in two ways: a per-label quota stops one label
    # dominating the metrics, and a per-family floor on the 'relevant' rows stops the
    # largest family (software_general) crowding out frontend and cloud/DevOps, whose
    # per-family precision would otherwise rest on three or four rows.
    quota = {
        "relevant": 70,
        "over_experience_bar": 25,
        "senior": 20,
        "adversarial": 25,
        "irrelevant": 15,
        "support": 10,
        "preference_mismatch": 15,
        "location_restricted": 12,
        "sparse": 8,
    }
    relevant_floor = dict.fromkeys(FAMILY_PATTERNS, 10)
    chosen: list[dict[str, Any]] = []
    taken: dict[str, int] = dict.fromkeys(quota, 0)
    per_company: dict[str, int] = {}

    def admit(row: dict[str, Any], *, cap_company: int = 12) -> bool:
        company = (row["company"] or "").lower()
        if per_company.get(company, 0) >= cap_company:
            return False
        chosen.append(row)
        taken[row["_label"]] += 1
        per_company[company] = per_company.get(company, 0) + 1
        return True

    for key in sorted(buckets):
        label, family, _ = key.split(":")
        if label != "relevant":
            continue
        floor = relevant_floor.get(family, 0)
        admitted = 0
        for row in buckets[key]:
            if admitted >= floor or taken["relevant"] >= quota["relevant"]:
                break
            if admit(row, cap_company=20):
                admitted += 1

    # India-located rows are taken before anything else: they are the scarcest class in the
    # pool and the candidate's own location, so a quota filled by volume would omit them.
    for key in sorted(buckets):
        if ":india" not in key:
            continue
        label = key.split(":")[0]
        for row in buckets[key]:
            if taken.get(label, 0) >= quota.get(label, 0):
                break
            if row not in chosen:
                admit(row, cap_company=20)

    for key in sorted(buckets):
        if not key.startswith(("location_restricted:", "sparse:")):
            continue
        label = key.split(":")[0]
        for row in buckets[key]:
            if taken.get(label, 0) >= quota.get(label, 0):
                break
            if row not in chosen:
                admit(row, cap_company=20)

    seen = {id(row) for row in chosen}
    for key in sorted(buckets, key=lambda k: -len(buckets[k])):
        label = key.split(":")[0]
        for row in buckets[key]:
            if taken[label] >= quota[label] or len(chosen) >= target_total:
                break
            if id(row) not in seen:
                admit(row)
    return chosen


API_BY_HOST = {
    "ashbyhq.com": "ashby",
    "greenhouse.io": "greenhouse",
    "lever.co": "lever",
    "workable.com": "workable",
    "smartrecruiters.com": "smartrecruiters",
    "arbeitnow": "arbeitnow",
    "remoteok": "remoteok",
    "himalayas.app": "himalayas",
    "jobicy.com": "jobicy",
}


def publishing_api(url: str) -> str:
    for host, api in API_BY_HOST.items():
        if host in (url or "").lower():
            return api
    return "employer_site"


def to_fixture(rows: list[dict[str, Any]]) -> dict[str, Any]:
    jobs = []
    for index, row in enumerate(rows, start=1):
        record = {
            "source": "manual",
            "external_id": f"EV-{index:03d}",
            "title": row["title"],
            "company": row["company"],
            "location": row["location"],
            "url": row["url"],
            "description": row["description"] or "",
        }
        for optional in ("employment_type", "work_arrangement", "experience_raw"):
            if row.get(optional):
                record[optional] = row[optional]
        jobs.append(
            {
                "label": row["_label"],
                "expect": row["_expect"],
                "job_family": job_family(row["title"]) or "non_target",
                "location_class": where(row["location"]),
                "why": row["_why"],
                "provenance": {
                    "fetched_from": row["url"],
                    "api": publishing_api(row["url"]),
                    "stated_experience_in_text": _stated_min_years(row["description"] or ""),
                    "structured_experience_min_years": row["experience_min_years"],
                },
                "record": record,
            }
        )
    return {
        "_about": {
            "purpose": "Labelled relevance benchmark for tests/test_matching_benchmark.py.",
            "version": 6,
            "rows": len(jobs),
            "candidate": "verified profile: 0.4 years, India/remote, software + backend/Python "
            "+ frontend + GenAI/agentic + cloud/DevOps target titles",
            "labelling": "Each label is assigned from facts quoted out of the listing — its "
            "title, its location and the smallest experience bar its own text states — never "
            "from the score the ranker produces. 'why' records the deciding fact and "
            "'provenance.fetched_from' the URL it can be re-checked against.",
            "rebuild": "python -m tests.build_eval_dataset",
        },
        "jobs": jobs,
    }


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    rows = harvest(root / "var" / "jobassist.db")
    fixture = to_fixture(rows)
    out = root / "tests" / "fixtures" / "eval_jobs_real.json"
    out.write_text(json.dumps(fixture, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    counts: dict[str, int] = {}
    families: dict[str, int] = {}
    for job in fixture["jobs"]:
        counts[job["label"]] = counts.get(job["label"], 0) + 1
        families[job["job_family"]] = families.get(job["job_family"], 0) + 1
    print(f"wrote {len(fixture['jobs'])} rows to {out}")
    print("labels:  ", json.dumps(counts, indent=0).replace("\n", " "))
    print("families:", json.dumps(families, indent=0).replace("\n", " "))


if __name__ == "__main__":
    main()
