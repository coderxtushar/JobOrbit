# ruff: noqa: F811 - pytest fixtures imported from the engine tests are requested by name
"""Preflight, submission reliability and the evidence trail.

Runs against the loopback application server in :mod:`tests.support.application_server`
(the same one the submission engine tests use), so a "submission" here is a real HTTP
request to a server this project runs, never to an employer.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db.models import (
    Application,
    ApplicationArtifact,
    ApplicationStatus,
    AutoApplyRun,
    BatchStatus,
    CandidateProfile,
    Job,
    JobLock,
    JobStatus,
    LockedArtifactError,
    SourceName,
    SubmissionAttempt,
    SubmissionEvent,
    SubmissionState,
    WorkArrangement,
    utcnow,
)
from app.services import autoapply_control as control
from app.services.autoapply import AutoApplyService, AutoApplyTargets, preview
from app.services.autoapply_resolution import ResolutionError, resolve
from app.services.preflight import run_preflight
from app.services.redaction import mask_value, redact
from app.submission.local_test import LocalTestSubmissionAdapter
from tests.conftest import persist_job
from tests.support.application_server import TestApplicationServer
from tests.test_demo_mode import demo_client  # noqa: F401 - fixture
from tests.test_submission_engine import (  # noqa: F401 - fixtures are used by name
    _job,
    _score,
    ats_server,
    configured,
    verified_profile,
)


def _run(session: Session, profile: CandidateProfile, targets: AutoApplyTargets) -> AutoApplyRun:
    service = AutoApplyService()
    run = service.create_run(session, profile, targets)
    session.commit()
    finished = service.execute(run.id, targets)
    session.expire_all()
    return finished


def _attempt(session: Session, job: Job) -> SubmissionAttempt:
    return (
        session.query(SubmissionAttempt)
        .filter(SubmissionAttempt.job_id == job.id)
        .order_by(SubmissionAttempt.id.desc())
        .first()
    )


LIVE = {"dry_run": False, "min_score": 50, "max_submissions": 10}


# --------------------------------------------------------------------------------------
# Preflight
# --------------------------------------------------------------------------------------


def test_preflight_itemises_every_job_and_counts_each_gate(
    configured: TestApplicationServer, session: Session, verified_profile, profile
) -> None:
    verified_profile.years_experience = 1.0
    ready = _job(session, configured, "PF-READY", external_id="PF-READY")
    _score(session, ready, profile)
    low = _job(session, configured, "PF-LOW", external_id="PF-LOW")
    _score(session, low, profile, score=30)
    senior = _job(session, configured, "PF-SENIOR", external_id="PF-SENIOR")
    senior.experience_min_years = 8
    _score(session, senior, profile, score=99)
    old = _job(session, configured, "PF-OLD", external_id="PF-OLD")
    old.posted_at = utcnow() - timedelta(days=10)
    _score(session, old, profile)
    applied = _job(session, configured, "PF-DONE", external_id="PF-DONE")
    _score(session, applied, profile)
    session.add(
        Application(
            job_id=applied.id,
            profile_id=profile.id,
            platform=SourceName.GREENHOUSE,
            status=ApplicationStatus.CONFIRMED,
        )
    )
    duplicate = _job(session, configured, "PF-DUP", external_id="PF-DUP")
    duplicate.status = JobStatus.DUPLICATE
    duplicate.duplicate_of_id = ready.id
    linkedin = persist_job(
        session,
        source=SourceName.LINKEDIN,
        external_id="PF-LI",
        title="Backend Developer",
        company="Elsewhere",
    )
    linkedin.url = "https://www.linkedin.com/jobs/view/123"
    _score(session, linkedin, profile)
    session.commit()

    plan = run_preflight(session, profile, AutoApplyTargets(**LIVE))
    by_id = {item.job_id: item for item in plan.jobs}

    assert by_id[ready.id].status == "ready" and by_id[ready.id].planned
    assert by_id[low.id].status == "below_threshold"
    assert by_id[senior.id].status == "blocked", "a hard constraint must beat a 99 score"
    assert "8 years" in " ".join(by_id[senior.id].blocking_reasons)
    assert by_id[old.id].status == "stale"
    assert by_id[applied.id].status == "applied"
    assert by_id[duplicate.id].status == "duplicate"
    assert by_id[linkedin.id].status == "unsupported" and not by_id[linkedin.id].planned
    assert plan.queue_job_ids[0] == ready.id
    assert ready.id in plan.queue_job_ids and linkedin.id in plan.queue_job_ids
    assert senior.id not in plan.queue_job_ids

    counts = plan.counts
    assert counts.total_discovered == 7
    assert counts.duplicates == 1 and counts.previously_applied == 1
    assert counts.expired_or_stale == 1 and counts.unsupported_platform == 1
    assert counts.ready == 1 and counts.planned_attempts == 1
    # Every queued job can be inspected: answers and the resume that would be sent.
    item = by_id[ready.id]
    assert item.resume_artifact and item.screening_answers
    sensitive = [answer for answer in item.screening_answers if answer.sensitive and answer.answer]
    assert sensitive and all("masked" in answer.answer for answer in sensitive)


def test_location_remote_family_platform_and_employer_constraints_are_hard(
    configured: TestApplicationServer, session: Session, verified_profile, profile
) -> None:
    onsite = _job(session, configured, "HC-1", external_id="HC-1", company="Onsite Co")
    onsite.work_arrangement = WorkArrangement.ONSITE
    onsite.location_normalized = "pune, india"
    onsite.location = "Pune, India"
    _score(session, onsite, profile, score=99)
    session.commit()

    def status(**overrides) -> str:
        targets = AutoApplyTargets(**{**LIVE, **overrides})
        return next(
            j for j in run_preflight(session, profile, targets).jobs if j.job_id == onsite.id
        ).status

    assert status() == "ready"
    assert status(remote_preference="remote_only") == "blocked"
    assert status(locations=["Bengaluru"]) == "blocked"
    assert status(locations=["Pune"]) == "ready"
    assert status(role_families=["data"]) == "blocked"
    assert status(platforms=["lever"]) == "blocked"
    assert status(excluded_companies=["onsite co"]) == "blocked"


def test_missing_answers_are_reported_before_the_run(
    configured: TestApplicationServer, session: Session, profile
) -> None:
    job = _job(session, configured, "PF-ANS", external_id="PF-ANS")
    _score(session, job, profile)
    session.commit()

    plan = run_preflight(session, profile, AutoApplyTargets(**LIVE))
    item = next(j for j in plan.jobs if j.job_id == job.id)
    assert item.status == "needs_answers"
    assert item.unresolved_questions
    assert plan.counts.missing_answers == 1 and plan.counts.planned_attempts == 0


def test_a_run_covers_only_the_jobs_the_user_approved(
    configured: TestApplicationServer, session: Session, verified_profile, profile
) -> None:
    first = _job(session, configured, "AP-1", external_id="AP-1")
    second = _job(session, configured, "AP-2", external_id="AP-2")
    _score(session, first, profile)
    _score(session, second, profile)
    session.commit()

    run = _run(session, profile, AutoApplyTargets(**LIVE, approved_job_ids=[second.id]))

    assert {attempt.job_id for attempt in run.attempts} == {second.id}
    assert len(configured.state.confirmed()) == 1
    assert run.preflight["queue_job_ids"] == [second.id]


def test_the_preview_count_and_the_run_queue_come_from_the_same_plan(
    configured: TestApplicationServer, session: Session, verified_profile, profile
) -> None:
    for index in range(3):
        _score(
            session,
            _job(session, configured, f"SAME-{index}", external_id=f"SAME-{index}"),
            profile,
        )
    session.commit()
    targets = AutoApplyTargets(**{**LIVE, "dry_run": True})
    counted = preview(session, profile, targets)
    run = _run(session, profile, targets)
    assert counted.eligible == len(run.attempts) == 3


def test_the_daily_cap_limits_planned_attempts(
    configured: TestApplicationServer,
    session: Session,
    verified_profile,
    profile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import reset_settings_cache

    monkeypatch.setenv("JA_BROWSER_SUBMISSION_ENABLED", "true")
    monkeypatch.setenv("JA_BROWSER_DAILY_SUBMISSION_CAP", "5")
    reset_settings_cache()
    for index in range(3):
        _score(
            session, _job(session, configured, f"CAP-{index}", external_id=f"CAP-{index}"), profile
        )
    session.commit()

    plan = run_preflight(session, profile, AutoApplyTargets(**LIVE, daily_cap=2))
    assert plan.counts.daily_cap == 2
    assert plan.counts.ready == 3 and plan.counts.planned_attempts == 2


# --------------------------------------------------------------------------------------
# Locks, duplicates, emergency stop
# --------------------------------------------------------------------------------------


def test_a_job_locked_by_another_worker_is_not_submitted(
    configured: TestApplicationServer, session: Session, verified_profile, profile
) -> None:
    job = _job(session, configured, "LOCK-1", external_id="LOCK-1")
    _score(session, job, profile)
    session.add(JobLock(job_id=job.id, owner="run-999-1", expires_at=utcnow() + timedelta(hours=1)))
    session.commit()

    _run(session, profile, AutoApplyTargets(**LIVE))
    attempt = _attempt(session, job)
    assert attempt.state is SubmissionState.ELIGIBLE
    assert attempt.failure_category == "locked_elsewhere"
    assert configured.state.applications == {}


def test_an_expired_lock_is_taken_over_and_released(
    configured: TestApplicationServer, session: Session, verified_profile, profile
) -> None:
    job = _job(session, configured, "LOCK-2", external_id="LOCK-2")
    _score(session, job, profile)
    session.add(
        JobLock(job_id=job.id, owner="run-999-1", expires_at=utcnow() - timedelta(minutes=1))
    )
    session.commit()

    _run(session, profile, AutoApplyTargets(**LIVE))
    assert _attempt(session, job).state is SubmissionState.SUBMITTED_CONFIRMED
    assert session.get(JobLock, job.id) is None, "the lock must be released after the attempt"


def test_a_job_the_user_submitted_by_hand_meanwhile_is_not_sent_again(
    configured: TestApplicationServer,
    session: Session,
    verified_profile,
    profile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = _job(session, configured, "DUP-1", external_id="DUP-1")
    _score(session, job, profile)
    session.commit()

    import app.services.autoapply as module

    original = module._answers_sent

    def user_submits_meanwhile(adapter, job_arg, form):
        application = (
            module.select(Application).where(Application.job_id == job_arg.id)  # type: ignore[attr-defined]
        )
        row = session.scalars(application).first()
        row.status = ApplicationStatus.SUBMITTED
        session.commit()
        return original(adapter, job_arg, form)

    service = AutoApplyService(session_factory=None)
    run = service.create_run(session, profile, AutoApplyTargets(**LIVE))
    session.commit()
    monkeypatch.setattr(module, "_answers_sent", user_submits_meanwhile)
    service.execute(run.id, AutoApplyTargets(**LIVE))
    session.expire_all()

    attempt = _attempt(session, job)
    assert attempt.state is SubmissionState.FAILED
    assert attempt.failure_category == "duplicate_prevented"
    assert configured.state.applications == {}


def test_a_new_run_does_not_take_a_job_from_an_active_run(
    configured: TestApplicationServer, session: Session, verified_profile, profile
) -> None:
    job = _job(session, configured, "ACT-1", external_id="ACT-1")
    _score(session, job, profile)
    session.commit()
    service = AutoApplyService()
    first = service.create_run(session, profile, AutoApplyTargets(**LIVE))
    first.status = BatchStatus.PAUSED
    service._queue(session, first, [job.id])
    session.commit()

    plan = run_preflight(session, profile, AutoApplyTargets(**LIVE))
    assert job.id not in plan.queue_job_ids
    second = service.create_run(session, profile, AutoApplyTargets(**LIVE))
    service._queue(session, second, [job.id])
    session.commit()
    keys = [a.idempotency_key for a in session.query(SubmissionAttempt).all()]
    assert len(keys) == 1 and "#retired" not in keys[0], "the paused run's attempt was stolen"


def test_the_emergency_stop_refuses_runs_and_sends_nothing(
    configured: TestApplicationServer, session: Session, verified_profile, profile, client
) -> None:
    job = _job(session, configured, "STOP-1", external_id="STOP-1")
    _score(session, job, profile)
    control.engage_emergency_stop(session, "test")
    session.commit()

    run = _run(session, profile, AutoApplyTargets(**LIVE))
    assert run.status is BatchStatus.CANCELLED and run.attempts == []
    assert configured.state.applications == {}
    response = client.post("/api/autoapply/runs", json={"dry_run": False})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "emergency_stop_active"

    control.clear_emergency_stop(session)
    session.commit()
    assert _run(session, profile, AutoApplyTargets(**LIVE)).confirmed_count == 1


def test_a_stop_engaged_mid_attempt_stops_before_the_request_is_sent(
    configured: TestApplicationServer,
    session: Session,
    verified_profile,
    profile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.autoapply as module

    job = _job(session, configured, "STOP-2", external_id="STOP-2")
    _score(session, job, profile)
    session.commit()
    original = module._answers_sent

    def stop_now(adapter, job_arg, form):
        control.engage_emergency_stop(session, "pressed during the attempt")
        session.commit()
        return original(adapter, job_arg, form)

    monkeypatch.setattr(module, "_answers_sent", stop_now)
    _run(session, profile, AutoApplyTargets(**LIVE))

    attempt = _attempt(session, job)
    assert attempt.state is SubmissionState.FAILED
    assert attempt.failure_category == "emergency_stop"
    assert configured.state.applications == {}


# --------------------------------------------------------------------------------------
# Crashes, timeouts, retries
# --------------------------------------------------------------------------------------


def _stuck_attempt(session: Session, profile, job: Job, checkpoint: str) -> SubmissionAttempt:
    run = AutoApplyService().create_run(session, profile, AutoApplyTargets(**LIVE))
    run.status = BatchStatus.RUNNING
    run.heartbeat_at = utcnow() - timedelta(hours=1)
    attempt = SubmissionAttempt(
        autoapply_run_id=run.id,
        job_id=job.id,
        state=SubmissionState.SUBMISSION_IN_PROGRESS,
        idempotency_key=f"stuck-{job.id}",
        checkpoint=checkpoint,
        attempts=1,
    )
    session.add(attempt)
    session.commit()
    return attempt


def test_a_crash_after_submit_was_requested_becomes_unknown_and_is_never_resent(
    configured: TestApplicationServer, session: Session, verified_profile, profile
) -> None:
    job = _job(session, configured, "CRASH-1", external_id="CRASH-1")
    _score(session, job, profile)
    attempt = _stuck_attempt(session, profile, job, "submit_requested")

    recovered = control.recover_interrupted_runs(session, stale_after_s=60)
    session.commit()
    assert recovered == [attempt.autoapply_run_id]
    assert attempt.state is SubmissionState.OUTCOME_UNKNOWN
    assert session.get(AutoApplyRun, attempt.autoapply_run_id).status is BatchStatus.INTERRUPTED

    run = _run(session, profile, AutoApplyTargets(**LIVE))
    assert run.attempts == [], "an unknown outcome was queued again"
    assert configured.state.applications == {}


def test_a_crash_before_submit_is_retryable(
    configured: TestApplicationServer, session: Session, verified_profile, profile
) -> None:
    job = _job(session, configured, "CRASH-2", external_id="CRASH-2")
    _score(session, job, profile)
    attempt = _stuck_attempt(session, profile, job, "form_filled")

    control.recover_interrupted_runs(session, stale_after_s=60)
    session.commit()
    assert attempt.state is SubmissionState.FAILED
    assert attempt.failure_category == "browser_crash"

    run = _run(session, profile, AutoApplyTargets(**LIVE))
    assert run.confirmed_count == 1


def test_a_fresh_heartbeat_is_not_mistaken_for_a_crash(
    configured: TestApplicationServer, session: Session, verified_profile, profile
) -> None:
    job = _job(session, configured, "BEAT-1", external_id="BEAT-1")
    attempt = _stuck_attempt(session, profile, job, "submit_requested")
    session.get(AutoApplyRun, attempt.autoapply_run_id).heartbeat_at = utcnow()
    session.commit()
    assert control.recover_interrupted_runs(session, stale_after_s=60) == []
    assert attempt.state is SubmissionState.SUBMISSION_IN_PROGRESS


def test_an_attempt_left_mid_dispatch_is_never_picked_up_by_the_worker(
    configured: TestApplicationServer, session: Session, verified_profile, profile
) -> None:
    job = _job(session, configured, "MID-1", external_id="MID-1")
    attempt = _stuck_attempt(session, profile, job, "submit_requested")
    picked, _wait = AutoApplyService()._next_attempt_id(session, attempt.autoapply_run_id, 5)
    assert picked is None


def test_resume_settles_an_interrupted_attempt_from_its_checkpoint(
    configured: TestApplicationServer, session: Session, verified_profile, profile
) -> None:
    job = _job(session, configured, "RES-1", external_id="RES-1")
    attempt = _stuck_attempt(session, profile, job, "submit_clicked")
    AutoApplyService().resume(session, attempt.autoapply_run_id)
    assert attempt.state is SubmissionState.OUTCOME_UNKNOWN


def test_an_error_after_the_request_left_is_an_unknown_outcome(
    configured: TestApplicationServer,
    session: Session,
    verified_profile,
    profile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = _job(session, configured, "ERR-1", external_id="ERR-1")
    _score(session, job, profile)
    session.commit()
    calls: list[int] = []

    def explode(self, *args, **kwargs):
        calls.append(1)
        raise RuntimeError("connection dropped while reading the reply")

    monkeypatch.setattr(LocalTestSubmissionAdapter, "submit", explode)
    _run(session, profile, AutoApplyTargets(**LIVE, max_attempts=3))

    attempt = _attempt(session, job)
    assert attempt.state is SubmissionState.OUTCOME_UNKNOWN
    assert attempt.checkpoint in {"submit_requested", "outcome_read"}
    assert calls == [1], "an unknown outcome was retried"
    application = session.get(Application, attempt.application_id)
    assert application.status is ApplicationStatus.SUBMISSION_UNKNOWN


def test_a_transient_failure_is_retried_and_a_permanent_one_is_not(
    configured: TestApplicationServer,
    session: Session,
    verified_profile,
    profile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flaky = _job(session, configured, "FLAKY-1", external_id="FLAKY-1")
    _score(session, flaky, profile)
    session.commit()
    original = LocalTestSubmissionAdapter.submit
    calls: list[int] = []

    def once_refused(self, *args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionRefusedError("server restarting")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(LocalTestSubmissionAdapter, "submit", once_refused)
    _run(session, profile, AutoApplyTargets(**LIVE, max_attempts=3))
    attempt = _attempt(session, flaky)
    assert attempt.state is SubmissionState.SUBMITTED_CONFIRMED and attempt.attempts == 2
    assert any(event.name == "retry" for event in attempt.events)

    from app.submission.base import SubmissionResult

    rejected = _job(session, configured, "PERM-1", external_id="PERM-1")
    _score(session, rejected, profile)
    session.commit()
    permanent: list[int] = []

    def wrong_page(self, *args, **kwargs):
        permanent.append(1)
        return SubmissionResult(
            state=SubmissionState.FAILED,
            reason="not submitted: wrong page",
            response_metadata={"failure_category": "wrong_page"},
        )

    monkeypatch.setattr(LocalTestSubmissionAdapter, "submit", wrong_page)
    _run(session, profile, AutoApplyTargets(**LIVE, max_attempts=3))
    assert _attempt(session, rejected).failure_category == "wrong_page"
    assert permanent == [1]


def test_the_circuit_breaker_opens_closes_and_ignores_job_specific_failures(
    session: Session,
) -> None:
    for _ in range(2):
        state = control.record_breaker_outcome(
            session, "lever", failure_category="captcha", succeeded=False, threshold=3
        )
    assert not state.open
    control.record_breaker_outcome(
        session, "lever", failure_category="posting_closed", succeeded=False, threshold=3
    )
    assert control.breaker_state(session, "lever").consecutive_failures == 2, "neutral counted"
    state = control.record_breaker_outcome(
        session, "lever", failure_category="timeout", succeeded=False, threshold=3
    )
    assert state.open
    later = utcnow() + control.CIRCUIT_COOLDOWN + timedelta(minutes=1)
    assert not control.breaker_state(session, "lever", now=later).open, "cooldown elapsed"
    control.record_breaker_outcome(
        session, "lever", failure_category="", succeeded=True, threshold=3
    )
    assert control.breaker_state(session, "lever").consecutive_failures == 0


# --------------------------------------------------------------------------------------
# Evidence and audit trail
# --------------------------------------------------------------------------------------


def test_a_confirmed_attempt_keeps_its_full_evidence(
    configured: TestApplicationServer, session: Session, verified_profile, profile
) -> None:
    job = _job(session, configured, "EV-1", external_id="EV-1")
    _score(session, job, profile)
    session.commit()

    _run(session, profile, AutoApplyTargets(**LIVE))
    attempt = _attempt(session, job)
    assert attempt.state is SubmissionState.SUBMITTED_CONFIRMED
    assert attempt.checkpoint == "outcome_read"
    assert attempt.duration_ms is not None and attempt.duration_ms >= 0
    names = [event.name for event in attempt.events]
    assert names[0] == "queued" and "submit_requested" in names
    assert names[-1] == "outcome:submitted_confirmed"
    assert attempt.answers_sent, "the answers sent must be recorded"
    for kind in ("resume_file", "screening_answers", "profile_snapshot"):
        artifact = session.get(ApplicationArtifact, attempt.artifacts[kind])
        assert artifact is not None and artifact.locked_at is not None, kind
    resume = json.loads(session.get(ApplicationArtifact, attempt.artifacts["resume_file"]).content)
    assert len(resume["sha256"]) == 64

    locked = session.get(ApplicationArtifact, attempt.artifacts["screening_answers"])
    locked.content = "{}"
    with pytest.raises(LockedArtifactError):
        session.flush()
    session.rollback()
    with pytest.raises(LockedArtifactError):
        session.delete(session.get(ApplicationArtifact, attempt.artifacts["screening_answers"]))
        session.flush()
    session.rollback()


def test_events_and_answers_are_redacted() -> None:
    text = "reach me at jane.doe@example.com or +91 98765 43210, token=abcdef123456"
    cleaned = redact(text)
    assert "jane.doe" not in cleaned and "98765" not in cleaned and "abcdef123456" not in cleaned
    assert redact("posted 2026-11-21 for 3 roles") == "posted 2026-11-21 for 3 roles"
    assert "secret answer" not in mask_value("secret answer")


def test_log_lines_never_carry_an_email_address(caplog: pytest.LogCaptureFixture) -> None:
    from app.logging_conf import JsonFormatter

    record = logging.LogRecord("t", logging.INFO, "", 0, "mailing a@b.co", (), None)
    record.reason = "phone +91 98765 43210"
    line = JsonFormatter().format(record)
    assert "a@b.co" not in line and "98765" not in line


def test_cleanup_deletes_old_evidence_and_keeps_the_outcome(
    configured: TestApplicationServer, session: Session, verified_profile, profile, tmp_path: Path
) -> None:
    from app.config import get_settings

    data_dir = get_settings().data_dir
    shots = data_dir / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    old_shot, new_shot = shots / "old.png", shots / "new.png"
    for path in (old_shot, new_shot):
        path.write_bytes(b"png")
    stale = time.time() - 40 * 86400
    os.utime(old_shot, (stale, stale))

    job = _job(session, configured, "CL-1", external_id="CL-1")
    attempt = _stuck_attempt(session, profile, job, "queued")
    attempt.state = SubmissionState.SUBMITTED_CONFIRMED
    attempt.confirmation_id = "x-1"
    attempt.evidence_path = str(old_shot)
    attempt.events.append(
        SubmissionEvent(kind="browser", name="old", created_at=utcnow() - timedelta(days=40))
    )
    session.commit()

    report = control.cleanup_evidence(session, data_dir=data_dir, retention_days=30)
    session.commit()
    assert report.screenshots_deleted == 1 and report.events_deleted == 1
    assert not old_shot.exists() and new_shot.exists()
    assert attempt.evidence_path == "" and attempt.state is SubmissionState.SUBMITTED_CONFIRMED


def test_evidence_outside_the_private_folder_is_never_served(
    configured: TestApplicationServer, session: Session, verified_profile, profile, client
) -> None:
    job = _job(session, configured, "EVF-1", external_id="EVF-1")
    attempt = _stuck_attempt(session, profile, job, "queued")
    attempt.evidence_path = "/etc/hosts"
    session.commit()
    response = client.get(f"/api/autoapply/attempts/{attempt.id}/evidence")
    assert response.status_code == 404


# --------------------------------------------------------------------------------------
# Settling unclear outcomes
# --------------------------------------------------------------------------------------


def _unknown(session: Session, configured, profile, key: str) -> SubmissionAttempt:
    job = _job(session, configured, key, external_id=key)
    _score(session, job, profile)
    session.commit()
    attempt = _stuck_attempt(session, profile, job, "submit_clicked")
    application = Application(
        job_id=job.id,
        profile_id=profile.id,
        platform=SourceName.GREENHOUSE,
        status=ApplicationStatus.SUBMISSION_UNKNOWN,
        user_approved=True,
    )
    session.add(application)
    session.flush()
    attempt.application_id = application.id
    attempt.state = SubmissionState.OUTCOME_UNKNOWN
    session.commit()
    return attempt


def test_resolving_as_submitted_needs_evidence_and_confirms_the_application(
    configured: TestApplicationServer, session: Session, verified_profile, profile
) -> None:
    attempt = _unknown(session, configured, profile, "RSV-1")
    with pytest.raises(ResolutionError):
        resolve(session, attempt, outcome="submitted", evidence="")
    resolve(session, attempt, outcome="submitted", evidence="confirmation email ref GH-1234")
    session.commit()
    assert attempt.state is SubmissionState.SUBMITTED_CONFIRMED
    assert attempt.confirmation_id.startswith("user-")
    application = session.get(Application, attempt.application_id)
    assert application.status is ApplicationStatus.CONFIRMED


def test_resolving_as_not_submitted_lets_a_later_run_try_again(
    configured: TestApplicationServer, session: Session, verified_profile, profile, client
) -> None:
    attempt = _unknown(session, configured, profile, "RSV-2")
    session.get(AutoApplyRun, attempt.autoapply_run_id).status = BatchStatus.COMPLETED
    session.commit()
    response = client.post(
        f"/api/autoapply/attempts/{attempt.id}/resolve",
        json={"outcome": "not_submitted", "evidence": "nothing in my inbox"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["failure_category"] == "user_verified_not_sent"
    session.expire_all()
    run = _run(session, profile, AutoApplyTargets(**LIVE))
    assert run.confirmed_count == 1


def test_a_confirmed_attempt_cannot_be_resolved_again(
    configured: TestApplicationServer, session: Session, verified_profile, profile, client
) -> None:
    attempt = _unknown(session, configured, profile, "RSV-3")
    resolve(session, attempt, outcome="submitted", evidence="reference 99")
    session.commit()
    response = client.post(
        f"/api/autoapply/attempts/{attempt.id}/resolve", json={"outcome": "not_submitted"}
    )
    assert response.status_code == 409


# --------------------------------------------------------------------------------------
# API surface
# --------------------------------------------------------------------------------------


def test_preflight_and_control_endpoints(
    configured: TestApplicationServer, session: Session, verified_profile, profile, client
) -> None:
    job = _job(session, configured, "API-1", external_id="API-1")
    _score(session, job, profile)
    session.commit()

    body = client.post("/api/autoapply/preflight", json={"dry_run": False, "min_score": 50}).json()
    assert body["counts"]["ready"] == 1
    assert body["jobs"][0]["job_id"] == job.id and body["jobs"][0]["status"] == "ready"

    status = client.get("/api/autoapply/control").json()
    assert status["emergency_stop"] is False
    stopped = client.post("/api/autoapply/emergency-stop", json={"reason": "testing"}).json()
    assert stopped["emergency_stop"] is True
    cleared = client.post("/api/autoapply/emergency-stop/clear").json()
    assert cleared["emergency_stop"] is False

    saved = client.put("/api/autoapply/preferences", json={"min_score": 80, "platforms": ["lever"]})
    assert saved.status_code == 200
    assert client.get("/api/autoapply/preferences").json()["min_score"] == 80


def test_demo_mode_refuses_the_safety_controls(demo_client) -> None:
    for path in ("/api/autoapply/emergency-stop", "/api/autoapply/evidence/cleanup"):
        response = demo_client.post(path, json={})
        assert response.status_code == 403, path


def test_auto_apply_never_sends_a_junior_to_a_senior_title(
    configured: TestApplicationServer, session: Session, verified_profile, profile
) -> None:
    """The feed may show a stretch role; auto-apply must not send to one.

    Regression: a "Sr." title with no stated years passed as ready for a junior profile,
    because the matcher's seniority tolerance (two levels) is meant for browsing.
    """
    verified_profile.experience_level = "junior"
    senior = _job(
        session, configured, "SEN-1", external_id="SEN-1", title="Sr. Software Development Engineer"
    )
    senior.experience_min_years = None
    _score(session, senior, profile, score=95)
    peer = _job(session, configured, "SEN-2", external_id="SEN-2", title="Software Engineer")
    peer.experience_min_years = None
    _score(session, peer, profile, score=80)
    session.commit()

    graded = _job(session, configured, "SEN-3", external_id="SEN-3", title="Software Engineer 3")
    graded.experience_min_years = None
    _score(session, graded, profile, score=90)
    next_step = _job(session, configured, "SEN-4", external_id="SEN-4", title="SDE-II Backend")
    next_step.experience_min_years = None
    _score(session, next_step, profile, score=85)
    session.commit()

    plan = run_preflight(session, profile, AutoApplyTargets(**LIVE))
    by_id = {item.job_id: item for item in plan.jobs}
    assert by_id[senior.id].status == "blocked"
    assert "level-3" in " ".join(by_id[senior.id].blocking_reasons)
    assert by_id[graded.id].status == "blocked", "a numbered grade 3 is above a junior"
    assert by_id[next_step.id].status == "ready", "one grade up is allowed"
    assert by_id[peer.id].status == "ready", "a title without a level must not be blocked"


def test_an_application_approved_in_review_stays_eligible_for_auto_apply(
    configured: TestApplicationServer, session: Session, verified_profile, profile
) -> None:
    """Approving in the review queue vouches for the application; it must not drop out."""
    job = _job(session, configured, "APR-1", external_id="APR-1")
    _score(session, job, profile)
    session.commit()
    first = _run(session, profile, AutoApplyTargets(**{**LIVE, "dry_run": True}))
    application = session.get(Application, first.attempts[0].application_id)
    application.status = ApplicationStatus.APPROVED
    application.user_approved = True
    session.commit()

    plan = run_preflight(session, profile, AutoApplyTargets(**LIVE))
    assert job.id in plan.queue_job_ids
    run = _run(session, profile, AutoApplyTargets(**LIVE))
    assert run.confirmed_count == 1
    assert session.get(Application, application.id).status is ApplicationStatus.CONFIRMED


def test_a_dry_run_that_cannot_fill_the_form_is_not_reported_ready(
    configured: TestApplicationServer,
    session: Session,
    verified_profile,
    profile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: a preview that stopped mid-form still read 'ready to submit'."""
    job = _job(session, configured, "PREV-1", external_id="PREV-1")
    _score(session, job, profile)
    session.commit()
    monkeypatch.setattr(
        LocalTestSubmissionAdapter,
        "preview_fill",
        lambda self, *args, **kwargs: "dry run stopped while filling: Country: not shown",
        raising=False,
    )
    _run(session, profile, AutoApplyTargets(**{**LIVE, "dry_run": True}))

    attempt = _attempt(session, job)
    assert attempt.state is SubmissionState.FAILED
    assert attempt.failure_category == "form_changed"
    assert "Country" in attempt.detail
    assert configured.state.applications == {}
