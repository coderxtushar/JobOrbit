"""Metrics.

Counted facts and estimates are returned by two different functions and rendered in two
different sections of the dashboard. :func:`estimated_metrics` is the only place an
estimate is produced, and it carries the assumption it rests on in its own ``basis`` field.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Application, ApplicationStatus, Job
from app.db.repositories import (
    ApplicationRepository,
    AuditRepository,
    ImportRunRepository,
    MatchRepository,
)
from app.schemas.source import EstimatedMetrics, OperationalMetrics

MINUTES_SAVED_PER_PREPARED_APPLICATION = 12


def operational_metrics(session: Session, profile_id: int) -> OperationalMetrics:
    jobs_total = int(session.scalar(select(func.count(Job.id))) or 0)
    applications = ApplicationRepository(session)
    matches = MatchRepository(session)
    runs = ImportRunRepository(session)

    status_counts = applications.status_counts()
    import_totals = runs.totals()

    review_queue = int(
        session.scalar(
            select(func.count(Application.id)).where(
                Application.status.in_(
                    [ApplicationStatus.READY_FOR_REVIEW, ApplicationStatus.APPROVED]
                )
            )
        )
        or 0
    )
    prepared = int(
        session.scalar(
            select(func.count(Application.id)).where(Application.prepared_at.is_not(None))
        )
        or 0
    )

    return OperationalMetrics(
        jobs_total=jobs_total,
        jobs_by_status=_job_status_counts(session),
        jobs_imported=import_totals["jobs_created"],
        records_invalid=import_totals["records_invalid"],
        duplicates_detected=import_totals["duplicates_detected"],
        jobs_filtered_out=matches.filtered_out_count(profile_id),
        match_bands=matches.band_counts(profile_id),
        review_queue_size=review_queue,
        applications_by_status=status_counts,
        applications_by_outcome=applications.outcome_counts(),
        applications_prepared=prepared,
        applications_submitted=status_counts.get(ApplicationStatus.SUBMITTED.value, 0)
        + status_counts.get(ApplicationStatus.CONFIRMED.value, 0),
        applications_confirmed=status_counts.get(ApplicationStatus.CONFIRMED.value, 0),
        import_failures=runs.failure_count(),
        audit_entries=AuditRepository(session).count(),
    )


def _job_status_counts(session: Session) -> dict[str, int]:
    rows = session.execute(select(Job.status, func.count(Job.id)).group_by(Job.status)).all()
    return {status.value: count for status, count in rows}


def estimated_metrics(prepared_applications: int) -> EstimatedMetrics:
    """An estimate, labelled as such, of manual form-filling time avoided."""
    return EstimatedMetrics(
        estimated_minutes_saved=prepared_applications * MINUTES_SAVED_PER_PREPARED_APPLICATION,
        basis=(
            f"Estimate only: {MINUTES_SAVED_PER_PREPARED_APPLICATION} minutes per prepared "
            f"application x {prepared_applications} prepared. This is an assumption about "
            "manual form-filling and answer-drafting time, not a measurement."
        ),
    )
