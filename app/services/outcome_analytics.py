"""Application outcome analytics, computed only from what was recorded.

The rules, because each prevents a specific misleading number:

* **Prepared is not submitted.** A prepared application, a dispatched attempt and a
  confirmed submission are counted separately; only ``SUBMITTED_CONFIRMED`` attempts and
  ``CONFIRMED`` applications count as sent (see :func:`~app.submission.states.counts_as_sent`).
* **No rate from a handful.** A conversion rate needs at least :data:`MIN_DENOMINATOR`
  applications behind it; below that it is ``None`` with the reason, never 0% or 100%.
* **Missing is not zero.** Where a fact was never recorded (an undated posting, an
  interview with no recorded round) it is counted as missing, not folded into zero.
* **Real timestamps only.** Weekly and monthly series use ``submitted_at`` and recorded
  interview round dates. Nothing is back-dated or interpolated.
* **Estimates say so.** "Time saved" is confirmed browser submissions multiplied by a
  configured minutes-per-application figure, and is labelled as an estimate with that
  assumption attached.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import (
    Application,
    ApplicationStatus,
    AutoApplyRun,
    CandidateProfile,
    InterviewRound,
    JobMatch,
    JobSourceReference,
    Outcome,
    SubmissionAttempt,
    SubmissionState,
)
from app.db.repositories.jobs import light_jobs_query
from app.services.resume_variants import infer_job_family
from app.submission.states import SUBMIT_REACHED, counts_as_sent

#: Smallest number of sent applications a conversion rate is computed from.
MIN_DENOMINATOR = 5

_SENT_STATUSES = (ApplicationStatus.SUBMITTED, ApplicationStatus.CONFIRMED)
_INTERVIEW = (Outcome.SCREENING, Outcome.INTERVIEWING, Outcome.OFFER, Outcome.ACCEPTED)
_OFFER = (Outcome.OFFER, Outcome.ACCEPTED)


@dataclass(slots=True)
class Rate:
    value: float | None
    numerator: int
    denominator: int
    note: str = ""


def rate(numerator: int, denominator: int) -> Rate:
    if denominator < MIN_DENOMINATOR:
        return Rate(
            None,
            numerator,
            denominator,
            f"not computed: {denominator} sent application(s), fewer than {MIN_DENOMINATOR}",
        )
    return Rate(round(100.0 * numerator / denominator, 1), numerator, denominator)


@dataclass(slots=True)
class Segment:
    """Performance of one slice (a source, a job family, an employer, a score band)."""

    discovered: int = 0
    sent: int = 0
    interviews: int = 0
    rejections: int = 0
    offers: int = 0

    def as_dict(self) -> dict[str, Any]:
        interview_rate = rate(self.interviews, self.sent)
        return {
            "discovered": self.discovered,
            "sent": self.sent,
            "interviews": self.interviews,
            "rejections": self.rejections,
            "offers": self.offers,
            "interview_rate": interview_rate.value,
            "interview_rate_note": interview_rate.note,
        }


@dataclass(slots=True)
class OutcomeReport:
    funnel: dict[str, int] = field(default_factory=dict)
    rates: dict[str, dict[str, Any]] = field(default_factory=dict)
    time_saved: dict[str, Any] = field(default_factory=dict)
    by_source: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_job_family: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_employer: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_score_band: dict[str, dict[str, Any]] = field(default_factory=dict)
    failure_reasons: dict[str, int] = field(default_factory=dict)
    duplicate_rate: float | None = None
    freshness: dict[str, Any] = field(default_factory=dict)
    weekly: dict[str, dict[str, int]] = field(default_factory=dict)
    monthly: dict[str, dict[str, int]] = field(default_factory=dict)
    missing: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "funnel": self.funnel,
            "rates": self.rates,
            "time_saved": self.time_saved,
            "by_source": self.by_source,
            "by_job_family": self.by_job_family,
            "by_employer": self.by_employer,
            "by_score_band": self.by_score_band,
            "failure_reasons": self.failure_reasons,
            "duplicate_rate": self.duplicate_rate,
            "freshness": self.freshness,
            "weekly": self.weekly,
            "monthly": self.monthly,
            "missing": self.missing,
            "notes": self.notes,
            "min_denominator": MIN_DENOMINATOR,
        }


def _week(moment: datetime) -> str:
    year, week, _ = moment.isocalendar()
    return f"{year}-W{week:02d}"


def _count(outcome: Outcome, segment: Segment) -> None:
    if outcome in _INTERVIEW:
        segment.interviews += 1
    if outcome is Outcome.REJECTED:
        segment.rejections += 1
    if outcome in _OFFER:
        segment.offers += 1


def build_outcome_report(session: Session, profile: CandidateProfile) -> OutcomeReport:
    report = OutcomeReport()
    jobs = {job.id: job for job in session.scalars(light_jobs_query()).all()}
    sources: dict[int, str] = {}
    for job_id, source in session.execute(
        select(JobSourceReference.job_id, JobSourceReference.source).order_by(JobSourceReference.id)
    ).all():
        sources.setdefault(job_id, getattr(source, "value", str(source)))
    matches = {
        match.job_id: match
        for match in session.scalars(
            select(JobMatch).where(JobMatch.profile_id == profile.id)
        ).all()
    }
    applications = session.scalars(
        select(Application).where(Application.profile_id == profile.id)
    ).all()
    attempts = session.scalars(
        select(SubmissionAttempt)
        .join(AutoApplyRun, AutoApplyRun.id == SubmissionAttempt.autoapply_run_id)
        .where(AutoApplyRun.profile_id == profile.id)
    ).all()
    rounds = session.scalars(
        select(InterviewRound)
        .join(Application, Application.id == InterviewRound.application_id)
        .where(Application.profile_id == profile.id)
    ).all()

    # ---- funnel ----
    duplicates = sum(1 for job in jobs.values() if job.duplicate_of_id is not None)
    eligible = sum(1 for match in matches.values() if not match.filtered_out)
    sent_apps = [app for app in applications if app.status in _SENT_STATUSES]
    confirmed_apps = [app for app in applications if app.status is ApplicationStatus.CONFIRMED]
    dispatched = [a for a in attempts if a.checkpoint in SUBMIT_REACHED or counts_as_sent(a.state)]
    report.funnel = {
        "jobs_discovered": len(jobs),
        "eligible_jobs": eligible,
        "applications_prepared": sum(1 for app in applications if app.prepared_at is not None),
        "submission_attempts": len(dispatched),
        "confirmed_submissions": sum(1 for a in attempts if counts_as_sent(a.state)),
        "applications_confirmed": len(confirmed_apps),
        "applications_marked_submitted": len(sent_apps),
        "unknown_outcomes": sum(1 for a in attempts if a.state is SubmissionState.OUTCOME_UNKNOWN),
        "failed_submissions": sum(
            1
            for a in attempts
            if a.state is SubmissionState.FAILED and a.checkpoint in SUBMIT_REACHED
        ),
        "failed_before_submit": sum(
            1
            for a in attempts
            if a.state is SubmissionState.FAILED and a.checkpoint not in SUBMIT_REACHED
        ),
        "waiting_on_you": sum(
            1
            for a in attempts
            if a.state
            in (SubmissionState.BLOCKED_MISSING_INFO, SubmissionState.REQUIRES_USER_ACTION)
        ),
        "interviews": sum(1 for app in applications if app.outcome in _INTERVIEW),
        "rejections": sum(1 for app in applications if app.outcome is Outcome.REJECTED),
        "offers": sum(1 for app in applications if app.outcome in _OFFER),
    }
    sent_count = len(sent_apps)
    for name, numerator in (
        ("interview_rate", report.funnel["interviews"]),
        ("rejection_rate", report.funnel["rejections"]),
        ("offer_rate", report.funnel["offers"]),
    ):
        value = rate(numerator, sent_count)
        report.rates[name] = {
            "value": value.value,
            "numerator": value.numerator,
            "denominator": value.denominator,
            "note": value.note or "of applications recorded as submitted",
        }
    attempted = len(dispatched)
    confirm = rate(report.funnel["confirmed_submissions"], attempted)
    report.rates["confirmation_rate"] = {
        "value": confirm.value,
        "numerator": confirm.numerator,
        "denominator": confirm.denominator,
        "note": confirm.note or "of auto-apply attempts that pressed Submit",
    }

    # ---- time saved: an estimate, labelled as one ----
    minutes = get_settings().minutes_per_manual_application
    confirmed_auto = report.funnel["confirmed_submissions"]
    report.time_saved = {
        "estimate_minutes": confirmed_auto * minutes,
        "confirmed_auto_submissions": confirmed_auto,
        "assumption": (
            f"{minutes} minutes per application form filled by hand "
            "(JA_MINUTES_PER_MANUAL_APPLICATION); only confirmed auto-submissions count"
        ),
        "is_estimate": True,
    }

    # ---- segments ----
    by_source: dict[str, Segment] = defaultdict(Segment)
    by_family: dict[str, Segment] = defaultdict(Segment)
    by_employer: dict[str, Segment] = defaultdict(Segment)
    by_band: dict[str, Segment] = defaultdict(Segment)
    for job in jobs.values():
        if job.duplicate_of_id is not None:
            continue
        by_source[sources.get(job.id, "unknown")].discovered += 1
        by_family[infer_job_family(job.title, list(job.required_skills or []))].discovered += 1
        by_employer[job.company or "unknown"].discovered += 1
        match = matches.get(job.id)
        by_band[match.band if match is not None else "unscored"].discovered += 1
    for app in sent_apps:
        applied_job = jobs.get(app.job_id)
        if applied_job is None:
            continue
        match = matches.get(applied_job.id)
        for segment in (
            by_source[sources.get(applied_job.id, "unknown")],
            by_family[infer_job_family(applied_job.title, list(applied_job.required_skills or []))],
            by_employer[applied_job.company or "unknown"],
            by_band[match.band if match is not None else "unscored"],
        ):
            segment.sent += 1
            _count(app.outcome, segment)
    report.by_source = {key: seg.as_dict() for key, seg in sorted(by_source.items())}
    report.by_job_family = {key: seg.as_dict() for key, seg in sorted(by_family.items())}
    top_employers = sorted(
        by_employer.items(), key=lambda item: (-item[1].sent, -item[1].discovered)
    )
    report.by_employer = {key: seg.as_dict() for key, seg in top_employers[:20]}
    report.by_score_band = {key: seg.as_dict() for key, seg in sorted(by_band.items())}

    # ---- failures ----
    report.failure_reasons = dict(
        Counter(
            a.failure_category or "uncategorised"
            for a in attempts
            if a.state
            in (
                SubmissionState.FAILED,
                SubmissionState.OUTCOME_UNKNOWN,
                SubmissionState.REQUIRES_USER_ACTION,
                SubmissionState.BLOCKED_MISSING_INFO,
            )
        ).most_common()
    )
    report.duplicate_rate = round(100.0 * duplicates / len(jobs), 2) if jobs else None

    # ---- posting freshness at the time of sending ----
    ages: list[float] = []
    undated = 0
    for app in sent_apps:
        sent_job = jobs.get(app.job_id)
        if sent_job is None or app.submitted_at is None:
            continue
        if sent_job.posted_at is None:
            undated += 1
            continue
        ages.append((app.submitted_at - sent_job.posted_at).total_seconds() / 3600.0)
    report.freshness = {
        "median_hours_posted_to_sent": round(median(ages), 1) if ages else None,
        "measured": len(ages),
        "undated_postings": undated,
    }

    # ---- time series from real timestamps ----
    weekly: dict[str, Counter[str]] = defaultdict(Counter)
    monthly: dict[str, Counter[str]] = defaultdict(Counter)
    missing_dates = 0
    for app in sent_apps:
        if app.submitted_at is None:
            missing_dates += 1
            continue
        weekly[_week(app.submitted_at)]["sent"] += 1
        monthly[app.submitted_at.strftime("%Y-%m")]["sent"] += 1
        if app.status is ApplicationStatus.CONFIRMED:
            weekly[_week(app.submitted_at)]["confirmed"] += 1
            monthly[app.submitted_at.strftime("%Y-%m")]["confirmed"] += 1
    app_ids = {app.id for app in applications}
    dated_interviews = 0
    for round_row in rounds:
        if round_row.application_id not in app_ids or round_row.scheduled_at is None:
            continue
        dated_interviews += 1
        weekly[_week(round_row.scheduled_at)]["interview_rounds"] += 1
        monthly[round_row.scheduled_at.strftime("%Y-%m")]["interview_rounds"] += 1
    report.weekly = {key: dict(value) for key, value in sorted(weekly.items())}
    report.monthly = {key: dict(value) for key, value in sorted(monthly.items())}
    report.missing = {
        "sent_without_submitted_at": missing_dates,
        "interviews_without_a_dated_round": max(
            0,
            report.funnel["interviews"] - len({r.application_id for r in rounds if r.scheduled_at}),
        ),
        "undated_postings_among_sent": undated,
    }
    if not sent_apps:
        report.notes.append("No application is recorded as submitted yet, so no rate is shown.")
    report.notes.append(
        "Interviews are counted from the outcome you record; the series dates them by the "
        "interview rounds you log."
    )
    return report


__all__ = ["MIN_DENOMINATOR", "OutcomeReport", "build_outcome_report", "rate"]
