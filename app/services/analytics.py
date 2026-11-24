"""Job-search analytics.

Three groups, kept apart on purpose:

``discovery``
    what the app found, and from where.
``quality``
    how trustworthy that haul is - duplicate rate, stale rate, undated listings,
    confidence distribution.
``outcomes``
    what the *user* did, and what employers did back.

Nothing here invents a success metric. Where no data exists the field is zero or ``None``
with the reason stated, because a job search that has produced no interviews must not
render as though it had. Recommendation precision in particular is reported as unavailable:
measuring it needs listings a human has labelled, which no running installation has.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import timedelta

from sqlalchemy.orm import Session

from app.db.models import CandidateProfile, utcnow
from app.db.repositories import (
    ApplicationRepository,
    ImportRunRepository,
    JobRepository,
    MatchRepository,
)
from app.services.duplication import analyse_duplication

DISCOVERY_WINDOW_DAYS = 14

#: Interview and offer are read from the outcome column rather than the status column.
#: Status records how far the *application* got; outcome records what the employer did,
#: and conflating them would let "submitted" read as progress it is not.
INTERVIEW_OUTCOMES = ("screening", "interviewing")
OFFER_OUTCOMES = ("offer", "accepted")

PRECISION_UNAVAILABLE = (
    "Not measured. Precision needs listings a person has labelled relevant or not, and "
    "this installation holds none. The versioned benchmark in tests/fixtures reports it "
    "for a fixed, hand-labelled set instead."
)


@dataclass(slots=True)
class DiscoveryAnalytics:
    jobs_total: int = 0
    jobs_scored: int = 0
    jobs_unscored: int = 0
    jobs_by_source: dict[str, int] = field(default_factory=dict)
    new_by_day: dict[str, int] = field(default_factory=dict)
    window_days: int = DISCOVERY_WINDOW_DAYS
    import_runs_failed: int = 0


@dataclass(slots=True)
class QualityAnalytics:
    band_counts: dict[str, int] = field(default_factory=dict)
    confidence_counts: dict[str, int] = field(default_factory=dict)
    filtered_out: int = 0
    duplicate_rate: float = 0.0
    cross_source_rate: float = 0.0
    false_merge_suspects: int = 0
    freshness: dict[str, int] = field(default_factory=dict)
    stale_rate: float = 0.0
    undated_rate: float = 0.0
    max_job_age_days: int = 0
    labelled_precision: float | None = None
    labelled_precision_note: str = PRECISION_UNAVAILABLE


@dataclass(slots=True)
class OutcomeAnalytics:
    applications_by_status: dict[str, int] = field(default_factory=dict)
    applications_by_outcome: dict[str, int] = field(default_factory=dict)
    applications_by_source: dict[str, int] = field(default_factory=dict)
    prepared: int = 0
    marked_submitted: int = 0
    confirmed: int = 0
    interviews: int = 0
    offers: int = 0
    review_queue_size: int = 0
    oldest_waiting_days: float | None = None
    oldest_waiting_id: int | None = None


@dataclass(slots=True)
class JobSearchAnalytics:
    discovery: DiscoveryAnalytics
    quality: QualityAnalytics
    outcomes: OutcomeAnalytics

    def as_dict(self) -> dict[str, object]:
        return {
            "discovery": asdict(self.discovery),
            "quality": asdict(self.quality),
            "outcomes": asdict(self.outcomes),
        }


def _rate(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 2) if whole else 0.0


def build_analytics(
    session: Session, profile: CandidateProfile, *, suspect_limit: int = 50
) -> JobSearchAnalytics:
    now = utcnow()
    jobs = JobRepository(session)
    matches = MatchRepository(session)
    applications = ApplicationRepository(session)

    jobs_total = sum(jobs.status_counts().values())
    scored = matches.scored_count(profile.id)
    duplication = analyse_duplication(session, suspect_limit=suspect_limit)

    max_age = profile.max_job_age_days or 0
    freshness = jobs.freshness_counts(now - timedelta(days=max_age or 30))

    discovery = DiscoveryAnalytics(
        jobs_total=jobs_total,
        jobs_scored=scored,
        jobs_unscored=max(jobs_total - scored, 0),
        jobs_by_source=dict(
            sorted(jobs.counts_by_source().items(), key=lambda item: item[1], reverse=True)
        ),
        new_by_day=jobs.discovered_by_day(now - timedelta(days=DISCOVERY_WINDOW_DAYS)),
        import_runs_failed=ImportRunRepository(session).failure_count(),
    )

    dated = freshness["current"] + freshness["stale"]
    quality = QualityAnalytics(
        band_counts=matches.band_counts(profile.id),
        confidence_counts=matches.confidence_counts(profile.id),
        filtered_out=matches.filtered_out_count(profile.id),
        duplicate_rate=duplication.duplicate_rate,
        cross_source_rate=duplication.cross_source_duplicate_rate,
        false_merge_suspects=len(duplication.false_merge_suspects),
        freshness=freshness,
        stale_rate=_rate(freshness["stale"], dated),
        undated_rate=_rate(freshness["undated"], jobs_total),
        max_job_age_days=max_age or 30,
    )

    status_counts = applications.status_counts()
    outcome_counts = applications.outcome_counts()
    waiting = applications.oldest_waiting()
    oldest_days: float | None = None
    if waiting is not None:
        reference = waiting.prepared_at or waiting.created_at
        oldest_days = round((now - reference).total_seconds() / 86400.0, 1)

    outcomes = OutcomeAnalytics(
        applications_by_status=status_counts,
        applications_by_outcome=outcome_counts,
        applications_by_source=dict(
            sorted(applications.counts_by_source().items(), key=lambda item: item[1], reverse=True)
        ),
        prepared=sum(status_counts.values()),
        marked_submitted=status_counts.get("SUBMITTED", 0) + status_counts.get("CONFIRMED", 0),
        confirmed=status_counts.get("CONFIRMED", 0),
        interviews=sum(outcome_counts.get(key, 0) for key in INTERVIEW_OUTCOMES),
        offers=sum(outcome_counts.get(key, 0) for key in OFFER_OUTCOMES),
        review_queue_size=status_counts.get("READY_FOR_REVIEW", 0)
        + status_counts.get("APPROVED", 0),
        oldest_waiting_days=oldest_days,
        oldest_waiting_id=waiting.id if waiting is not None else None,
    )

    return JobSearchAnalytics(discovery=discovery, quality=quality, outcomes=outcomes)
