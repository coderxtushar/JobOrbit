"""Auto-apply preflight: what a run would do, job by job, before anything is authorised.

A run used to be authorised against a count. The preflight replaces that with an itemised
plan the user can inspect: every job the scope touches, which hard constraint (if any)
removes it, what score and evidence it has, which resume and answers would go with it,
which questions are still open, and whether its platform can be submitted to at all.

Two rules shape it.

* **Hard constraints are not scores.** Experience, location, remote preference, role
  family, employer exclusions, platform selection, freshness, duplicates and earlier
  applications each remove a job on their own, with a reason, regardless of how well it
  scores. A job that ranks first but asks for five years more than the candidate has is
  blocked, not ranked lower.
* **The run executes this plan, not a fresh guess.** :func:`run_preflight` is the same
  function the orchestrator calls to build its queue, and when the user approves a
  specific list of jobs the run is limited to that list. A job that stopped qualifying
  between preview and start is dropped rather than sent.

Nothing here contacts a provider or writes to the database.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    AnswerProvenance,
    Application,
    ApplicationStatus,
    AutoApplyRun,
    BatchStatus,
    CandidateProfile,
    Job,
    JobMatch,
    JobSourceReference,
    JobStatus,
    JobUserState,
    Resume,
    SavedAnswer,
    SubmissionAttempt,
    SubmissionState,
    WorkArrangement,
    utcnow,
)
from app.services.batch import confidence_at_least
from app.services.filters import SENIORITY_BY_LEVEL
from app.services.questions import build_question_set
from app.services.redaction import mask_value
from app.services.resume_variants import infer_job_family
from app.services.text import normalize_company, normalize_location, seniority_level
from app.services.tracking import blocking_questions

if TYPE_CHECKING:  # pragma: no cover
    from app.services.autoapply import AutoApplyTargets

#: Application statuses meaning the user has already dealt with this job.
_HANDLED_STATUSES: dict[ApplicationStatus, str] = {
    ApplicationStatus.SUBMITTED: "you have already applied",
    ApplicationStatus.CONFIRMED: "you have already applied (confirmed)",
    ApplicationStatus.SUBMISSION_UNKNOWN: "an earlier submission's outcome is still unknown",
    ApplicationStatus.SKIPPED: "you skipped this job",
}
# APPROVED is deliberately absent: approving an application in the review queue is the
# user vouching for it, so it stays eligible for auto-apply. Duplicate protection does not
# depend on this list; it comes from dispatched attempts and the pre-dispatch re-check.

#: Attempt states proving the employer may already hold an application.
_DISPATCHED_STATES: frozenset[SubmissionState] = frozenset(
    {
        SubmissionState.SUBMITTED_CONFIRMED,
        SubmissionState.OUTCOME_UNKNOWN,
        SubmissionState.SUBMISSION_IN_PROGRESS,
    }
)

_ACTIVE_RUN_STATUSES = (BatchStatus.PENDING, BatchStatus.RUNNING, BatchStatus.PAUSED)

REMOTE_PREFERENCES = ("any", "remote_only", "remote_or_hybrid", "onsite_or_hybrid")

#: Status of one job in the plan, in the order a reader should care about them.
STATUS_READY = "ready"
STATUS_NEEDS_ANSWERS = "needs_answers"
STATUS_UNSUPPORTED = "unsupported"
STATUS_BLOCKED = "blocked"
STATUS_INELIGIBLE = "ineligible"
STATUS_BELOW_THRESHOLD = "below_threshold"
STATUS_STALE = "stale"
STATUS_APPLIED = "applied"
STATUS_DUPLICATE = "duplicate"


@dataclass(slots=True)
class Fit:
    """One hard-constraint verdict: ``ok``, ``fail`` or ``unknown`` (not enough data)."""

    status: str
    detail: str = ""


@dataclass(slots=True)
class ScreeningAnswer:
    question: str
    question_key: str
    answer: str
    provenance: str
    sensitive: bool
    source: str


@dataclass(slots=True)
class JobPlan:
    """Everything the user needs to judge one job before authorising the batch."""

    job_id: int
    title: str
    employer: str
    sources: list[str]
    url: str
    posted_at: datetime | None
    discovered_at: datetime | None
    score: float | None
    band: str
    evidence_coverage: float | None
    confidence: str
    role_family: str
    location_fit: Fit
    experience_fit: Fit
    platform: str
    platform_name: str
    submission_supported: bool
    capability_reason: str
    resume_artifact: str
    cover_letter_preview: str
    application_id: int | None
    screening_answers: list[ScreeningAnswer] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: str = STATUS_READY
    #: Would be queued by a run (its attempt recorded, even if the platform refuses it).
    queued: bool = False
    #: Would be counted against the submission budget: queued, supported, fully answered.
    planned: bool = False


@dataclass(slots=True)
class PreflightCounts:
    total_discovered: int = 0
    new_jobs: int = 0
    duplicates: int = 0
    previously_applied: int = 0
    scored: int = 0
    meeting_score: int = 0
    meeting_confidence: int = 0
    meeting_experience: int = 0
    meeting_location: int = 0
    expired_or_stale: int = 0
    missing_answers: int = 0
    blocked_by_eligibility: int = 0
    blocked_by_constraints: int = 0
    unsupported_platform: int = 0
    ready: int = 0
    queued: int = 0
    planned_attempts: int = 0
    daily_cap: int | None = None
    dispatched_today: int = 0
    daily_cap_remaining: int | None = None


@dataclass(slots=True)
class Preflight:
    counts: PreflightCounts
    jobs: list[JobPlan]
    queue_job_ids: list[int]
    notes: list[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=utcnow)

    def summary(self) -> dict[str, Any]:
        """Compact record of what the user saw, stored on the run they authorise."""
        return {
            "generated_at": self.generated_at.isoformat(),
            "counts": asdict(self.counts),
            "queue_job_ids": list(self.queue_job_ids),
            "notes": list(self.notes),
        }


# --------------------------------------------------------------------------------------
# Individual hard constraints
# --------------------------------------------------------------------------------------


#: How far above the candidate's own level a title may be before auto-apply will not send
#: to it. The feed is looser on purpose (it shows a stretch role so the user can decide);
#: sending an application is a stronger act, so one level up is the limit here.
AUTOAPPLY_SENIORITY_STEP = 1


#: A numbered grade after a role word: "Software Engineer 3", "SDE-II", "Analyst IV".
#: Numbered grades are the usual way large employers write seniority, and the word-based
#: detector cannot see them. Roman numerals are matched only after a role word, so a
#: pronoun "I" elsewhere in a title cannot be read as a grade.
_NUMBERED_GRADE = re.compile(
    r"\b(?i:engineer|developer|sde|swe|programmer|analyst|scientist|associate)"
    r"\s*[-,]?\s*(IV|III|II|I|[1-5])\b"
)
_GRADE_VALUE = {"I": 1, "II": 2, "III": 3, "IV": 4}


def _title_grade(title: str) -> int | None:
    """Seniority from a title's words and from a numbered grade, whichever is higher."""
    levels = [level for level in (seniority_level(title),) if level is not None]
    for match in _NUMBERED_GRADE.finditer(title or ""):
        token = match.group(1)
        levels.append(_GRADE_VALUE.get(token) or int(token))
    return max(levels) if levels else None


def _experience_fit(job: Job, profile: CandidateProfile, tolerance: float | None) -> Fit:
    required = job.experience_min_years
    title_level = _title_grade(job.title or "")
    own_level = SENIORITY_BY_LEVEL.get(profile.experience_level or "", 0)
    if title_level is not None and title_level - own_level > AUTOAPPLY_SENIORITY_STEP:
        # Checked even when the listing gives years: "Sr." with "2+ years" is still a
        # senior hire, and the title is what the employer screens on first.
        return Fit(
            "fail",
            f"the title reads as a level-{title_level} role and your profile is "
            f"'{profile.experience_level}' (level {own_level}); auto-apply only sends to "
            f"roles at most {AUTOAPPLY_SENIORITY_STEP} level above yours",
        )
    if required is None:
        return Fit("unknown", "the listing states no minimum experience")
    have = float(profile.years_experience or 0.0)
    slack = 0.0 if tolerance is None else max(0.0, float(tolerance))
    if required > have + slack:
        return Fit(
            "fail",
            f"asks for at least {required:g} years; you have {have:g} (tolerance {slack:g})",
        )
    return Fit("ok", f"asks for {required:g}+ years; you have {have:g}")


def _location_fit(
    job: Job, profile: CandidateProfile, locations: list[str], remote_preference: str
) -> Fit:
    arrangement = job.work_arrangement
    preference = remote_preference if remote_preference in REMOTE_PREFERENCES else "any"
    unknown_arrangement = arrangement in (None, WorkArrangement.UNKNOWN)

    if preference == "remote_only":
        if unknown_arrangement:
            return Fit("fail", "you asked for remote only and the listing does not say remote")
        if arrangement is not WorkArrangement.REMOTE:
            return Fit("fail", f"you asked for remote only; this role is {arrangement.value}")
    elif preference == "remote_or_hybrid":
        if arrangement is WorkArrangement.ONSITE:
            return Fit("fail", "you asked for remote or hybrid; this role is onsite")
    elif preference == "onsite_or_hybrid" and arrangement is WorkArrangement.REMOTE:
        return Fit("fail", "you asked for onsite or hybrid; this role is remote")

    allowed = [normalize_location(item) for item in (locations or []) if item.strip()]
    if not allowed:
        allowed = [normalize_location(item) for item in (profile.preferred_locations or []) if item]
    if arrangement is WorkArrangement.REMOTE and preference != "onsite_or_hybrid":
        return Fit("ok", "remote role")
    if not allowed:
        return Fit("ok" if job.location_normalized else "unknown", "no location limit set")
    if not job.location_normalized:
        return Fit("unknown", "the listing states no location")

    job_parts = {part.strip() for part in job.location_normalized.split(",") if part.strip()}
    for wanted in allowed:
        wanted_parts = {part.strip() for part in wanted.split(",") if part.strip()}
        if job_parts & wanted_parts or any(
            want in part or part in want for part in job_parts for want in wanted_parts
        ):
            return Fit("ok", f"{job.location} matches {wanted}")
    if profile.open_to_relocation and not locations:
        return Fit("ok", f"{job.location}: outside your locations, but you are open to relocation")
    return Fit("fail", f"{job.location or 'unstated'} is outside your allowed locations")


def _too_old(job: Job, max_age_hours: int | None, now: datetime) -> str:
    if job.status is JobStatus.EXPIRED or job.closed_at is not None:
        return "the listing is closed or expired"
    if max_age_hours and job.posted_at is not None:
        if job.posted_at < now - timedelta(hours=max_age_hours):
            days = (now - job.posted_at).days
            return f"posted {days} day(s) ago, older than your {max_age_hours}-hour limit"
    return ""


# --------------------------------------------------------------------------------------
# Answers and artifacts
# --------------------------------------------------------------------------------------


def _answers_for_job(
    job: Job,
    profile: CandidateProfile,
    application: Application | None,
    bank: dict[str, SavedAnswer],
) -> tuple[list[ScreeningAnswer], list[str]]:
    """The answers that would be sent, and the questions still open.

    A prepared application's own answers are authoritative. Without one, the standard
    question set is resolved against the profile and the answer bank exactly as
    preparation would, without writing anything. The employer's live form can ask more;
    those are discovered when it is opened and go to the Action inbox.
    """
    answers: list[ScreeningAnswer] = []
    if application is not None:
        for row in application.answers:
            value = row.answer or ""
            answers.append(
                ScreeningAnswer(
                    question=row.question,
                    question_key=row.question_key,
                    answer=mask_value(value) if row.is_sensitive else value[:300],
                    provenance=row.provenance.value,
                    sensitive=row.is_sensitive,
                    source="this application",
                )
            )
        return answers, blocking_questions(application)

    unresolved: list[str] = []
    for prepared in build_question_set(job, profile):
        value = prepared.answer
        provenance = prepared.provenance.value
        source = "your profile" if value else ""
        saved = bank.get(prepared.question_key)
        if not value and saved is not None and (saved.answer or "").strip():
            value, provenance, source = saved.answer, saved.provenance.value, "answer bank"
        sensitive_draft = prepared.is_sensitive and provenance == AnswerProvenance.AI_DRAFT.value
        if not value.strip() or sensitive_draft:
            unresolved.append(prepared.question)
        answers.append(
            ScreeningAnswer(
                question=prepared.question,
                question_key=prepared.question_key,
                answer=mask_value(value) if prepared.is_sensitive else value[:300],
                provenance=provenance,
                sensitive=prepared.is_sensitive,
                source=source or "missing",
            )
        )
    return answers, unresolved


def _resume_label(session: Session, profile_id: int, browser_target: bool) -> str:
    rows = session.scalars(
        select(Resume)
        .where(Resume.profile_id == profile_id)
        .order_by(Resume.is_primary.desc(), Resume.id.desc())
    ).all()
    for row in rows:
        name = row.original_filename or ""
        if browser_target and not name.lower().endswith((".pdf", ".docx", ".doc")):
            continue
        return f"{name} ({row.label}) — your uploaded file, sent unchanged"
    if browser_target:
        return "no PDF or DOCX resume on file — upload one before a live run"
    return "the resume variant chosen at preparation"


# --------------------------------------------------------------------------------------
# The preflight
# --------------------------------------------------------------------------------------


def dispatched_today(session: Session, target_keys: frozenset[str]) -> int:
    start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    count = session.scalar(
        select(func.count(SubmissionAttempt.id)).where(
            SubmissionAttempt.target_key.in_(target_keys),
            SubmissionAttempt.state.in_(
                _DISPATCHED_STATES | {SubmissionState.REQUIRES_USER_ACTION}
            ),
            SubmissionAttempt.finished_at >= start,
        )
    )
    return int(count or 0)


def effective_daily_cap(targets: AutoApplyTargets) -> int | None:
    from app.config import get_settings

    settings = get_settings()
    caps = [settings.browser_daily_submission_cap] if settings.browser_submission_enabled else []
    if targets.daily_cap:
        caps.append(int(targets.daily_cap))
    return min(caps) if caps else None


def run_preflight(
    session: Session,
    profile: CandidateProfile,
    targets: AutoApplyTargets,
    *,
    exclude_run_id: int | None = None,
    breakdown_limit: int = 300,
) -> Preflight:
    """Classify every job in scope and return the itemised plan."""
    from app.submission.registry import BROWSER_TARGET_KEYS, adapter_for_job, target_for_job

    now = utcnow()
    counts = PreflightCounts()
    notes: list[str] = []

    statement = select(Job, JobMatch).outerjoin(
        JobMatch, (JobMatch.job_id == Job.id) & (JobMatch.profile_id == profile.id)
    )
    if targets.sources:
        statement = statement.where(
            Job.id.in_(
                select(JobSourceReference.job_id).where(
                    JobSourceReference.source.in_(targets.sources)
                )
            )
        )
    rows = session.execute(statement).all()
    job_ids = [job.id for job, _ in rows]
    skipped_by_profile = {
        job_id: True
        for job_id in session.scalars(
            select(JobUserState.job_id).where(
                JobUserState.profile_id == profile.id, JobUserState.state == "skipped"
            )
        )
    }

    sources_by_job: dict[int, list[str]] = defaultdict(list)
    for job_id, source in session.execute(
        select(JobSourceReference.job_id, JobSourceReference.source)
    ).all():
        value = source.value if hasattr(source, "value") else str(source)
        if value not in sources_by_job[job_id]:
            sources_by_job[job_id].append(value)

    applications: dict[int, Application] = {}
    for prepared_row in session.scalars(
        select(Application).where(Application.profile_id == profile.id).order_by(Application.id)
    ).all():
        applications[prepared_row.job_id] = prepared_row

    dispatched_jobs: set[int] = set()
    active_elsewhere: dict[int, int] = {}
    seen_by_autoapply: set[int] = set()
    for attempt, run in session.execute(
        select(SubmissionAttempt, AutoApplyRun).join(
            AutoApplyRun, AutoApplyRun.id == SubmissionAttempt.autoapply_run_id
        )
    ).all():
        if run.profile_id != profile.id:
            continue
        seen_by_autoapply.add(attempt.job_id)
        if attempt.state in _DISPATCHED_STATES or (
            attempt.state is SubmissionState.REQUIRES_USER_ACTION
            and attempt.checkpoint in ("submit_requested", "submit_clicked", "outcome_read")
        ):
            dispatched_jobs.add(attempt.job_id)
        elif (
            run.status in _ACTIVE_RUN_STATUSES
            and run.id != exclude_run_id
            and "#retired-" not in (attempt.idempotency_key or "")
            and attempt.state
            not in (SubmissionState.UNSUPPORTED_PLATFORM, SubmissionState.SUBMITTED_CONFIRMED)
        ):
            active_elsewhere[attempt.job_id] = run.id

    bank = {
        entry.question_key: entry
        for entry in session.scalars(
            select(SavedAnswer).where(SavedAnswer.profile_id == profile.id)
        ).all()
    }
    excluded = [
        normalize_company(name)
        for name in [*(targets.excluded_companies or []), *(profile.excluded_companies or [])]
        if name and name.strip()
    ]
    platforms = {key.strip().lower() for key in (targets.platforms or []) if key.strip()}
    families = {family.strip().lower() for family in (targets.role_families or []) if family}
    titles = [title.strip().lower() for title in (targets.titles or []) if title.strip()]
    allowed_confidence = set(confidence_at_least(targets.min_confidence))
    max_age_hours = targets.normalized_age_hours()
    resume_cache: dict[bool, str] = {}

    plans: list[JobPlan] = []
    counts.total_discovered = len(job_ids)
    for job, match in rows:
        target = target_for_job(job)
        adapter = adapter_for_job(job)
        report = adapter.check_capability(job)
        application = applications.get(job.id)
        browser_target = target.key in BROWSER_TARGET_KEYS
        if browser_target not in resume_cache:
            resume_cache[browser_target] = _resume_label(session, profile.id, browser_target)

        plan = JobPlan(
            job_id=job.id,
            title=job.title,
            employer=job.company,
            sources=sources_by_job.get(job.id, []),
            url=job.url or "",
            posted_at=job.posted_at,
            discovered_at=job.discovered_at,
            score=round(match.total_score, 1) if match is not None else None,
            band=match.band if match is not None else "",
            evidence_coverage=match.evidence_coverage if match is not None else None,
            confidence=match.confidence if match is not None else "",
            role_family=infer_job_family(job.title, list(job.required_skills or [])),
            location_fit=_location_fit(
                job, profile, list(targets.locations or []), targets.remote_preference
            ),
            experience_fit=_experience_fit(job, profile, targets.experience_tolerance_years),
            platform=target.key,
            platform_name=target.display_name,
            submission_supported=report.supported,
            capability_reason="" if report.supported else report.reason,
            resume_artifact=resume_cache[browser_target],
            cover_letter_preview=(
                (application.cover_letter or "")[:400]
                if application is not None and application.cover_letter
                else ("drafted at preparation" if targets.include_cover_letter else "none")
            ),
            application_id=application.id if application is not None else None,
        )
        if job.posted_at is None:
            plan.warnings.append("no posting date, so freshness could not be checked")
        if application is None and job.id not in seen_by_autoapply:
            counts.new_jobs += 1

        # ---- exclusions that end the evaluation ----
        if job.status is JobStatus.DUPLICATE or job.duplicate_of_id is not None:
            plan.status = STATUS_DUPLICATE
            plan.blocking_reasons.append(f"duplicate of job {job.duplicate_of_id or '?'}")
            counts.duplicates += 1
            plans.append(plan)
            continue
        handled = _HANDLED_STATUSES.get(application.status) if application is not None else None
        if handled or job.id in dispatched_jobs:
            plan.status = STATUS_APPLIED
            plan.blocking_reasons.append(handled or "an earlier attempt already submitted it")
            counts.previously_applied += 1
            plans.append(plan)
            continue
        if job.status is JobStatus.SKIPPED or skipped_by_profile.get(job.id):
            plan.status = STATUS_BLOCKED
            plan.blocking_reasons.append("you skipped this job")
            counts.blocked_by_constraints += 1
            plans.append(plan)
            continue
        stale = _too_old(job, max_age_hours, now)
        if stale:
            plan.status = STATUS_STALE
            plan.blocking_reasons.append(stale)
            counts.expired_or_stale += 1
            plans.append(plan)
            continue

        # ---- soft thresholds, reported separately from hard constraints ----
        below: list[str] = []
        if match is None:
            below.append("not scored yet")
        else:
            counts.scored += 1
            if match.total_score >= targets.min_score and (
                not targets.bands or match.band in targets.bands
            ):
                counts.meeting_score += 1
            else:
                below.append(
                    f"score {match.total_score:.0f} (band {match.band}) is under your "
                    f"{targets.min_score:.0f} minimum or outside bands {targets.bands}"
                )
            if match.confidence in allowed_confidence:
                counts.meeting_confidence += 1
            else:
                below.append(
                    f"evidence confidence is {match.confidence}, under your "
                    f"'{targets.min_confidence}' minimum"
                )

        # ---- hard constraints: each blocks on its own, whatever the score ----
        hard: list[str] = []
        eligibility: list[str] = []
        if match is not None and match.filtered_out:
            eligibility = list(match.filter_reasons or ["fails an eligibility filter"])
        company_key = job.company_normalized or normalize_company(job.company)
        for name in excluded:
            if name and name in company_key:
                hard.append(f"{job.company} is on your excluded employers list")
                break
        if platforms and target.key not in platforms:
            hard.append(f"{target.display_name} is not one of the platforms you selected")
        if plan.experience_fit.status == "fail":
            hard.append(plan.experience_fit.detail)
        else:
            counts.meeting_experience += 1
        if plan.location_fit.status == "fail":
            hard.append(plan.location_fit.detail)
        else:
            counts.meeting_location += 1
        if families and plan.role_family not in families:
            hard.append(f"role family '{plan.role_family}' is not in {sorted(families)}")
        if titles and not any(title in (job.title or "").lower() for title in titles):
            hard.append("the title matches none of your title keywords")
        if job.id in active_elsewhere:
            hard.append(f"already queued in auto-apply run {active_elsewhere[job.id]}")

        plan.blocking_reasons.extend(eligibility + hard + below)
        if eligibility:
            plan.status = STATUS_INELIGIBLE
            counts.blocked_by_eligibility += 1
        elif hard:
            plan.status = STATUS_BLOCKED
            counts.blocked_by_constraints += 1
        elif below:
            plan.status = STATUS_BELOW_THRESHOLD
        if plan.blocking_reasons:
            plans.append(plan)
            continue

        # ---- in scope: what would happen to it ----
        plan.queued = True
        plan.screening_answers, plan.unresolved_questions = _answers_for_job(
            job, profile, application, bank
        )
        if not report.supported:
            plan.status = STATUS_UNSUPPORTED
            counts.unsupported_platform += 1
        elif plan.unresolved_questions:
            plan.status = STATUS_NEEDS_ANSWERS
            counts.missing_answers += 1
            plan.warnings.append(
                f"{len(plan.unresolved_questions)} question(s) need your answer first; the "
                "application is prepared and waits in the Action inbox"
            )
        else:
            plan.status = STATUS_READY
            plan.planned = True
            counts.ready += 1
            if browser_target:
                plan.warnings.append(
                    "the employer's form can ask questions the listing does not; any without "
                    "an answer stop this job and go to your Action inbox"
                )
        plans.append(plan)

    queued = sorted(
        (plan for plan in plans if plan.queued),
        key=lambda plan: (-(plan.score or 0.0), plan.job_id),
    )
    budget = max(1, targets.max_submissions)
    if len(queued) > budget:
        notes.append(
            f"{len(queued)} jobs qualify; the run covers the top {budget} by score "
            "(raise the submission limit to include more)"
        )
        for plan in queued[budget:]:
            plan.queued = False
            plan.planned = False
            plan.warnings.append("outside this run's submission limit")
        queued = queued[:budget]

    if targets.approved_job_ids:
        approved = set(targets.approved_job_ids)
        for plan in queued:
            if plan.job_id not in approved:
                plan.queued = False
                plan.planned = False
                plan.warnings.append("not in the list you approved")
        dropped = approved - {plan.job_id for plan in queued}
        if dropped:
            notes.append(
                f"{len(dropped)} approved job(s) no longer qualify and will not be sent: "
                + ", ".join(str(job_id) for job_id in sorted(dropped)[:20])
            )
        queued = [plan for plan in queued if plan.queued]

    counts.queued = len(queued)
    planned = [plan for plan in queued if plan.planned]
    cap = effective_daily_cap(targets)
    counts.daily_cap = cap
    if cap is not None:
        counts.dispatched_today = dispatched_today(session, BROWSER_TARGET_KEYS)
        counts.daily_cap_remaining = max(0, cap - counts.dispatched_today)
    limit = len(planned)
    if counts.daily_cap_remaining is not None:
        limit = min(limit, counts.daily_cap_remaining)
        if counts.daily_cap_remaining < len(planned):
            notes.append(
                f"today's cap leaves room for {counts.daily_cap_remaining} more submission(s); "
                "the rest stay prepared for a later run"
            )
    counts.planned_attempts = 0 if targets.dry_run else limit
    if targets.dry_run:
        notes.append("dry run: forms are filled and screenshotted, nothing is submitted")

    order = {
        STATUS_READY: 0,
        STATUS_NEEDS_ANSWERS: 1,
        STATUS_UNSUPPORTED: 2,
        STATUS_BLOCKED: 3,
        STATUS_INELIGIBLE: 4,
        STATUS_BELOW_THRESHOLD: 5,
        STATUS_STALE: 6,
        STATUS_APPLIED: 7,
        STATUS_DUPLICATE: 8,
    }
    plans.sort(key=lambda plan: (order.get(plan.status, 9), -(plan.score or 0.0), plan.job_id))
    if len(plans) > breakdown_limit:
        notes.append(f"showing the first {breakdown_limit} of {len(plans)} jobs")
    return Preflight(
        counts=counts,
        jobs=plans[:breakdown_limit],
        queue_job_ids=[plan.job_id for plan in queued],
        notes=notes,
        generated_at=now,
    )


__all__ = [
    "REMOTE_PREFERENCES",
    "Fit",
    "JobPlan",
    "Preflight",
    "PreflightCounts",
    "ScreeningAnswer",
    "dispatched_today",
    "effective_daily_cap",
    "run_preflight",
]
