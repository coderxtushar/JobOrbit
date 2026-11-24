"""Job-search analytics.

The thing worth testing here is not arithmetic but restraint: an empty search must report
zeros, an unlabelled installation must say precision is unmeasured rather than guess it,
and an outcome must only ever reflect what the user recorded.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.db.models import CandidateProfile, Outcome, utcnow
from app.db.repositories import ApplicationRepository, JobRepository, MatchRepository
from app.services.analytics import (
    INTERVIEW_OUTCOMES,
    OFFER_OUTCOMES,
    PRECISION_UNAVAILABLE,
    build_analytics,
)
from app.services.scoring import ScoringService
from tests.conftest import persist_job, utc_days_ago


def test_an_empty_installation_reports_zeros_not_blanks(
    session: Session, profile: CandidateProfile
) -> None:
    report = build_analytics(session, profile)

    assert report.discovery.jobs_total == 0
    assert report.discovery.jobs_scored == 0
    assert report.outcomes.prepared == 0
    assert report.outcomes.interviews == 0
    assert report.outcomes.offers == 0
    assert report.outcomes.oldest_waiting_days is None


def test_precision_is_reported_as_unmeasured_rather_than_invented(
    session: Session, profile: CandidateProfile
) -> None:
    report = build_analytics(session, profile)

    assert report.quality.labelled_precision is None
    assert report.quality.labelled_precision_note == PRECISION_UNAVAILABLE
    assert "labelled" in report.quality.labelled_precision_note


def test_unscored_jobs_are_counted_so_the_user_knows_work_remains(
    session: Session, profile: CandidateProfile
) -> None:
    first = persist_job(session, external_id="AN-1", title="Backend Developer One")
    persist_job(session, external_id="AN-2", title="Python Developer Two")
    ScoringService(session).score_one(first, profile)
    session.flush()

    report = build_analytics(session, profile)

    assert report.discovery.jobs_total == 2
    assert report.discovery.jobs_scored == 1
    assert report.discovery.jobs_unscored == 1


def test_discovery_is_grouped_by_the_day_the_app_saw_the_job(
    session: Session, profile: CandidateProfile
) -> None:
    """Grouping on posted_at would answer a different question and is explicitly not done."""
    job = persist_job(session, external_id="AN-3", title="Backend Developer Three")
    job.discovered_at = utc_days_ago(2)
    job.posted_at = utc_days_ago(200)
    session.flush()

    report = build_analytics(session, profile)

    assert sum(report.discovery.new_by_day.values()) == 1
    expected_day = (utcnow() - timedelta(days=2)).date().isoformat()
    assert expected_day in report.discovery.new_by_day


def test_a_job_discovered_outside_the_window_is_not_counted_in_the_series(
    session: Session, profile: CandidateProfile
) -> None:
    job = persist_job(session, external_id="AN-4", title="Backend Developer Four")
    job.discovered_at = utc_days_ago(90)
    session.flush()

    report = build_analytics(session, profile)

    assert report.discovery.new_by_day == {}
    assert report.discovery.jobs_total == 1


def test_undated_listings_are_their_own_bucket_not_assumed_stale(
    session: Session, profile: CandidateProfile
) -> None:
    persist_job(session, external_id="AN-5", title="Backend Developer Five", posted_at=None)
    persist_job(
        session, external_id="AN-6", title="Backend Developer Six", posted_at=utc_days_ago(1)
    )
    persist_job(
        session, external_id="AN-7", title="Backend Developer Seven", posted_at=utc_days_ago(400)
    )
    session.flush()

    report = build_analytics(session, profile)
    freshness = report.quality.freshness

    assert freshness["undated"] == 1
    assert freshness["current"] == 1
    assert freshness["stale"] == 1
    assert report.quality.stale_rate == 50.0, "the stale rate covers only dated listings"
    assert round(report.quality.undated_rate) == 33


def test_the_stale_rate_never_divides_by_the_undated_listings(
    session: Session, profile: CandidateProfile
) -> None:
    for index in range(3):
        persist_job(
            session,
            external_id=f"AN-U{index}",
            title=f"Platform Engineer {['Alpha', 'Beta', 'Gamma'][index]}",
            posted_at=None,
        )
    session.flush()

    report = build_analytics(session, profile)

    assert report.quality.stale_rate == 0.0
    assert report.quality.undated_rate == 100.0


def test_confidence_distribution_comes_from_the_stored_scores(
    session: Session, profile: CandidateProfile
) -> None:
    job = persist_job(session, external_id="AN-8", title="Backend Developer Eight")
    row = ScoringService(session).score_one(job, profile)
    session.flush()

    report = build_analytics(session, profile)

    assert report.quality.confidence_counts.get(row.confidence) == 1
    assert sum(report.quality.confidence_counts.values()) == MatchRepository(session).scored_count(
        profile.id
    )


def test_top_sources_are_ordered_by_contribution(
    session: Session, profile: CandidateProfile
) -> None:
    persist_job(session, external_id="AN-9", title="Backend Developer Nine")
    session.flush()

    report = build_analytics(session, profile)
    counts = list(report.discovery.jobs_by_source.values())

    assert counts == sorted(counts, reverse=True)
    assert report.discovery.jobs_by_source == JobRepository(session).counts_by_source()


def test_an_application_counts_as_submitted_only_when_the_user_recorded_it(
    client, session: Session
) -> None:
    job = persist_job(
        session,
        external_id="AN-10",
        title="Backend Developer Ten",
        url="https://jobs.example.com/an10",
    )
    session.commit()
    prepared = client.post("/api/applications/prepare", json={"job_id": job.id})
    assert prepared.status_code == 201

    client.post(f"/api/applications/{prepared.json()['id']}/record-opened")

    report = client.get("/api/metrics/analytics").json()

    assert report["outcomes"]["prepared"] == 1
    assert report["outcomes"]["marked_submitted"] == 0, (
        "opening the employer's page must never count as a submission"
    )
    assert report["outcomes"]["confirmed"] == 0


def test_interview_and_offer_counts_read_the_outcome_field_not_the_status(
    session: Session, profile: CandidateProfile
) -> None:
    from app.db.models import Application

    job = persist_job(session, external_id="AN-13", title="Backend Developer Thirteen")
    application = Application(
        job_id=job.id,
        profile_id=profile.id,
        platform="manual_json",
        outcome=Outcome.INTERVIEWING,
    )
    session.add(application)
    session.flush()

    report = build_analytics(session, profile)

    assert report.outcomes.interviews == 1
    assert report.outcomes.offers == 0
    assert "interviewing" in INTERVIEW_OUTCOMES
    assert "offer" in OFFER_OUTCOMES


def test_every_interview_and_offer_marker_is_a_real_outcome_value() -> None:
    """A marker that matches no enum value would silently always count zero."""
    values = {outcome.value for outcome in Outcome}

    assert set(INTERVIEW_OUTCOMES) <= values
    assert set(OFFER_OUTCOMES) <= values


def test_the_oldest_waiting_application_is_named_as_the_bottleneck(
    client, session: Session
) -> None:
    job = persist_job(
        session,
        external_id="AN-11",
        title="Backend Developer Eleven",
        url="https://jobs.example.com/an11",
    )
    session.commit()
    prepared = client.post("/api/applications/prepare", json={"job_id": job.id}).json()

    application = ApplicationRepository(session).get(prepared["id"])
    assert application is not None
    application.prepared_at = utc_days_ago(9)
    session.commit()

    report = client.get("/api/metrics/analytics").json()

    assert report["outcomes"]["review_queue_size"] == 1
    assert report["outcomes"]["oldest_waiting_id"] == prepared["id"]
    assert report["outcomes"]["oldest_waiting_days"] is not None
    assert report["outcomes"]["oldest_waiting_days"] >= 8


def test_the_analytics_endpoint_keeps_the_three_groups_separate(client, session: Session) -> None:
    persist_job(session, external_id="AN-12", title="Backend Developer Twelve")
    session.commit()

    response = client.get("/api/metrics/analytics")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"discovery", "quality", "outcomes", "demo_mode"}
    assert "duplicate_rate" in body["quality"]
    assert "jobs_by_source" in body["discovery"]
    assert "applications_by_outcome" in body["outcomes"]


def test_the_analytics_endpoint_is_read_only(client) -> None:
    """Analytics must never be a write path, so it stays available in the public demo."""
    from app.api.deps import DEMO_BLOCKED_REASONS, DEMO_SESSION_SCOPED

    assert "analytics" not in DEMO_BLOCKED_REASONS
    assert "analytics" not in DEMO_SESSION_SCOPED

    import inspect

    from app.api.routes import sources

    source = inspect.getsource(sources.analytics)
    assert "refuse_in_demo_mode" not in source
    assert "session.add" not in source
