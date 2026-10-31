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
_CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}


@dataclass(slots=True)
class Scored:
    label: str
    expect: str
    why: str
    job_family: str
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
                job_family=entry.get("job_family", "unknown"),
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
    """Order rows the way the job feed does: eligible, then band, then confidence, then score."""
    eligible = [row for row in results if not row.filtered_out]
    return sorted(
        eligible,
        key=lambda row: (
            _BAND_RANK.get(row.band, 3),
            _CONFIDENCE_RANK.get(row.confidence, 3),
            -row.score,
        ),
    )


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


def per_family(results: list[Scored]) -> dict[str, dict[str, float]]:
    """Metrics restricted to each target family's own rows.

    An aggregate number can hide a family that ranks badly, because the largest family
    dominates it. Non-target rows carry no family of their own, so they are pooled under
    ``non_target`` where only the false-positive rate is meaningful.
    """
    families = sorted({row.job_family for row in results})
    report: dict[str, dict[str, float]] = {}
    for family in families:
        rows = [row for row in results if row.job_family == family]
        good = [row for row in rows if row.is_good]
        bad = [row for row in rows if row.is_bad]
        report[family] = {
            "rows": float(len(rows)),
            "relevant_rows": float(len(good)),
            "unsuitable_rows": float(len(bad)),
            "relevant_recall": round(relevant_recall(rows), 4) if good else -1.0,
            "false_positive_rate": round(false_positive_rate(rows, 65.0), 4) if bad else -1.0,
            "mean_score_relevant": (
                round(sum(row.score for row in good) / len(good), 2) if good else -1.0
            ),
        }
    return report


def confidence_calibration(results: list[Scored]) -> dict[str, dict[str, float]]:
    """Does a confidence label predict whether the row is actually suitable?

    Calibration is the honest check on the confidence field: if ``high`` confidence rows
    are no more often suitable than ``low`` confidence rows, the label carries no
    information and should not be shown to the user as if it did.
    """
    report: dict[str, dict[str, float]] = {}
    for level in ("high", "medium", "low"):
        rows = [row for row in results if row.confidence == level]
        judged = [row for row in rows if row.is_good or row.is_bad]
        report[level] = {
            "rows": float(len(rows)),
            "judged_rows": float(len(judged)),
            "share_suitable": (
                round(sum(1 for row in judged if row.is_good) / len(judged), 4) if judged else -1.0
            ),
            "mean_evidence_coverage": (
                round(sum(row.evidence_coverage for row in rows) / len(rows), 4) if rows else -1.0
            ),
        }
    return report


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
        "senior",
        "support",
        "irrelevant",
        "adversarial",
        "preference_mismatch",
        "over_experience_bar",
        "sparse",
        "location_restricted",
    }


def test_the_dataset_covers_every_target_job_family() -> None:
    """Each family the profile targets needs enough rows for its own metrics to mean anything."""
    families: dict[str, int] = {}
    for entry in load_dataset():
        if entry["label"] == "relevant":
            families[entry["job_family"]] = families.get(entry["job_family"], 0) + 1
    assert set(families) == {
        "software_general",
        "backend_python",
        "frontend",
        "genai_agentic",
        "cloud_devops",
    }
    thin = {family: count for family, count in families.items() if count < 5}
    assert not thin, f"too few relevant rows to measure these families: {thin}"


def test_the_dataset_is_india_and_remote_weighted_for_this_candidate() -> None:
    relevant = [entry for entry in load_dataset() if entry["label"] == "relevant"]
    india = [entry for entry in relevant if entry["location_class"] == "india"]
    reachable = [
        entry
        for entry in relevant
        if entry["location_class"] in {"india", "remote"}
        or (entry["record"].get("work_arrangement") or "") == "remote"
    ]
    assert len(reachable) == len(relevant), (
        "a row the candidate should apply to must be India-located or remote"
    )
    assert india, "the dataset must contain India-located rows the candidate should apply to"


def test_every_row_is_a_real_listing_with_recorded_provenance() -> None:
    publishers = {
        "ashby",
        "smartrecruiters",
        "remoteok",
        "greenhouse",
        "lever",
        "workable",
        "arbeitnow",
        "himalayas",
        "jobicy",
        "employer_site",
    }
    for entry in load_dataset():
        provenance = entry["provenance"]
        assert provenance["fetched_from"].startswith("https://")
        assert "example.com" not in provenance["fetched_from"], (
            "a hand-written listing cannot be evidence that a rule works"
        )
        assert provenance["api"] in publishers
        assert entry["why"].strip(), "every label must carry the reason it was assigned"


def test_the_dataset_is_large_and_balanced_enough_to_measure(benchmark: list[Scored]) -> None:
    good = [row for row in benchmark if row.is_good]
    bad = [row for row in benchmark if row.is_bad]
    assert len(benchmark) >= 150
    assert len(good) >= 40
    assert len(bad) >= 60


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
    measured = measure(benchmark)["precision_at_10"]
    baseline = _baseline()["metrics"]["precision_at_10"]
    assert measured >= baseline, f"precision@10 regressed: {measured} < {baseline}"


def test_precision_at_20_is_no_worse_than_the_baseline(benchmark: list[Scored]) -> None:
    measured = measure(benchmark)["precision_at_20"]
    baseline = _baseline()["metrics"]["precision_at_20"]
    assert measured >= baseline, f"precision@20 regressed: {measured} < {baseline}"


def test_the_false_positive_rate_is_no_worse_than_the_baseline(benchmark: list[Scored]) -> None:
    measured = measure(benchmark)["false_positive_rate_above_threshold"]
    baseline = _baseline()["metrics"]["false_positive_rate_above_threshold"]
    assert measured <= baseline, f"false-positive rate regressed: {measured} > {baseline}"


def test_relevant_recall_is_no_worse_than_the_baseline(benchmark: list[Scored]) -> None:
    measured = measure(benchmark)["relevant_recall"]
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
    sparse = [row for row in benchmark if row.expect == "not_confident"]
    assert sparse, "the dataset must contain a listing with no usable description"
    for row in sparse:
        assert row.band != "high"
        assert row.confidence != "high"
        assert any(
            "assess" in line or "sparse" in line or "words" in line or "inferred" in line
            for line in row.explanation
        ), f"{row.title} gave no reason for its low confidence"


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


def test_no_job_family_recommends_an_unsuitable_listing(benchmark: list[Scored]) -> None:
    """A clean aggregate must not hide one family that recommends the wrong roles."""
    report = per_family(benchmark)
    baseline = _baseline()["per_family"]
    offenders = {
        family: values["false_positive_rate"]
        for family, values in report.items()
        if values["false_positive_rate"] > baseline.get(family, {}).get("false_positive_rate", 0.0)
    }
    assert not offenders, f"these families got worse at recommending unsuitable roles: {offenders}"


def test_every_target_family_keeps_enough_rows_to_be_measured(benchmark: list[Scored]) -> None:
    report = per_family(benchmark)
    for family in (
        "software_general",
        "backend_python",
        "frontend",
        "genai_agentic",
        "cloud_devops",
    ):
        assert family in report, f"{family} disappeared from the dataset"
        assert report[family]["relevant_rows"] >= 5, (
            f"{family} has only {report[family]['relevant_rows']:g} suitable rows, too few to measure"
        )


def test_confidence_predicts_suitability_rather_than_being_decorative(
    benchmark: list[Scored],
) -> None:
    """A confidence label the user is shown must carry information.

    If medium-confidence rows were no more often suitable than low-confidence ones, the
    label would be noise presented as a judgement, which is exactly what the project's
    honesty rules forbid.
    """
    calibration = confidence_calibration(benchmark)
    medium, low = calibration["medium"], calibration["low"]
    assert medium["judged_rows"] >= 20 and low["judged_rows"] >= 10, (
        "too few judged rows in each bucket for calibration to mean anything"
    )
    assert medium["share_suitable"] > low["share_suitable"], (
        f"medium confidence is no more often suitable ({medium['share_suitable']}) than "
        f"low ({low['share_suitable']}), so the label carries no information"
    )
    assert medium["mean_evidence_coverage"] > low["mean_evidence_coverage"], (
        "a higher confidence label must rest on more evidence, not less"
    )


def test_high_confidence_is_not_awarded_without_published_requirements(
    benchmark: list[Scored],
) -> None:
    """Records a known gap: no real listing in the dataset reaches high confidence.

    This is asserted rather than left implicit so that a future change which starts
    awarding 'high' is noticed and justified, instead of quietly relaxing the bar.
    """
    high = [row for row in benchmark if row.confidence == "high"]
    expected = _baseline()["confidence_calibration"]["high"]["rows"]
    assert float(len(high)) == expected, (
        f"{len(high)} rows now earn high confidence against a recorded {expected:g}; "
        "if this is intended, update eval_baseline.json deliberately"
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
    print("\n--- per job family ---")
    for family, values in per_family(benchmark).items():
        print(
            f"  {family:18s} rows={values['rows']:5.0f} relevant={values['relevant_rows']:4.0f} "
            f"recall={values['relevant_recall']:7.4f} fpr={values['false_positive_rate']:7.4f} "
            f"mean_relevant_score={values['mean_score_relevant']:6.2f}"
        )
    print("\n--- confidence calibration ---")
    for level, values in confidence_calibration(benchmark).items():
        print(
            f"  {level:6s} rows={values['rows']:5.0f} judged={values['judged_rows']:5.0f} "
            f"share_suitable={values['share_suitable']:7.4f} "
            f"mean_coverage={values['mean_evidence_coverage']:7.4f}"
        )
    print("\n--- top 15 ranked ---")
    for index, row in enumerate(rank(benchmark)[:15], 1):
        print(
            f"  {index:2d}. {row.score:5.1f} {row.band:6s} {row.confidence:6s} "
            f"[{row.label:11s}] {row.title[:44]} @ {row.company[:18]}"
        )
    assert measured
