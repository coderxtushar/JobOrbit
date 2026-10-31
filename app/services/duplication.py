"""Cross-source duplication analysis.

Deduplication happens at ingest time in :mod:`app.services.dedup`. This module reports on
the *result* afterwards, so the rate can be seen rather than assumed, and so the two ways
it can be wrong are both detectable:

* a **missed merge** — two stored jobs that are almost certainly the same posting, which
  inflates the feed and could lead to applying twice;
* a **false merge** — one stored job whose sightings disagree about what the job is, which
  would hide a real listing behind another one.

Both are reported as *suspects* with the evidence, never acted on automatically. Merging is
additive by design, so nothing here deletes a job, a sighting or an application.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Application, Job, JobSourceReference
from app.services.dedup import MatchKind
from app.services.text import collapse_whitespace, normalize_company

#: Two titles with at least this much token overlap describe the same role closely enough
#: to be worth a human look. Measured on live multi-source data: genuine repostings of one
#: role sit at or above this, while distinct roles at one company sit well below it.
MISSED_MERGE_TITLE_OVERLAP = 0.8

#: Below this overlap the sightings merged into one job disagree about what the job is.
FALSE_MERGE_TITLE_OVERLAP = 0.5

#: Pair search is quadratic inside a company bucket, so a company with an enormous board is
#: reported as skipped rather than silently stalling a diagnostics request.
MAX_BUCKET_FOR_PAIR_SEARCH = 400


def _tokens(title: str) -> frozenset[str]:
    """Tokenise a title as written, deliberately *not* via :func:`dedup._core_title`.

    An earlier version reused the dedup core, which made the detector blind to exactly the
    failures it exists to find: two "PhD - <topic>" postings both reduced to the core "phd",
    so the detector scored their overlap at 100% and reported the resulting false merge as
    healthy. Comparing the titles as written keeps detection independent of the function
    under test.
    """
    kept = [ch if ch.isalnum() or ch.isspace() else " " for ch in title.casefold()]
    return frozenset(collapse_whitespace("".join(kept)).split())


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


@dataclass(frozen=True, slots=True)
class MergedJob:
    job_id: int
    title: str
    company: str
    sources: tuple[str, ...]
    urls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MissedMergeSuspect:
    job_ids: tuple[int, int]
    titles: tuple[str, str]
    company: str
    sources: tuple[str, ...]
    title_overlap: float
    reason: str


@dataclass(frozen=True, slots=True)
class FalseMergeSuspect:
    job_id: int
    stored_title: str
    observed_titles: tuple[str, ...]
    observed_companies: tuple[str, ...]
    sources: tuple[str, ...]
    title_overlap: float
    reason: str


@dataclass(frozen=True, slots=True)
class NormalizationCollision:
    normalized_company: str
    raw_companies: tuple[str, ...]
    job_count: int


@dataclass
class DuplicationReport:
    jobs_total: int = 0
    sightings_total: int = 0
    merged_sightings: int = 0
    duplicate_rate: float = 0.0

    exact_duplicate_sightings: int = 0
    fuzzy_duplicate_sightings: int = 0
    sightings_by_rule: dict[str, int] = field(default_factory=dict)

    multi_source_jobs: int = 0
    cross_source_duplicate_rate: float = 0.0
    sources_seen: list[str] = field(default_factory=list)
    source_pair_overlaps: dict[str, int] = field(default_factory=dict)

    jobs_with_application: int = 0
    multi_source_jobs_with_application: int = 0

    missed_merge_suspects: list[MissedMergeSuspect] = field(default_factory=list)
    false_merge_suspects: list[FalseMergeSuspect] = field(default_factory=list)
    normalization_collisions: list[NormalizationCollision] = field(default_factory=list)
    buckets_skipped: list[str] = field(default_factory=list)

    @property
    def is_healthy(self) -> bool:
        return not self.false_merge_suspects and not self.normalization_collisions


def _load_sightings(session: Session) -> dict[int, list[JobSourceReference]]:
    grouped: dict[int, list[JobSourceReference]] = defaultdict(list)
    for reference in session.scalars(select(JobSourceReference)).all():
        grouped[reference.job_id].append(reference)
    return grouped


def _rule_counts(sightings: dict[int, list[JobSourceReference]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for references in sightings.values():
        for reference in references:
            rule = str((reference.source_metadata or {}).get("dedup") or MatchKind.NEW.value)
            counts[rule] += 1
    return dict(counts)


def _find_false_merges(
    jobs_by_id: dict[int, Job], sightings: dict[int, list[JobSourceReference]]
) -> list[FalseMergeSuspect]:
    suspects: list[FalseMergeSuspect] = []
    for job_id, references in sightings.items():
        job = jobs_by_id.get(job_id)
        if job is None or len(references) < 2:
            continue

        observed_titles = [
            str((reference.source_metadata or {}).get("observed_title") or "")
            for reference in references
        ]
        observed_companies = [
            str((reference.source_metadata or {}).get("observed_company") or "")
            for reference in references
        ]
        titled = [title for title in observed_titles if title]
        if len(titled) < 2:
            continue

        token_sets = [_tokens(title) for title in titled]
        worst = min(
            jaccard(token_sets[index], token_sets[other])
            for index in range(len(token_sets))
            for other in range(index + 1, len(token_sets))
        )
        companies = {normalize_company(name) for name in observed_companies if name}
        if worst >= FALSE_MERGE_TITLE_OVERLAP and len(companies) <= 1:
            continue

        reasons = []
        if worst < FALSE_MERGE_TITLE_OVERLAP:
            reasons.append(f"sighting titles overlap by only {worst:.0%}")
        if len(companies) > 1:
            reasons.append(f"sightings name {len(companies)} different companies")
        suspects.append(
            FalseMergeSuspect(
                job_id=job_id,
                stored_title=job.title,
                observed_titles=tuple(titled),
                observed_companies=tuple(name for name in observed_companies if name),
                sources=tuple(sorted({reference.source.value for reference in references})),
                title_overlap=round(worst, 4),
                reason="; ".join(reasons),
            )
        )
    return suspects


def _find_missed_merges(
    jobs: list[Job], sightings: dict[int, list[JobSourceReference]]
) -> tuple[list[MissedMergeSuspect], list[str]]:
    buckets: dict[str, list[Job]] = defaultdict(list)
    for job in jobs:
        buckets[normalize_company(job.company)].append(job)

    suspects: list[MissedMergeSuspect] = []
    skipped: list[str] = []
    for company, bucket in buckets.items():
        if len(bucket) < 2:
            continue
        if len(bucket) > MAX_BUCKET_FOR_PAIR_SEARCH:
            skipped.append(f"{company} ({len(bucket)} jobs)")
            continue
        for index, left in enumerate(bucket):
            left_tokens = _tokens(left.title)
            for right in bucket[index + 1 :]:
                overlap = jaccard(left_tokens, _tokens(right.title))
                if overlap < MISSED_MERGE_TITLE_OVERLAP:
                    continue
                left_sources = {reference.source.value for reference in sightings.get(left.id, [])}
                right_sources = {
                    reference.source.value for reference in sightings.get(right.id, [])
                }
                same_place = (left.location or "").strip().lower() == (
                    right.location or ""
                ).strip().lower()
                reasons = [f"titles overlap by {overlap:.0%} at the same company"]
                if same_place:
                    reasons.append("same stated location")
                if left_sources & right_sources:
                    reasons.append("seen on a shared platform, so one may be a repost")
                else:
                    reasons.append("seen on different platforms")
                suspects.append(
                    MissedMergeSuspect(
                        job_ids=(left.id, right.id),
                        titles=(left.title, right.title),
                        company=left.company,
                        sources=tuple(sorted(left_sources | right_sources)),
                        title_overlap=round(overlap, 4),
                        reason="; ".join(reasons),
                    )
                )
    return suspects, skipped


def _find_normalization_collisions(jobs: list[Job]) -> list[NormalizationCollision]:
    """Flag distinct employer names that normalization has collapsed into one key.

    Suffix-only differences ("Acme Ltd" vs "Acme") are the intended behaviour and are not
    reported; anything else means the normalizer is merging companies that differ.
    """
    grouped: dict[str, set[str]] = defaultdict(set)
    counts: dict[str, int] = defaultdict(int)
    for job in jobs:
        key = normalize_company(job.company)
        grouped[key].add(job.company.strip())
        counts[key] += 1

    collisions: list[NormalizationCollision] = []
    for key, raw_names in grouped.items():
        if len(raw_names) < 2:
            continue
        stripped = {name.lower().replace(".", "").replace(",", "").strip() for name in raw_names}
        if len({normalize_company(name) for name in stripped}) <= 1 and all(
            key in name.lower().replace(" ", "") or name.lower().replace(" ", "") in key
            for name in stripped
        ):
            continue
        collisions.append(
            NormalizationCollision(
                normalized_company=key,
                raw_companies=tuple(sorted(raw_names)),
                job_count=counts[key],
            )
        )
    return collisions


def analyse_duplication(session: Session, *, suspect_limit: int = 25) -> DuplicationReport:
    """Measure duplication across every stored job and sighting."""
    jobs = list(session.scalars(select(Job)).all())
    jobs_by_id = {job.id: job for job in jobs}
    sightings = _load_sightings(session)

    sightings_total = sum(len(references) for references in sightings.values())
    report = DuplicationReport(
        jobs_total=len(jobs),
        sightings_total=sightings_total,
        merged_sightings=max(sightings_total - len(jobs), 0),
    )
    if sightings_total:
        report.duplicate_rate = round(report.merged_sightings / sightings_total, 4)

    rule_counts = _rule_counts(sightings)
    report.sightings_by_rule = rule_counts
    report.exact_duplicate_sightings = rule_counts.get(
        MatchKind.SAME_SOURCE_ID.value, 0
    ) + rule_counts.get(MatchKind.SAME_URL.value, 0)
    report.fuzzy_duplicate_sightings = rule_counts.get(MatchKind.SAME_FINGERPRINT.value, 0)

    sources_seen: set[str] = set()
    pair_overlaps: dict[str, int] = defaultdict(int)
    for references in sightings.values():
        names = sorted({reference.source.value for reference in references})
        sources_seen.update(names)
        if len(names) > 1:
            report.multi_source_jobs += 1
            for index, left in enumerate(names):
                for right in names[index + 1 :]:
                    pair_overlaps[f"{left}+{right}"] += 1
    report.sources_seen = sorted(sources_seen)
    report.source_pair_overlaps = dict(
        sorted(pair_overlaps.items(), key=lambda item: -item[1])[:20]
    )
    if report.jobs_total:
        report.cross_source_duplicate_rate = round(report.multi_source_jobs / report.jobs_total, 4)

    applied_job_ids = set(
        session.scalars(select(Application.job_id).where(Application.job_id.isnot(None))).all()
    )
    report.jobs_with_application = len(applied_job_ids & set(jobs_by_id))
    report.multi_source_jobs_with_application = sum(
        1
        for job_id, references in sightings.items()
        if job_id in applied_job_ids
        and len({reference.source.value for reference in references}) > 1
    )

    report.false_merge_suspects = _find_false_merges(jobs_by_id, sightings)[:suspect_limit]
    missed, skipped = _find_missed_merges(jobs, sightings)
    report.missed_merge_suspects = sorted(missed, key=lambda item: -item.title_overlap)[
        :suspect_limit
    ]
    report.buckets_skipped = skipped
    report.normalization_collisions = _find_normalization_collisions(jobs)[:suspect_limit]
    return report


def sighting_count(session: Session) -> int:
    return int(session.scalar(select(func.count(JobSourceReference.id))) or 0)
