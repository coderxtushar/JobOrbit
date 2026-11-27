"""Archiving listings older than the person's age limit."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Application, ApplicationStatus, CandidateProfile, JobStatus, SourceName
from app.db.repositories import JobRepository
from app.db.repositories.jobs import JobQuery
from app.services.archive import archive_stale_jobs
from tests.conftest import persist_job, utc_days_ago


def _job(session: Session, key: str, days_ago: float | None, **overrides):
    return persist_job(
        session,
        external_id=f"ARCH-{key}",
        url=f"https://jobs.example.com/view/{key}",
        title=f"Backend Developer {key}",
        posted_at=utc_days_ago(days_ago) if days_ago is not None else None,
        **overrides,
    )


def test_only_dated_listings_past_the_limit_are_archived(
    session: Session, profile: CandidateProfile
) -> None:
    fresh = _job(session, "fresh", 5)
    stale = _job(session, "stale", 90)
    undated = _job(session, "undated", None)

    assert archive_stale_jobs(session) == 1

    assert stale.status is JobStatus.EXPIRED
    assert fresh.status is not JobStatus.EXPIRED
    assert undated.status is not JobStatus.EXPIRED


def test_shortlisted_and_applied_listings_are_never_archived(
    session: Session, profile: CandidateProfile
) -> None:
    kept = _job(session, "kept", 90)
    kept.status = JobStatus.SHORTLISTED
    applied = _job(session, "applied", 90)
    session.add(
        Application(
            job_id=applied.id,
            profile_id=profile.id,
            platform=SourceName.MANUAL,
            status=ApplicationStatus.READY_FOR_REVIEW,
        )
    )
    session.flush()

    assert archive_stale_jobs(session) == 0
    assert kept.status is JobStatus.SHORTLISTED
    assert applied.status is not JobStatus.EXPIRED


def test_archived_listings_leave_the_list_but_stay_reachable(
    session: Session, profile: CandidateProfile
) -> None:
    _job(session, "fresh", 5)
    _job(session, "stale", 90)
    archive_stale_jobs(session)
    repository = JobRepository(session)

    default_titles = {job.title for job in repository.list(JobQuery(limit=50))}
    expired_titles = {
        job.title for job in repository.list(JobQuery(statuses=[JobStatus.EXPIRED], limit=50))
    }
    everything = {job.title for job in repository.list(JobQuery(include_expired=True, limit=50))}

    assert default_titles == {"Backend Developer fresh"}
    assert expired_titles == {"Backend Developer stale"}
    assert everything == {"Backend Developer fresh", "Backend Developer stale"}


def test_the_jobs_api_hides_archived_listings_unless_asked(
    client: TestClient, session: Session, profile: CandidateProfile
) -> None:
    _job(session, "fresh", 5)
    _job(session, "stale", 90)
    archive_stale_jobs(session)
    session.commit()

    default = client.get("/api/jobs", params={"limit": 50}).json()
    shown = client.get("/api/jobs", params={"limit": 50, "include_expired": True}).json()
    only_expired = client.get("/api/jobs", params={"limit": 50, "status": "EXPIRED"}).json()

    assert default["total"] == 1
    assert shown["total"] == 2
    assert [job["title"] for job in only_expired["items"]] == ["Backend Developer stale"]
