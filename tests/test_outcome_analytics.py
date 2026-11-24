"""Outcome analytics: honest denominators, prepared never counted as sent."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.db.models import (
    Application,
    ApplicationStatus,
    AutoApplyRun,
    InterviewRound,
    Outcome,
    SourceName,
    SubmissionAttempt,
    SubmissionState,
    utcnow,
)
from app.services.outcome_analytics import MIN_DENOMINATOR, build_outcome_report
from tests.conftest import persist_job


def _app(session: Session, profile, index: int, status, outcome=Outcome.PENDING) -> Application:
    job = persist_job(
        session,
        source=SourceName.GREENHOUSE,
        external_id=f"OA-{index}",
        title="Backend Developer",
        company=f"Co {chr(65 + index)}",
    )
    job.posted_at = utcnow() - timedelta(hours=30)
    row = Application(
        job_id=job.id,
        profile_id=profile.id,
        platform=SourceName.GREENHOUSE,
        status=status,
        outcome=outcome,
        prepared_at=utcnow(),
        submitted_at=utcnow()
        if status in (ApplicationStatus.SUBMITTED, ApplicationStatus.CONFIRMED)
        else None,
    )
    session.add(row)
    session.flush()
    return row


def test_prepared_applications_are_never_counted_as_sent(session: Session, profile) -> None:
    for index in range(4):
        _app(session, profile, index, ApplicationStatus.READY_FOR_REVIEW)
    report = build_outcome_report(session, profile)
    assert report.funnel["applications_prepared"] == 4
    assert report.funnel["applications_marked_submitted"] == 0
    assert report.funnel["confirmed_submissions"] == 0
    assert report.rates["interview_rate"]["value"] is None


def test_a_rate_needs_enough_applications_behind_it(session: Session, profile) -> None:
    _app(session, profile, 0, ApplicationStatus.CONFIRMED, Outcome.INTERVIEWING)
    report = build_outcome_report(session, profile)
    assert report.rates["interview_rate"]["value"] is None, "1 of 1 must not read as 100%"
    assert "fewer than" in report.rates["interview_rate"]["note"]

    for index in range(1, MIN_DENOMINATOR):
        _app(session, profile, index, ApplicationStatus.CONFIRMED, Outcome.REJECTED)
    report = build_outcome_report(session, profile)
    assert report.rates["interview_rate"]["value"] == round(100 / MIN_DENOMINATOR, 1)
    assert report.funnel["rejections"] == MIN_DENOMINATOR - 1


def test_attempts_split_confirmed_unknown_and_failed(session: Session, profile) -> None:
    app = _app(session, profile, 0, ApplicationStatus.SUBMISSION_UNKNOWN)
    run = AutoApplyRun(profile_id=profile.id)
    session.add(run)
    session.flush()
    rows = [
        (SubmissionState.SUBMITTED_CONFIRMED, "outcome_read", "", "c-1"),
        (SubmissionState.OUTCOME_UNKNOWN, "submit_clicked", "unknown_outcome", ""),
        (SubmissionState.FAILED, "form_filled", "form_changed", ""),
        (SubmissionState.FAILED, "outcome_read", "validation_rejected", ""),
    ]
    for index, (state, checkpoint, category, confirmation) in enumerate(rows):
        job = persist_job(
            session,
            source=SourceName.LEVER,
            external_id=f"AT-{index}",
            title=f"Role {index}",
            company=f"Attempt Company {chr(65 + index)}",
            url=f"https://jobs.example.com/at/{index}",
        )
        session.add(
            SubmissionAttempt(
                autoapply_run_id=run.id,
                job_id=job.id,
                application_id=app.id,
                state=state,
                checkpoint=checkpoint,
                failure_category=category,
                confirmation_id=confirmation,
                idempotency_key=f"k-{index}",
            )
        )
    session.flush()
    funnel = build_outcome_report(session, profile).funnel
    assert funnel["submission_attempts"] == 3
    assert funnel["confirmed_submissions"] == 1
    assert funnel["unknown_outcomes"] == 1
    assert funnel["failed_submissions"] == 1 and funnel["failed_before_submit"] == 1
    report = build_outcome_report(session, profile)
    assert report.failure_reasons["form_changed"] == 1
    assert report.time_saved["is_estimate"] and report.time_saved["estimate_minutes"] > 0


def test_series_use_real_dates_and_missing_is_reported(session: Session, profile) -> None:
    app = _app(session, profile, 0, ApplicationStatus.CONFIRMED, Outcome.INTERVIEWING)
    _app(session, profile, 1, ApplicationStatus.CONFIRMED, Outcome.SCREENING)
    session.add(InterviewRound(application_id=app.id, round_name="R1", scheduled_at=utcnow()))
    session.flush()
    report = build_outcome_report(session, profile)
    assert sum(week.get("sent", 0) for week in report.weekly.values()) == 2
    assert sum(week.get("interview_rounds", 0) for week in report.weekly.values()) == 1
    assert report.missing["interviews_without_a_dated_round"] == 1
    assert report.freshness["median_hours_posted_to_sent"] is not None


def test_the_endpoint_serves_the_report(client) -> None:
    body = client.get("/api/metrics/outcomes").json()
    assert body["funnel"]["confirmed_submissions"] == 0
    assert body["min_denominator"] == MIN_DENOMINATOR
