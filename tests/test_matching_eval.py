"""Match-quality evaluation against a labelled dataset.

``tests/fixtures/eval_jobs.json`` holds job listings labelled relevant, irrelevant,
adversarial or edge for the real candidate profile. This module scores every one of them
and asserts aggregate quality, which turns "the matcher feels about right" into a number
that fails the build when it regresses.

The adversarial rows are the point of the exercise. A listing that shares only the word
"Engineer", or lists Linux and Docker for a support role, is the case where naive token
overlap puts something unsuitable at the top of the feed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CandidateProfile, Job, JobSourceReference, SourceName, utcnow
from app.db.repositories import ProfileRepository
from app.schemas.job import RawJobRecord
from app.services.ingest import IngestReport, JobIngestService
from app.services.scoring import ScoringService

FIXTURE = Path(__file__).parent / "fixtures" / "eval_jobs.json"

#: Quality floors. These are deliberately strict on false positives: an unsuitable job in
#: the high band costs an application and the candidate's credibility with that employer,
#: whereas a relevant job landing in "worth a look" still gets seen.
MIN_RELEVANT_RECALL = 0.90
MAX_IRRELEVANT_IN_HIGH = 0
MAX_ADVERSARIAL_IN_HIGH = 0


@dataclass(slots=True)
class Scored:
    label: str
    expect: str
    why: str
    title: str
    company: str
    job: Job
    score: float
    band: str
    filtered_out: bool
    filter_reasons: list[str]
    category_scores: dict[str, Any]
    explanation: list[str]
    matched_skills: list[str]
    missing_required: list[str]


def _load() -> list[dict[str, Any]]:
    return json.loads(FIXTURE.read_text())["jobs"]


def _record(entry: dict[str, Any]) -> RawJobRecord:
    payload = dict(entry["record"])
    days_ago = payload.pop("posted_days_ago", None)
    if days_ago is not None:
        payload["posted_at"] = utcnow() - timedelta(days=int(days_ago))
    elif entry["expect"] != "freshness_unassessable":
        payload.setdefault("posted_at", utcnow() - timedelta(days=5))
    return RawJobRecord(**payload)


def _ingest_dataset(session: Session) -> tuple[dict[str, Job], IngestReport]:
    """Load the dataset through the real pipeline, so dedup runs as it does in production.

    Inserting rows directly would bypass deduplication, and the dataset deliberately
    contains a cross-platform duplicate pair whose whole purpose is to be merged.
    """
    entries = _load()
    service = JobIngestService(session)
    report = service.ingest(
        [_record(entry) for entry in entries],
        source=SourceName.MANUAL,
        trigger="eval",
    )
    session.flush()

    by_external: dict[str, Job] = {}
    for entry in entries:
        external_id = entry["record"]["external_id"]
        reference = session.scalars(
            select(JobSourceReference).where(JobSourceReference.external_id == external_id)
        ).first()
        if reference is not None:
            job = session.get(Job, reference.job_id)
            if job is not None:
                by_external[external_id] = job
    return by_external, report


@pytest.fixture
def eval_profile(session: Session) -> CandidateProfile:
    """The real candidate profile: 2026 B.Tech CSE grad, ~0.4 years, Python/AI/cloud."""
    repository = ProfileRepository(session)
    profile = repository.get_or_create_default()
    repository.update(
        profile,
        {
            "full_name": "Tushar Gautam",
            "email": "tushar.gautam.dev@gmail.com",
            "experience_level": "fresher",
            "years_experience": 0.4,
            "graduation_date": "2026",
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
                "mongoose",
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
                "llm evaluation",
                "ai agent benchmarking",
                "evaluation harnesses",
                "benchmarking pipelines",
                "regression detection",
                "automated test execution",
                "css",
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


@pytest.fixture
def ingested(session: Session, eval_profile: CandidateProfile):
    return _ingest_dataset(session)


@pytest.fixture
def scored_dataset(session: Session, eval_profile: CandidateProfile, ingested) -> list[Scored]:
    by_external, _report = ingested
    service = ScoringService(session)
    results: list[Scored] = []
    seen: set[int] = set()
    for entry in _load():
        job = by_external.get(entry["record"]["external_id"])
        if job is None or job.id in seen:
            continue
        seen.add(job.id)
        match = service.score_one(job, eval_profile)
        results.append(
            Scored(
                label=entry["label"],
                expect=entry["expect"],
                why=entry["why"],
                title=job.title,
                company=job.company,
                job=job,
                score=match.total_score,
                band=match.band,
                filtered_out=match.filtered_out,
                filter_reasons=list(match.filter_reasons),
                category_scores=dict(match.category_scores),
                explanation=list(match.explanation),
                matched_skills=list(match.matched_skills),
                missing_required=list(match.missing_required_skills),
            )
        )
    session.flush()
    return results


def _of(results: list[Scored], label: str) -> list[Scored]:
    return [item for item in results if item.label == label]


def test_the_cross_platform_duplicate_pair_collapses_into_one_job(ingested) -> None:
    """Two platforms advertising one posting must become one job with both references."""
    by_external, report = ingested
    first = by_external.get("EV-E03")
    second = by_external.get("EV-E04")
    assert first is not None and second is not None
    assert first.id == second.id, "the duplicate pair was stored as two separate jobs"
    assert report.duplicates_detected >= 1
    sources = {reference.source for reference in first.source_references}
    assert len(sources) >= 2, f"only one source reference survived: {sources}"
    # The richer listing must enrich, never overwrite: skills union across both sightings.
    assert {"python", "fastapi", "postgresql", "docker"} <= set(first.required_skills)


def test_dataset_is_balanced_enough_to_measure_anything(scored_dataset: list[Scored]) -> None:
    assert len(_of(scored_dataset, "relevant")) >= 10
    assert len(_of(scored_dataset, "irrelevant")) >= 8
    assert len(_of(scored_dataset, "adversarial")) >= 4
    assert len(_of(scored_dataset, "edge")) >= 5


def test_relevant_jobs_are_not_rejected(scored_dataset: list[Scored]) -> None:
    """A relevant job must survive the hard filters and reach at least the review band."""
    relevant = _of(scored_dataset, "relevant")
    kept = [item for item in relevant if not item.filtered_out and item.band in {"high", "review"}]
    recall = len(kept) / len(relevant)
    missed = [
        f"{item.title} @ {item.company} -> {item.score:.1f}/{item.band}"
        f" filtered={item.filtered_out} reasons={item.filter_reasons}"
        for item in relevant
        if item not in kept
    ]
    assert recall >= MIN_RELEVANT_RECALL, f"recall {recall:.0%}; missed: {missed}"


def test_no_irrelevant_job_reaches_the_high_band(scored_dataset: list[Scored]) -> None:
    offenders = [
        f"{item.title} @ {item.company} -> {item.score:.1f}/{item.band} ({item.why})"
        for item in _of(scored_dataset, "irrelevant")
        if item.band == "high" and not item.filtered_out
    ]
    assert len(offenders) <= MAX_IRRELEVANT_IN_HIGH, f"unsuitable jobs ranked high: {offenders}"


def test_no_adversarial_job_reaches_the_high_band(scored_dataset: list[Scored]) -> None:
    """Surface token overlap must not promote an unsuitable role."""
    offenders = [
        f"{item.title} @ {item.company} -> {item.score:.1f}/{item.band} ({item.why})"
        for item in _of(scored_dataset, "adversarial")
        if item.band == "high" and not item.filtered_out
    ]
    assert len(offenders) <= MAX_ADVERSARIAL_IN_HIGH, f"adversarial jobs ranked high: {offenders}"


def test_relevant_jobs_outrank_irrelevant_ones_on_average(
    scored_dataset: list[Scored],
) -> None:
    relevant = _of(scored_dataset, "relevant")
    unsuitable = _of(scored_dataset, "irrelevant") + _of(scored_dataset, "adversarial")
    relevant_mean = sum(item.score for item in relevant) / len(relevant)
    unsuitable_mean = sum(item.score for item in unsuitable) / len(unsuitable)
    assert relevant_mean - unsuitable_mean >= 20.0, (
        f"separation too small: relevant {relevant_mean:.1f} vs unsuitable {unsuitable_mean:.1f}"
    )


def test_the_worst_relevant_job_outranks_the_best_unsuitable_one(
    scored_dataset: list[Scored],
) -> None:
    """Ranking is what the user actually sees, so the orderings must not interleave badly."""
    relevant = sorted(_of(scored_dataset, "relevant"), key=lambda item: item.score)
    unsuitable = sorted(
        _of(scored_dataset, "irrelevant") + _of(scored_dataset, "adversarial"),
        key=lambda item: item.score,
        reverse=True,
    )
    best_unsuitable = unsuitable[0]
    better_than_relevant = [item for item in relevant if item.score < best_unsuitable.score]
    assert len(better_than_relevant) <= 2, (
        f"'{best_unsuitable.title}' at {best_unsuitable.score:.1f} outranks "
        f"{len(better_than_relevant)} relevant jobs: "
        + ", ".join(f"{i.title} ({i.score:.1f})" for i in better_than_relevant)
    )


def test_no_unsuitable_job_clears_the_candidates_own_score_threshold(
    scored_dataset: list[Scored], eval_profile: CandidateProfile
) -> None:
    """The threshold the user sets is what a bulk run selects on, so it is the real gate.

    A job above minimum_match_score and not filtered out WILL be picked up by
    "prepare everything at or above my threshold", which is the expensive mistake.
    """
    threshold = eval_profile.minimum_match_score
    offenders = [
        f"{item.title} @ {item.company} -> {item.score:.1f} (>= {threshold}) [{item.label}]"
        for item in _of(scored_dataset, "irrelevant") + _of(scored_dataset, "adversarial")
        if item.score >= threshold and not item.filtered_out
    ]
    assert not offenders, f"a bulk run at the user's own threshold would prepare: {offenders}"


def test_a_title_only_listing_cannot_outrank_fully_assessed_matches(
    session: Session, eval_profile: CandidateProfile, scored_dataset: list[Scored]
) -> None:
    """Ranking is what the user sees, and it must not be led by an empty listing.

    "Terse Listings Inc" publishes no skills and no experience, so the only assessable
    category is its title, which scores ~100 and carried the whole redistributed weight.
    Ordering by raw score alone put it second in the feed, above eleven real matches.
    """
    from app.db.repositories import JobQuery, JobRepository

    feed = JobRepository(session).list(
        JobQuery(profile_id=eval_profile.id, sort_by="score", descending=True, limit=12)
    )
    titles = [job.title for job in feed]
    assert titles, "the feed came back empty"

    by_title = {item.title: item for item in scored_dataset}
    for position, title in enumerate(titles):
        scored = by_title.get(title)
        if scored is None:
            continue
        assert scored.band == "high", (
            f"position {position + 1} of the feed is '{title}' in band "
            f"'{scored.band}' (score {scored.score:.1f}) while high-band matches exist"
        )


def test_a_generic_word_overlap_does_not_earn_title_credit(
    scored_dataset: list[Scored],
) -> None:
    """Sharing only the word 'engineer' must be reported as meaningless, not scored as fit.

    Two independent rules can catch this row: the generic-token cap, and the stronger
    role-family rule which recognises "support" as a different discipline. Either is a
    valid explanation, so the assertion requires a stated reason rather than one wording.
    """
    support = next(
        item for item in scored_dataset if item.title.startswith("Technical Support Engineer")
    )
    title = support.category_scores.get("title")
    assert isinstance(title, dict)
    assert float(title["score"]) <= 25.0, title
    detail = str(title["detail"]).lower()
    assert "generic" in detail or "not among the kinds of work" in detail, title

    mechanical = next(
        item for item in scored_dataset if item.title.startswith("Mechanical Design Engineer")
    )
    mechanical_title = mechanical.category_scores.get("title")
    assert isinstance(mechanical_title, dict)
    assert float(mechanical_title["score"]) <= 25.0, mechanical_title


def test_a_real_title_match_is_not_damaged_by_the_generic_rule(
    scored_dataset: list[Scored],
) -> None:
    """The cap must only bite when the overlap is generic-only."""
    for prefix, floor in (
        ("Software Engineer - Backend", 70.0),
        ("Agentic AI Engineer", 70.0),
        ("Cloud Engineer - Associate", 70.0),
        ("DevOps Engineer", 70.0),
    ):
        item = next(entry for entry in scored_dataset if entry.title.startswith(prefix))
        title = item.category_scores.get("title")
        assert isinstance(title, dict)
        assert float(title["score"]) >= floor, f"{prefix} title scored {title}"


def test_every_score_carries_an_explanation(scored_dataset: list[Scored]) -> None:
    for item in scored_dataset:
        assert item.explanation, f"{item.title} scored {item.score} with no explanation"
        assert item.category_scores, f"{item.title} has no category breakdown"


def test_experience_eligibility_is_reflected_for_senior_roles(
    scored_dataset: list[Scored],
) -> None:
    """A role demanding many years must be penalised or filtered, never silently fine."""
    senior = [
        item
        for item in scored_dataset
        if item.label in {"irrelevant", "adversarial"}
        and any(
            token in item.job.experience_raw.lower()
            for token in ("8-12", "10+", "12+", "9-14", "5-8", "6-9", "4-7")
        )
    ]
    assert senior, "dataset lost its senior-role rows"
    for item in senior:
        experience = item.category_scores.get("experience")
        penalised = isinstance(experience, dict) and float(experience.get("score", 100)) <= 50.0
        assert penalised or item.filtered_out or item.band != "high", (
            f"{item.title} requires {item.job.experience_raw} but experience scored "
            f"{experience} and it landed in {item.band}"
        )


def test_a_missing_posting_date_is_unassessable_not_zero(
    scored_dataset: list[Scored],
) -> None:
    dateless = [item for item in scored_dataset if item.expect == "freshness_unassessable"]
    assert dateless
    for item in dateless:
        freshness = item.category_scores.get("freshness")
        assert isinstance(freshness, dict)
        assert freshness.get("assessable") is False, freshness
        assert any("freshness" in line.lower() for line in item.explanation)


def test_a_stale_posting_scores_low_on_freshness(scored_dataset: list[Scored]) -> None:
    stale = [item for item in scored_dataset if item.expect == "stale"]
    assert stale
    for item in stale:
        freshness = item.category_scores.get("freshness")
        assert isinstance(freshness, dict)
        assert freshness.get("assessable") is True
        assert float(freshness.get("score", 100)) <= 25.0, freshness


def test_inferred_skills_are_capped_and_labelled(scored_dataset: list[Scored]) -> None:
    inferred = [item for item in scored_dataset if item.expect == "skills_inferred_capped"]
    assert inferred
    for item in inferred:
        skills = item.category_scores.get("skills")
        assert isinstance(skills, dict)
        assert float(skills.get("score", 100)) <= 75.0, skills
        assert item.band != "high", f"{item.title} published no requirements yet ranked high"


@pytest.mark.skipif(
    "not config.getoption('-s', default=False) and True",
    reason="reporting helper; run with -s and -k report to print the ranking",
)
def test_report_ranking(scored_dataset: list[Scored]) -> None:
    """Print the observed ranking. Not an assertion - a measurement you can read."""
    rows = sorted(scored_dataset, key=lambda item: item.score, reverse=True)
    print()
    print(f"{'score':>6} {'band':<7} {'label':<12} {'filt':<5} title @ company")
    print("-" * 96)
    for item in rows:
        print(
            f"{item.score:6.1f} {item.band:<7} {item.label:<12} "
            f"{'YES' if item.filtered_out else '-':<5} {item.title[:44]} @ {item.company[:20]}"
        )
    relevant = [item for item in rows if item.label == "relevant"]
    unsuitable = [item for item in rows if item.label in ("irrelevant", "adversarial")]
    print()
    print(
        f"relevant   n={len(relevant):2d} "
        f"mean={sum(i.score for i in relevant) / len(relevant):.1f} "
        f"min={min(i.score for i in relevant):.1f} max={max(i.score for i in relevant):.1f}"
    )
    print(
        f"unsuitable n={len(unsuitable):2d} "
        f"mean={sum(i.score for i in unsuitable) / len(unsuitable):.1f} "
        f"min={min(i.score for i in unsuitable):.1f} max={max(i.score for i in unsuitable):.1f}"
    )
    print(
        f"relevant in high band    : {sum(1 for i in relevant if i.band == 'high')}/{len(relevant)}"
    )
    print(
        "unsuitable in high band  : "
        f"{sum(1 for i in unsuitable if i.band == 'high' and not i.filtered_out)}/{len(unsuitable)}"
    )
    print(
        f"unsuitable filtered out  : {sum(1 for i in unsuitable if i.filtered_out)}/{len(unsuitable)}"
    )


def test_report_problem_rows(scored_dataset: list[Scored]) -> None:
    """Print category detail for the rows that rank suspiciously. Measurement, not gate."""
    import json as _json

    targets = {
        "Software Engineer",
        "Software Engineer II - Backend",
        "Technical Support Engineer - Tier 1",
        "Senior Staff Software Engineer",
        "AI Prompt Engineer - Content Marketing",
    }
    for item in scored_dataset:
        if item.title not in targets:
            continue
        print()
        print(
            f"=== {item.title} @ {item.company} -> {item.score:.1f} / {item.band} "
            f"filtered={item.filtered_out}"
        )
        print(
            f"    experience_raw={item.job.experience_raw!r} required={item.job.required_skills} "
        )
        for name, detail in item.category_scores.items():
            print(f"    {name:12s} {_json.dumps(detail, default=str)[:150]}")
        print(f"    reasons={item.filter_reasons}")
        for line in item.explanation[:6]:
            print(f"    ~ {line[:120]}")
