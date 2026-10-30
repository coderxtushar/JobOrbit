"""Bulk preparation tests.

These cover the properties a hundred-job run depends on: it reaches every job, it never
creates a second application for the same posting, one bad job does not kill the run, a
killed process leaves a resumable run, a cancellation stops it, and a dry run writes
nothing.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.base import session_scope
from app.db.models import (
    Application,
    ApplicationStatus,
    BatchItemStatus,
    BatchRun,
    BatchRunItem,
    BatchStatus,
    CandidateProfile,
    Job,
    JobMatch,
    JobStatus,
)
from app.db.repositories import BatchRunRepository, ProfileRepository
from app.services.batch import (
    BatchOptions,
    BatchPreparationService,
    BatchSelection,
    select_job_ids,
)
from tests.conftest import make_record, persist_job, utc_days_ago

BATCH_SIZE = 120


@pytest.fixture
def engine(_isolated_settings, tmp_path):
    """A file-backed engine, overriding the shared in-memory one from conftest.

    Batch concurrency needs a real connection per worker thread. The ``StaticPool``
    in-memory engine used by every other test module hands all sessions the *same* SQLite
    connection, so two workers interleave statements on one transaction and the commit
    fails with "cannot commit transaction - SQL statements in progress". A file database
    gives each thread its own connection, which is what the application does in practice.
    """
    from sqlalchemy import create_engine, event

    from app.db import base as db_base
    from app.db.models import Base

    path = tmp_path / "batch-tests.db"
    engine = create_engine(f"sqlite+pysqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    Base.metadata.create_all(engine)
    db_base.configure(engine)
    yield engine
    engine.dispose()


def _seed_jobs(session: Session, profile: CandidateProfile, count: int) -> list[Job]:
    jobs: list[Job] = []
    for index in range(count):
        job = persist_job(
            session,
            record=make_record(
                external_id=f"GH-{index}",
                title="Backend Developer" if index % 2 else "Python Developer",
                company=f"Company {index:03d}",
                url=f"https://boards.example.com/jobs/{index}",
                posted_at=utc_days_ago(index % 20),
            ),
        )
        session.add(
            JobMatch(
                job_id=job.id,
                profile_id=profile.id,
                total_score=95.0 - (index % 40),
                band="high" if index % 40 < 15 else "review",
                filtered_out=False,
            )
        )
        job.status = JobStatus.SCORED
        jobs.append(job)
    session.flush()
    session.commit()
    return jobs


def test_a_run_of_over_one_hundred_jobs_prepares_every_one(
    session: Session, profile: CandidateProfile, engine
) -> None:
    _seed_jobs(session, profile, BATCH_SIZE)
    service = BatchPreparationService()

    run = service.create_run(
        session,
        profile,
        BatchSelection(limit=500),
        BatchOptions(concurrency=4, max_attempts=2),
    )
    session.commit()
    assert run.total_items == BATCH_SIZE

    summary = service.execute(run.id)

    assert summary["status"] == BatchStatus.COMPLETED.value
    counts = summary["counts"]
    assert isinstance(counts, dict)
    assert counts.get(BatchItemStatus.FAILED.value, 0) == 0
    terminal = sum(counts.values())
    assert terminal == BATCH_SIZE

    with session_scope() as fresh:
        applications = fresh.query(Application).count()
        assert applications == BATCH_SIZE
        statuses = {status for (status,) in fresh.query(Application.status).distinct().all()}
        assert statuses == {ApplicationStatus.READY_FOR_REVIEW}
        items = fresh.query(BatchRunItem).filter(BatchRunItem.batch_run_id == run.id).all()
        assert all(item.finished_at is not None for item in items)
        assert all(item.application_id is not None for item in items)


def test_running_the_same_batch_twice_creates_no_duplicate_applications(
    session: Session, profile: CandidateProfile, engine
) -> None:
    _seed_jobs(session, profile, 12)
    service = BatchPreparationService()

    first = service.create_run(session, profile, BatchSelection(limit=100), BatchOptions())
    session.commit()
    service.execute(first.id)

    with session_scope() as fresh:
        after_first = fresh.query(Application).count()
    assert after_first == 12

    with session_scope() as fresh:
        reloaded = ProfileRepository(fresh).get_or_create_default()
        second = service.create_run(fresh, reloaded, BatchSelection(limit=100), BatchOptions())
        second_id = second.id
    service.execute(second_id)

    with session_scope() as fresh:
        assert fresh.query(Application).count() == after_first


def test_a_selection_excludes_jobs_already_submitted(
    session: Session, profile: CandidateProfile, engine
) -> None:
    jobs = _seed_jobs(session, profile, 5)
    session.add(
        Application(
            job_id=jobs[0].id,
            profile_id=profile.id,
            platform=make_record().source,
            status=ApplicationStatus.SUBMITTED,
        )
    )
    session.add(
        Application(
            job_id=jobs[1].id,
            profile_id=profile.id,
            platform=make_record().source,
            status=ApplicationStatus.READY_FOR_REVIEW,
        )
    )
    session.flush()

    selected = select_job_ids(session, profile, BatchSelection(limit=100))
    assert jobs[0].id not in selected
    assert jobs[1].id in selected


def test_selection_honours_score_band_and_age(session: Session, profile: CandidateProfile) -> None:
    _seed_jobs(session, profile, 40)
    high_only = select_job_ids(session, profile, BatchSelection(bands=["high"], limit=100))
    assert high_only
    for job_id in high_only:
        match = (
            session.query(JobMatch)
            .filter(JobMatch.job_id == job_id, JobMatch.profile_id == profile.id)
            .one()
        )
        assert match.band == "high"

    scored = select_job_ids(session, profile, BatchSelection(min_score=90.0, limit=100))
    for job_id in scored:
        match = (
            session.query(JobMatch)
            .filter(JobMatch.job_id == job_id, JobMatch.profile_id == profile.id)
            .one()
        )
        assert match.total_score >= 90.0

    recent = select_job_ids(session, profile, BatchSelection(max_age_days=5, limit=100))
    assert len(recent) < 40


def test_an_unscored_job_is_excluded_unless_asked_for(
    session: Session, profile: CandidateProfile
) -> None:
    persist_job(session, record=make_record(external_id="NOSCORE", company="Unscored Ltd"))
    session.commit()
    assert select_job_ids(session, profile, BatchSelection(limit=50)) == []
    assert len(select_job_ids(session, profile, BatchSelection(include_unscored=True))) == 1


def test_a_dry_run_writes_no_application(
    session: Session, profile: CandidateProfile, engine
) -> None:
    _seed_jobs(session, profile, 6)
    service = BatchPreparationService()
    run = service.create_run(session, profile, BatchSelection(limit=50), BatchOptions(dry_run=True))
    session.commit()
    summary = service.execute(run.id)

    assert summary["status"] == BatchStatus.COMPLETED.value
    assert "dry run" in str(summary["message"])
    with session_scope() as fresh:
        assert fresh.query(Application).count() == 0
        items = fresh.query(BatchRunItem).filter(BatchRunItem.batch_run_id == run.id).all()
        assert len(items) == 6
        assert all(item.status is BatchItemStatus.PREPARED for item in items)
        assert all(item.application_id is None for item in items)


@pytest.mark.parametrize(
    ("stored_url", "expected_reason"),
    [
        ("", "no application URL"),
        ("https://10.0.0.5/job", "unsafe"),
    ],
)
def test_a_job_with_no_usable_destination_is_skipped_with_a_reason_not_prepared(
    session: Session,
    profile: CandidateProfile,
    engine,
    stored_url: str,
    expected_reason: str,
) -> None:
    """Both failure modes are reported, and neither produces an application.

    Normalization already strips an unsafe URL on import, so the first case is what a
    real import produces. The second writes the unsafe value straight onto the row to
    exercise the batch runner's own guard rather than the importer's.
    """
    job = persist_job(
        session,
        record=make_record(external_id="BAD-1", company="Sketchy Inc", url="https://10.0.0.5/job"),
    )
    job.url = stored_url
    job.canonical_url = stored_url
    session.add(JobMatch(job_id=job.id, profile_id=profile.id, total_score=90.0, band="high"))
    session.commit()

    service = BatchPreparationService()
    run = service.create_run(session, profile, BatchSelection(limit=10), BatchOptions())
    session.commit()
    service.execute(run.id)

    with session_scope() as fresh:
        item = fresh.query(BatchRunItem).filter(BatchRunItem.batch_run_id == run.id).one()
        assert item.status is BatchItemStatus.SKIPPED_INELIGIBLE
        assert expected_reason in item.detail
        assert fresh.query(Application).count() == 0


def test_one_failing_job_does_not_stop_the_run_and_retries_are_bounded(
    session: Session, profile: CandidateProfile, engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs = _seed_jobs(session, profile, 5)
    doomed = jobs[2].id
    attempts: list[int] = []

    original = BatchPreparationService._prepare_one

    def _sometimes_broken(self, *, job_id: int, **kwargs):
        if job_id == doomed:
            attempts.append(job_id)
            raise TimeoutError("the letter generator timed out")
        return original(self, job_id=job_id, **kwargs)

    monkeypatch.setattr(BatchPreparationService, "_prepare_one", _sometimes_broken)

    service = BatchPreparationService()
    run = service.create_run(
        session, profile, BatchSelection(limit=50), BatchOptions(max_attempts=3, concurrency=2)
    )
    session.commit()
    summary = service.execute(run.id)

    assert summary["status"] == BatchStatus.COMPLETED_WITH_ERRORS.value
    assert len(attempts) == 3
    with session_scope() as fresh:
        items = fresh.query(BatchRunItem).filter(BatchRunItem.batch_run_id == run.id).all()
        failed = [item for item in items if item.status is BatchItemStatus.FAILED]
        assert len(failed) == 1
        assert failed[0].job_id == doomed
        assert failed[0].attempts == 3
        assert "3 attempt(s)" in failed[0].detail
        succeeded = [
            item
            for item in items
            if item.status in {BatchItemStatus.PREPARED, BatchItemStatus.NEEDS_ACTION}
        ]
        assert len(succeeded) == 4
        assert fresh.query(Application).count() == 4


def test_an_interrupted_run_is_reconciled_and_resumes_only_what_is_left(
    session: Session, profile: CandidateProfile, engine
) -> None:
    _seed_jobs(session, profile, 8)
    service = BatchPreparationService()
    run = service.create_run(session, profile, BatchSelection(limit=50), BatchOptions())
    session.commit()
    run_id = run.id

    # Simulate a process killed mid-run: three items terminal, one in flight, the rest queued.
    with session_scope() as fresh:
        items = fresh.query(BatchRunItem).filter(BatchRunItem.batch_run_id == run_id).all()
        for item in items[:3]:
            item.status = BatchItemStatus.PREPARED
        items[3].status = BatchItemStatus.IN_PROGRESS
        fresh.get(BatchRun, run_id).status = BatchStatus.RUNNING

    with session_scope() as fresh:
        assert BatchRunRepository(fresh).mark_interrupted() == 1

    with session_scope() as fresh:
        reloaded = fresh.get(BatchRun, run_id)
        assert reloaded is not None
        assert reloaded.status is BatchStatus.INTERRUPTED
        assert "resumed" in reloaded.message
        pending = BatchRunRepository(fresh).pending_items(run_id)
        assert len(pending) == 5

    service.execute(run_id)

    with session_scope() as fresh:
        assert fresh.query(Application).count() == 5
        statuses = [
            item.status
            for item in fresh.query(BatchRunItem).filter(BatchRunItem.batch_run_id == run_id).all()
        ]
        assert BatchItemStatus.QUEUED not in statuses
        assert BatchItemStatus.IN_PROGRESS not in statuses
        assert fresh.get(BatchRun, run_id).status is BatchStatus.COMPLETED


def test_a_cancelled_run_stops_and_records_what_it_skipped(
    session: Session, profile: CandidateProfile, engine
) -> None:
    _seed_jobs(session, profile, 10)
    service = BatchPreparationService()
    run = service.create_run(
        session, profile, BatchSelection(limit=50), BatchOptions(concurrency=1)
    )
    session.commit()
    run_id = run.id

    with session_scope() as fresh:
        target = fresh.get(BatchRun, run_id)
        assert target is not None
        BatchRunRepository(fresh).request_cancel(target)

    summary = service.execute(run_id)

    assert summary["status"] == BatchStatus.CANCELLED.value
    with session_scope() as fresh:
        items = fresh.query(BatchRunItem).filter(BatchRunItem.batch_run_id == run_id).all()
        assert all(item.status is BatchItemStatus.CANCELLED for item in items)
        assert fresh.query(Application).count() == 0


def test_an_empty_selection_finishes_immediately_rather_than_hanging(
    client: TestClient, engine
) -> None:
    response = client.post(
        "/api/batches",
        json={"selection": {"limit": 50}, "run_in_background": False},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["total_items"] == 0
    assert body["status"] == BatchStatus.COMPLETED.value
    assert "nothing to prepare" in body["message"]


def test_the_batch_endpoints_drive_a_whole_run(client: TestClient, engine) -> None:
    with session_scope() as session:
        created = ProfileRepository(session).get_or_create_default()
        ProfileRepository(session).update(
            created,
            {
                "full_name": "Test Candidate",
                "technical_skills": ["python", "fastapi"],
                "target_titles": ["Backend Developer"],
            },
        )
        _seed_jobs(session, created, 15)

    preview = client.post("/api/batches/preview", json={"selection": {"limit": 100}})
    assert preview.status_code == 200
    assert preview.json()["total"] == 15

    started = client.post(
        "/api/batches",
        json={"selection": {"limit": 100}, "concurrency": 3, "run_in_background": False},
    )
    assert started.status_code == 201, started.text
    run = started.json()
    assert run["total_items"] == 15

    detail = client.get(f"/api/batches/{run['id']}").json()
    assert detail["status"] in {
        BatchStatus.COMPLETED.value,
        BatchStatus.COMPLETED_WITH_ERRORS.value,
    }
    assert len(detail["items"]) == 15
    assert detail["items"][0]["job_title"]
    assert sum(detail["status_counts"].values()) == 15

    listed = client.get("/api/batches").json()
    assert listed["total"] == 1

    assert client.get("/api/batches/9999").status_code == 404
    assert client.post("/api/batches/9999/cancel").status_code == 404
    finished = client.post(f"/api/batches/{run['id']}/cancel")
    assert finished.status_code == 409
    nothing_left = client.post(f"/api/batches/{run['id']}/resume")
    assert nothing_left.status_code == 409


def test_no_batch_endpoint_submits_an_application(client: TestClient) -> None:
    """The bulk path must not acquire a capability the single-job path refuses."""
    paths = client.get("/openapi.json").json()["paths"]
    batch_paths = {path for path in paths if path.startswith("/api/batches")}
    assert batch_paths
    for path in batch_paths:
        for method, spec in paths[path].items():
            blob = f"{path} {method} {spec.get('summary', '')} {spec.get('description', '')}"
            assert "submit" not in blob.lower() or "not" in blob.lower()
    assert not any("submit" in path.lower() for path in paths)


def test_a_cancelled_run_can_be_resumed_and_finishes_the_rest(
    session: Session, profile: CandidateProfile, engine
) -> None:
    """A cancelled item was never attempted, so resuming must pick it up again.

    Classing CANCELLED as terminal made Resume impossible on precisely the runs that
    needed it, which is what this asserts against.
    """
    _seed_jobs(session, profile, 6)
    service = BatchPreparationService()
    run = service.create_run(
        session, profile, BatchSelection(limit=50), BatchOptions(concurrency=1)
    )
    session.commit()
    run_id = run.id

    with session_scope() as fresh:
        target = fresh.get(BatchRun, run_id)
        assert target is not None
        BatchRunRepository(fresh).request_cancel(target)
    service.execute(run_id)

    with session_scope() as fresh:
        assert fresh.get(BatchRun, run_id).status is BatchStatus.CANCELLED
        assert fresh.query(Application).count() == 0
        pending = BatchRunRepository(fresh).pending_items(run_id)
        assert len(pending) == 6
        BatchRunRepository(fresh).clear_cancel(fresh.get(BatchRun, run_id))

    summary = service.execute(run_id)

    assert summary["status"] == BatchStatus.COMPLETED.value
    with session_scope() as fresh:
        assert fresh.query(Application).count() == 6
        assert not BatchRunRepository(fresh).pending_items(run_id)


def test_resuming_a_cancelled_run_through_the_api(client: TestClient, engine) -> None:
    with session_scope() as session:
        created = ProfileRepository(session).get_or_create_default()
        ProfileRepository(session).update(created, {"full_name": "Test Candidate"})
        _seed_jobs(session, created, 4)

    started = client.post(
        "/api/batches",
        json={"selection": {"limit": 50}, "concurrency": 1, "run_in_background": False},
    ).json()
    run_id = started["id"]

    with session_scope() as session:
        run = session.get(BatchRun, run_id)
        assert run is not None
        run.status = BatchStatus.CANCELLED
        run.cancel_requested = True
        for item in session.query(BatchRunItem).filter(BatchRunItem.batch_run_id == run_id):
            item.status = BatchItemStatus.CANCELLED

    resumed = client.post(f"/api/batches/{run_id}/resume?run_in_background=false")
    assert resumed.status_code == 200, resumed.text
    body = resumed.json()
    assert body["cancel_requested"] is False
    assert body["status"] in {
        BatchStatus.COMPLETED.value,
        BatchStatus.COMPLETED_WITH_ERRORS.value,
    }
