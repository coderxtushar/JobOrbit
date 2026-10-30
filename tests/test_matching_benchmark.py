"""Match-quality benchmark over real job listings.

``tests/fixtures/eval_jobs_real.json`` holds 39 listings fetched from public job-board APIs
(Ashby, SmartRecruiters, Remote OK) with a relevance label assigned by reading each one.
This module scores all of them against a profile built from the real resume and measures
four numbers:

* **precision@10 / precision@20** - of the top rows the candidate would actually look at,
  how many are worth applying to. Ranking mirrors production exactly: band first, then
  score, which is what ``JobRepository.list`` does.
* **false-positive rate above the threshold** - the share of unsuitable listings scoring at
  or above the candidate's own ``minimum_match_score``. This is the costly error: it turns
  into a wasted application.
* **relevant recall** - the share of genuinely suitable listings that stay eligible and
  reach the review band or better. The costly error here is a missed opportunity.

``tests/fixtures/eval_baseline.json`` records these numbers as **measured** on the ranker
before the required/preferred/incidental skill classification and role-family rules were
added. The tests assert the current ranker is no worse on every metric, so the file is a
regression gate rather than a claim: regenerate it with
``python -m tests.benchmark_baseline`` only when a change is intended to move the numbers.

Rows labelled ``adjacent`` are excluded from precision and recall: they are the right role
family with an experience bar above the candidate, so either ranking is defensible. They
are still asserted to stay eligible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.db.models import CandidateProfile, Job, utcnow
from app.db.repositories import ProfileRepository
from app.schemas.job import RawJobRecord
from app.services.ingest import JobIngestService
from app.services.matching import score_job

FIXTURE = Path(__file__).parent / "fixtures" / "eval_jobs_real.json"
BASELINE = Path(__file__).parent / "fixtures" / "eval_baseline.json"

#: Labels whose rows the candidate should apply to.
GOOD_LABELS = frozenset({"relevant"})

#: Labels whose rows must never be recommended. ``adversarial`` rows are the hard ones:
#: they share an Indian location, an "Associate" level, a generic title token, or a profile
#: skill mentioned in passing, so every surface signal except the role itself looks right.
BAD_LABELS = frozenset({"irrelevant", "adversarial", "senior", "support"})

_BAND_RANK = {"high": 0, "review": 1, "low": 2}


@dataclass(slots=True)
class Scored:
    label: str
    expect: str
    why: str
    title: str
    company: str
    score: float
    band: str
    confidence: str
    evidence_coverage: float
    filtered_out: bool
    filter_reasons: list[str]
    category_scores: dict[str, Any]
    explanation: list[str]

    @property
    def is_good(self) -> bool:
        return self.label in GOOD_LABELS

    @property
    def is_bad(self) -> bool:
        return self.label in BAD_LABELS


def load_dataset() -> list[dict[str, Any]]:
    return json.loads(FIXTURE.read_text())["jobs"]


def _record(entry: dict[str, Any]) -> RawJobRecord:
    payload = dict(entry["record"])
    payload.setdefault("posted_at", utcnow() - timedelta(days=4))
    return RawJobRecord(**payload)


def build_profile(session: Session) -> CandidateProfile:
    """The real candidate profile, as configured from the parsed resume."""
    repository = ProfileRepository(session)
    profile = repository.get_or_create_default()
    repository.update(
        profile,
        {
            "full_name": "Tushar Gautam",
            "experience_level": "fresher",
            "years_experience": 0.4,
            "target_titles": [
                "Software Engineer",
                "Software Developer",
                "Backend Developer",
                "Python Developer",
                "Frontend Developer",
                "Full-Stack Developer",
                "AI Engineer",
                "Generative AI Engineer",
                "Agentic AI Engineer",
                "LLM Application Developer",
                "Machine Learning Engineer",
                "Cloud Engineer",
                "DevOps Engineer",
                "Junior Platform Engineer",
            ],
            "technical_skills": [
                "python",
                "javascript",
                "typescript",
                "c++",
                "c",
                "fastapi",
                "node.js",
                "express.js",
                "react",
                "next.js",
                "tailwind",
                "mongodb",
                "postgresql",
                "mysql",
                "redis",
                "firebase",
                "docker",
                "kubernetes",
                "aws",
                "github actions",
                "git",
                "github",
                "linux",
                "postman",
                "langchain",
                "llm",
                "agentic ai",
                "css",
                "sql",
            ],
            "preferred_locations": ["Remote", "Gurgaon", "Delhi NCR", "Noida", "Bengaluru"],
            "work_arrangements": ["remote", "hybrid", "onsite"],
            "employment_types": ["full_time", "internship"],
            "max_job_age_days": 45,
            "minimum_match_score": 65.0,
        },
    )
    session.flush()
    return profile


def score_dataset(session: Session, profile: CandidateProfile) -> list[Scored]:
    """Ingest every labelled row through the real pipeline, then score it."""
    service = JobIngestService(session)
    results: list[Scored] = []
    for entry in load_dataset():
        record = _record(entry)
        report = service.ingest([record], source=record.source, trigger="benchmark")
        if not report.created_job_ids:
            continue
        job = session.get(Job, report.created_job_ids[0])
        if job is None:
            continue
        result = score_job(job, profile)
        results.append(
            Scored(
                label=entry["label"],
                expect=entry["expect"],
                why=entry["why"],
                title=job.title,
                company=job.company,
                score=result.total_score,
                band=result.band,
                confidence=result.confidence,
                evidence_coverage=result.evidence_coverage,
                filtered_out=result.filtered_out,
                filter_reasons=list(result.filter_reasons),
                category_scores=result.category_scores,
                explanation=list(result.explanation),
            )
        )
    return results


def rank(results: list[Scored]) -> list[Scored]:
    """Order rows the way the job feed does: eligible first, then band, then score."""
    eligible = [row for row in results if not row.filtered_out]
    return sorted(eligible, key=lambda row: (_BAND_RANK.get(row.band, 3), -row.score))


def precision_at(results: list[Scored], k: int) -> float:
    """Share of the top ``k`` ranked rows that are worth applying to.

    ``adjacent`` rows are neither credited nor penalised, so they are removed from the
    ranking before the cut rather than counted as errors.
    """
    judged = [row for row in rank(results) if row.is_good or row.is_bad]
    top = judged[:k]
    if not top:
        return 0.0
    return sum(1 for row in top if row.is_good) / len(top)


def false_positive_rate(results: list[Scored], threshold: float) -> float:
    """Share of unsuitable rows that score at or above the candidate's own threshold."""
    bad = [row for row in results if row.is_bad]
    if not bad:
        return 0.0
    above = [row for row in bad if not row.filtered_out and row.score >= threshold]
    return len(above) / len(bad)


def relevant_recall(results: list[Scored]) -> float:
    """Share of suitable rows that stay eligible and reach the review band or better."""
    good = [row for row in results if row.is_good]
    if not good:
        return 0.0
    kept = [row for row in good if not row.filtered_out and row.band in {"high", "review"}]
    return len(kept) / len(good)


def measure(results: list[Scored], threshold: float = 65.0) -> dict[str, float]:
    return {
        "precision_at_10": round(precision_at(results, 10), 4),
        "precision_at_20": round(precision_at(results, 20), 4),
        "false_positive_rate_above_threshold": round(false_positive_rate(results, threshold), 4),
        "relevant_recall": round(relevant_recall(results), 4),
        "bad_rows_in_high_band": float(
            sum(1 for row in results if row.is_bad and row.band == "high")
        ),
    }


@pytest.fixture
def benchmark(session: Session) -> list[Scored]:
    profile = build_profile(session)
    return score_dataset(session, profile)


def _baseline() -> dict[str, Any]:
    return json.loads(BASELINE.read_text())


# --------------------------------------------------------------------------------------
# Dataset integrity
# --------------------------------------------------------------------------------------


def test_the_dataset_covers_every_category_the_benchmark_claims_to_test() -> None:
    labels = {entry["label"] for entry in load_dataset()}
    assert labels == {
        "relevant",
        "adjacent",
        "senior",
        "support",
        "irrelevant",
        "adversarial",
        "preference_mismatch",
        "over_experience_bar",
        "edge",
    }


def test_every_row_is_a_real_listing_with_recorded_provenance() -> None:
    for entry in load_dataset():
        provenance = entry["provenance"]
        assert provenance["fetched_from"].startswith("https://")
        assert provenance["api"] in {"ashby", "smartrecruiters", "remoteok"}
        assert entry["why"].strip(), "every label must carry the reason it was assigned"


def test_the_dataset_is_large_and_balanced_enough_to_measure(benchmark: list[Scored]) -> None:
    good = [row for row in benchmark if row.is_good]
    bad = [row for row in benchmark if row.is_bad]
    assert len(benchmark) >= 35
    assert len(good) >= 7
    assert len(bad) >= 20


# --------------------------------------------------------------------------------------
# Quality metrics, measured against the versioned baseline
# --------------------------------------------------------------------------------------


def test_no_unsuitable_listing_reaches_the_high_band(benchmark: list[Scored]) -> None:
    offenders = [
        f"{row.title} @ {row.company} ({row.label}, {row.score:g})"
        for row in benchmark
        if row.is_bad and row.band == "high"
    ]
    assert offenders == []


def test_no_unsuitable_listing_clears_the_candidates_own_threshold(
    benchmark: list[Scored],
) -> None:
    """65 is the score at which this candidate would prepare an application."""
    offenders = [
        f"{row.title} @ {row.company} ({row.label}, {row.score:g})"
        for row in benchmark
        if row.is_bad and not row.filtered_out and row.score >= 65.0
    ]
    assert offenders == []


def test_precision_at_10_is_no_worse_than_the_baseline(benchmark: list[Scored]) -> None:
    measured = precision_at(benchmark, 10)
    baseline = _baseline()["metrics"]["precision_at_10"]
    assert measured >= baseline, f"precision@10 regressed: {measured} < {baseline}"


def test_precision_at_20_is_no_worse_than_the_baseline(benchmark: list[Scored]) -> None:
    measured = precision_at(benchmark, 20)
    baseline = _baseline()["metrics"]["precision_at_20"]
    assert measured >= baseline, f"precision@20 regressed: {measured} < {baseline}"


def test_the_false_positive_rate_is_no_worse_than_the_baseline(benchmark: list[Scored]) -> None:
    measured = false_positive_rate(benchmark, 65.0)
    baseline = _baseline()["metrics"]["false_positive_rate_above_threshold"]
    assert measured <= baseline, f"false-positive rate regressed: {measured} > {baseline}"


def test_relevant_recall_is_no_worse_than_the_baseline(benchmark: list[Scored]) -> None:
    measured = relevant_recall(benchmark)
    baseline = _baseline()["metrics"]["relevant_recall"]
    assert measured >= baseline, f"recall regressed: {measured} < {baseline}"


def test_adjacent_roles_stay_eligible_rather_than_being_filtered_away(
    benchmark: list[Scored],
) -> None:
    """A role in the right family with a higher bar is the candidate's call, not ours."""
    for row in benchmark:
        if row.label == "adjacent":
            assert not row.filtered_out, f"{row.title}: {row.filter_reasons}"


def test_a_bar_stated_only_in_prose_is_enforced_like_a_structured_one(
    benchmark: list[Scored],
) -> None:
    """Regression: these ranked in the high band above every genuinely suitable listing.

    Each one states five to seven years, but in its description rather than in a
    structured field, so the experience filter never saw it.
    """
    rows = [row for row in benchmark if row.label == "over_experience_bar"]
    assert len(rows) >= 5
    for row in rows:
        assert row.filtered_out, f"{row.title} should have been filtered"
        assert any("years of experience" in reason for reason in row.filter_reasons), (
            f"{row.title}: {row.filter_reasons}"
        )


def test_rows_excluded_by_a_hard_preference_are_excluded_with_a_stated_reason(
    benchmark: list[Scored],
) -> None:
    """Filtering an onsite role in an unaccepted city is correct, not a missed match."""
    rows = [row for row in benchmark if row.label == "preference_mismatch"]
    assert rows
    for row in rows:
        assert row.filtered_out, f"{row.title} should have been filtered"
        assert row.filter_reasons, f"{row.title} was filtered without a reason"


# --------------------------------------------------------------------------------------
# Honesty about evidence
# --------------------------------------------------------------------------------------


def test_a_listing_with_no_description_cannot_become_a_confident_match(
    benchmark: list[Scored],
) -> None:
    """ "Intern, Software Development" has a perfect title and an empty description."""
    sparse = [row for row in benchmark if row.expect == "sparse_no_description"]
    assert sparse, "the dataset must contain a listing with no usable description"
    for row in sparse:
        assert row.band != "high"
        assert row.confidence != "high"
        assert any("assess" in line or "sparse" in line for line in row.explanation)


def test_every_scored_row_explains_itself(benchmark: list[Scored]) -> None:
    for row in benchmark:
        assert row.explanation
        assert all(data["detail"] for data in row.category_scores.values())


def test_confidence_is_reported_separately_from_the_score(benchmark: list[Scored]) -> None:
    """Relevance and the strength of the evidence behind it are different questions."""
    for row in benchmark:
        assert row.confidence in {"high", "medium", "low"}
        assert 0.0 <= row.evidence_coverage <= 1.0
    assert {row.confidence for row in benchmark} != {"high"}, (
        "a benchmark where every row is high-confidence is not measuring confidence"
    )


# --------------------------------------------------------------------------------------
# Reported numbers, printed so a run records what it measured
# --------------------------------------------------------------------------------------


def test_report_measured_metrics(benchmark: list[Scored]) -> None:
    measured = measure(benchmark)
    baseline = _baseline()["metrics"]
    print("\n--- benchmark: current vs baseline ---")
    for key, value in measured.items():
        before = baseline.get(key)
        print(f"  {key:38s} baseline={before!s:8s} now={value}")
    print("\n--- top 15 ranked ---")
    for index, row in enumerate(rank(benchmark)[:15], 1):
        print(
            f"  {index:2d}. {row.score:5.1f} {row.band:6s} {row.confidence:6s} "
            f"[{row.label:11s}] {row.title[:44]} @ {row.company[:18]}"
        )
    assert measured
