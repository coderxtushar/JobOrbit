"""Auto-apply endpoints.

One click authorises a whole run inside its configured scope: discover, filter, rank,
prepare, dispatch where a provider permits dispatch, verify, record. ``POST /runs`` is that
click.

Two things are deliberately true of this router. It has no route whose name or path
promises a submission, because the submission happens inside a run whose scope the user set
and whose outcome is reported per attempt. And ``GET /capabilities`` reads every provider's
own capability report, so the honest answer to "can you submit to LinkedIn" is served from
the adapter rather than from prose that could drift.

In a default installation ``confirmed_count`` is zero on every run, because no real
platform authorises candidate submission. That is the product being accurate, not a
failure, and the response says so in ``message``.
"""

from __future__ import annotations

import threading
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import FileResponse

from app.api.deps import AppSettings, Authorized, DbSession, Llm, Profile, refuse_in_demo_mode
from app.api.errors import ApiError
from app.db.models import AutoApplyRun, CandidateProfile, SubmissionAttempt, SubmissionState
from app.logging_conf import get_logger
from app.schemas.autoapply import (
    AutoApplyRunRead,
    AutoApplyTargetsIn,
    BreakerRead,
    ControlStatusRead,
    EmergencyStopIn,
    PlatformSubmissionRead,
    PreflightRead,
    ResolveAttemptIn,
    RunPreviewRead,
    SubmissionAttemptDetail,
    SubmissionCapabilitiesRead,
    TargetBreakdown,
)
from app.schemas.common import Page
from app.services import autoapply_control as control
from app.services.autoapply import AutoApplyService, AutoApplyTargets, preview, signal_all_runs
from app.services.autoapply_control import is_emergency_stopped
from app.services.preflight import dispatched_today, effective_daily_cap, run_preflight
from app.submission import all_submission_adapters, get_submission_adapter, supported_targets
from app.submission.states import counts_as_sent

router = APIRouter(prefix="/api/autoapply", tags=["autoapply"], dependencies=[Authorized])

logger = get_logger(__name__)

_NO_REAL_PLATFORM_NOTE = (
    "No job platform in scope publishes an authorized candidate-side submission "
    "interface, so submission is unavailable for every real provider and each one reports "
    "its own reason. Applications are prepared in full and the employer's page is opened "
    "for you."
)


def _targets(payload: AutoApplyTargetsIn) -> AutoApplyTargets:
    return AutoApplyTargets(
        sources=list(payload.sources),
        max_discover=payload.max_discover,
        max_submissions=payload.max_submissions,
        max_age_hours=payload.max_age_hours,
        min_score=payload.min_score,
        min_confidence=payload.min_confidence,
        bands=list(payload.bands),
        titles=list(payload.titles),
        excluded_companies=list(payload.excluded_companies),
        concurrency=payload.concurrency,
        max_attempts=payload.max_attempts,
        dry_run=payload.dry_run,
        include_cover_letter=payload.include_cover_letter,
        role_families=list(payload.role_families),
        locations=list(payload.locations),
        remote_preference=payload.remote_preference,
        experience_tolerance_years=payload.experience_tolerance_years,
        daily_cap=payload.daily_cap,
        platforms=[key.strip().lower() for key in payload.platforms if key.strip()],
        approved_job_ids=list(payload.approved_job_ids),
    )


@router.get(
    "/capabilities",
    response_model=SubmissionCapabilitiesRead,
    summary="What each provider permits, read from its own adapter",
)
def submission_capabilities() -> SubmissionCapabilitiesRead:
    rows: list[PlatformSubmissionRead] = []
    from app.db.models import Job

    probe = Job(title="", company="", url="")
    for adapter in all_submission_adapters():
        report = adapter.check_capability(probe)
        rows.append(
            PlatformSubmissionRead(
                key=adapter.target.key,
                display_name=adapter.target.display_name,
                submission_supported=report.supported,
                reason=report.reason,
                credential_owner=report.credential_owner.value,
                documented_api=report.documented_api,
                browser_submission_permitted=report.browser_submission_permitted,
                manual_completion_required=report.manual_completion_required,
                evidence_url=report.evidence_url,
                evidence_quote=report.evidence_quote,
            )
        )
    return SubmissionCapabilitiesRead(
        supported_targets=sorted(supported_targets()),
        platforms=sorted(rows, key=lambda row: row.display_name),
        note=_NO_REAL_PLATFORM_NOTE,
    )


@router.post(
    "/preview",
    response_model=RunPreviewRead,
    summary="Count what a run would cover, without contacting any provider",
)
def preview_run(
    payload: AutoApplyTargetsIn, session: DbSession, profile: Profile
) -> RunPreviewRead:
    plan = preview(session, profile, _targets(payload))
    breakdown: list[TargetBreakdown] = []
    for key, count in sorted(plan.by_target.items(), key=lambda item: -item[1]):
        adapter = get_submission_adapter(key)
        breakdown.append(
            TargetBreakdown(
                key=key,
                display_name=adapter.target.display_name,
                eligible=count,
                submission_supported=key in supported_targets(),
                reason=plan.unsupported_reasons.get(key, ""),
            )
        )
    note = (
        f"{plan.eligible} job(s) match this scope. {plan.submittable} can be submitted "
        "programmatically; the rest are prepared for you to send yourself."
    )
    return RunPreviewRead(
        eligible=plan.eligible,
        submittable=plan.submittable,
        targets=breakdown,
        note=note,
    )


@router.post(
    "/runs",
    response_model=AutoApplyRunRead,
    status_code=status.HTTP_201_CREATED,
    summary="Authorise one run over everything in scope",
)
def start_run(
    payload: AutoApplyTargetsIn,
    session: DbSession,
    profile: Profile,
    provider: Llm,
    settings: AppSettings,
    run_in_background: Annotated[bool, Query()] = False,
) -> AutoApplyRunRead:
    """Create a run and execute it.

    ``dry_run`` defaults to true, so the default behaviour of this endpoint is to prepare
    everything and dispatch nothing.
    """
    refuse_in_demo_mode(settings, "autoapply_run")
    if is_emergency_stopped(session):
        raise ApiError(
            "emergency_stop_active",
            "The emergency stop is on. Clear it on the Auto-apply page before starting a run.",
            status.HTTP_409_CONFLICT,
        )
    targets = _targets(payload)
    profile.autoapply_preferences = {
        key: value for key, value in targets.as_dict().items() if key != "approved_job_ids"
    }
    service = AutoApplyService(provider=provider)
    run = service.create_run(session, profile, targets)
    session.flush()
    run_id = run.id

    if run_in_background:
        # Committed first, so the worker's own session can see the run it is given.
        session.commit()
        thread = threading.Thread(
            target=_execute_quietly,
            args=(run_id, targets),
            name=f"joborbit-autoapply-{run_id}",
            daemon=True,
        )
        thread.start()
        return _read(run)

    session.commit()
    service.execute(run_id, targets)
    refreshed = session.get(AutoApplyRun, run_id)
    if refreshed is None:
        raise ApiError("not_found", f"run {run_id} disappeared", status.HTTP_404_NOT_FOUND)
    session.refresh(refreshed)
    return _read(refreshed)


def _execute_quietly(run_id: int, targets: AutoApplyTargets) -> None:
    try:
        AutoApplyService().execute(run_id, targets)
    except Exception:  # noqa: BLE001 - a worker thread must not take the process down
        logger.exception("autoapply_run_failed", extra={"run_id": run_id})


@router.get("", response_model=Page[AutoApplyRunRead], summary="List auto-apply runs")
def list_runs(
    session: DbSession,
    profile: Profile,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AutoApplyRunRead]:
    from sqlalchemy import func, select

    mine = AutoApplyRun.profile_id == profile.id
    total = int(session.scalar(select(func.count(AutoApplyRun.id)).where(mine)) or 0)
    rows = session.scalars(
        select(AutoApplyRun)
        .where(mine)
        .order_by(AutoApplyRun.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return Page[AutoApplyRunRead](
        items=[_read(row) for row in rows], total=total, limit=limit, offset=offset
    )


@router.get("/runs/{run_id}", response_model=AutoApplyRunRead, summary="One run with its attempts")
def get_run(run_id: int, session: DbSession, profile: Profile) -> AutoApplyRunRead:
    return _read(_require(session, run_id, profile))


@router.post("/runs/{run_id}/pause", response_model=AutoApplyRunRead, summary="Pause a run")
def pause_run(run_id: int, session: DbSession, provider: Llm, profile: Profile) -> AutoApplyRunRead:
    run = _require(session, run_id, profile)
    AutoApplyService(provider=provider).request_pause(session, run_id)
    session.flush()
    session.refresh(run)
    return _read(run)


@router.post("/runs/{run_id}/resume", response_model=AutoApplyRunRead, summary="Resume a run")
def resume_run(
    run_id: int,
    session: DbSession,
    provider: Llm,
    settings: AppSettings,
    profile: Profile,
    run_in_background: Annotated[bool, Query()] = False,
) -> AutoApplyRunRead:
    refuse_in_demo_mode(settings, "autoapply_resume")
    run = _require(session, run_id, profile)
    if is_emergency_stopped(session):
        raise ApiError(
            "emergency_stop_active",
            "The emergency stop is on. Clear it before resuming a run.",
            status.HTTP_409_CONFLICT,
        )
    service = AutoApplyService(provider=provider)
    service.resume(session, run_id)
    session.commit()
    targets = _targets_from_row(run)
    if run_in_background:
        threading.Thread(
            target=_execute_quietly,
            args=(run_id, targets),
            name=f"joborbit-autoapply-{run_id}",
            daemon=True,
        ).start()
        return _read(run)
    service.execute(run_id, targets)
    refreshed = _require(session, run_id, profile)
    session.refresh(refreshed)
    return _read(refreshed)


@router.post("/runs/{run_id}/cancel", response_model=AutoApplyRunRead, summary="Stop a run")
def cancel_run(
    run_id: int, session: DbSession, provider: Llm, profile: Profile
) -> AutoApplyRunRead:
    run = _require(session, run_id, profile)
    AutoApplyService(provider=provider).request_cancel(session, run_id)
    session.flush()
    session.refresh(run)
    return _read(run)


@router.get(
    "/runs/{run_id}/report",
    response_class=Response,
    summary="Plain-text report for one run",
)
def run_report(run_id: int, session: DbSession, profile: Profile) -> Response:
    run = _require(session, run_id, profile)
    lines = [
        f"JobOrbit auto-apply run {run.id}",
        f"started    {run.started_at.isoformat()}",
        f"finished   {run.finished_at.isoformat() if run.finished_at else '(still running)'}",
        f"status     {run.status.value}",
        f"dry run    {run.dry_run}",
        "",
        f"eligible                 {run.eligible_count}",
        f"prepared                 {run.prepared_count}",
        f"confirmed submissions    {run.confirmed_count}",
        f"waiting on your answer   {run.blocked_count}",
        f"needs you to act         {run.needs_user_count}",
        f"platform permits none    {run.unsupported_count}",
        f"failed                   {run.failed_count}",
        f"outcome unverified       {run.unknown_count}",
        "",
        "Attempts",
    ]
    for attempt in sorted(run.attempts, key=lambda a: a.id):
        sent = "SENT" if counts_as_sent(attempt.state) else "    "
        confirmation = attempt.confirmation_id or "-"
        lines.append(
            f"  {sent} job {attempt.job_id:>6}  {attempt.target_key:<16} "
            f"{attempt.state.value:<24} {confirmation:<14} {attempt.detail[:80]}"
        )
    lines += ["", _NO_REAL_PLATFORM_NOTE]
    return Response(
        content="\n".join(lines) + "\n",
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="autoapply-run-{run.id}.txt"'},
    )


def _require(session: DbSession, run_id: int, profile: CandidateProfile) -> AutoApplyRun:
    """The run, if it belongs to this profile; another person's run is "not found"."""
    run = session.get(AutoApplyRun, run_id)
    if run is None or run.profile_id != profile.id:
        raise ApiError("not_found", f"no auto-apply run {run_id}", status.HTTP_404_NOT_FOUND)
    return run


def _targets_from_row(run: AutoApplyRun) -> AutoApplyTargets:
    """Rebuild the run's scope from the stored blob, so a resume honours the original scope.

    The blob goes back through the same request model that created it, which both validates
    persisted data before it is acted on and drops a key that no longer exists — otherwise
    a field removed from the schema would raise on every resume of an older run.
    """
    stored = {
        key: value
        for key, value in (run.targets or {}).items()
        if key in AutoApplyTargetsIn.model_fields
    }
    return _targets(AutoApplyTargetsIn.model_validate(stored))


def _read(run: AutoApplyRun) -> AutoApplyRunRead:
    return AutoApplyRunRead.model_validate(run)


# --------------------------------------------------------------------------------------
# Preflight
# --------------------------------------------------------------------------------------


@router.post(
    "/preflight",
    response_model=PreflightRead,
    summary="Itemised plan for a run: every job, every constraint, nothing sent",
)
def preflight_run(
    payload: AutoApplyTargetsIn, session: DbSession, profile: Profile
) -> PreflightRead:
    """The batch preview the user approves. Read-only: no provider is contacted."""
    plan = run_preflight(session, profile, _targets(payload))
    from dataclasses import asdict

    return PreflightRead.model_validate(
        {
            "counts": asdict(plan.counts),
            "jobs": [asdict(job) for job in plan.jobs],
            "queue_job_ids": plan.queue_job_ids,
            "notes": plan.notes,
            "generated_at": plan.generated_at,
            "emergency_stop": is_emergency_stopped(session),
        }
    )


@router.get(
    "/preferences",
    response_model=AutoApplyTargetsIn,
    summary="The scope last authorised, as the starting point for the next preflight",
)
def read_preferences(profile: Profile) -> AutoApplyTargetsIn:
    stored = {
        key: value
        for key, value in (profile.autoapply_preferences or {}).items()
        if key in AutoApplyTargetsIn.model_fields and key != "approved_job_ids"
    }
    try:
        return AutoApplyTargetsIn.model_validate(stored)
    except ValueError:
        return AutoApplyTargetsIn()


@router.put("/preferences", response_model=AutoApplyTargetsIn, summary="Save the run scope")
def save_preferences(payload: AutoApplyTargetsIn, profile: Profile) -> AutoApplyTargetsIn:
    data = payload.model_dump(mode="json")
    data.pop("approved_job_ids", None)
    profile.autoapply_preferences = data
    return payload


# --------------------------------------------------------------------------------------
# Safety controls
# --------------------------------------------------------------------------------------


@router.get("/control", response_model=ControlStatusRead, summary="Emergency stop and breakers")
def control_status(session: DbSession, settings: AppSettings) -> ControlStatusRead:
    from app.submission.registry import BROWSER_TARGET_KEYS

    stop = control.emergency_stop_state(session) or {}
    return ControlStatusRead(
        emergency_stop=bool(stop),
        emergency_stop_reason=str(stop.get("reason") or ""),
        emergency_stop_at=str(stop.get("at") or ""),
        breakers=[BreakerRead(**state.as_dict()) for state in control.all_breakers(session)],
        daily_cap=effective_daily_cap(AutoApplyTargets()),
        dispatched_today=dispatched_today(session, BROWSER_TARGET_KEYS),
        browser_submission_enabled=settings.browser_submission_enabled,
        evidence_retention_days=settings.evidence_retention_days,
    )


@router.post(
    "/emergency-stop",
    response_model=ControlStatusRead,
    summary="Stop every run now and refuse new ones until cleared",
)
def emergency_stop(
    payload: EmergencyStopIn, session: DbSession, settings: AppSettings
) -> ControlStatusRead:
    """Cancels every active run. A run between browser steps stops before pressing Submit;
    one already past Submit records an unknown outcome rather than a guess."""
    refuse_in_demo_mode(settings, "autoapply_control")
    control.engage_emergency_stop(session, payload.reason or "stopped from the dashboard")
    session.commit()
    signal_all_runs()
    return control_status(session, settings)


@router.post("/emergency-stop/clear", response_model=ControlStatusRead, summary="Allow runs again")
def clear_emergency_stop(session: DbSession, settings: AppSettings) -> ControlStatusRead:
    refuse_in_demo_mode(settings, "autoapply_control")
    control.clear_emergency_stop(session)
    return control_status(session, settings)


@router.post(
    "/circuits/{target}/reset",
    response_model=ControlStatusRead,
    summary="Close a platform's circuit breaker",
)
def reset_circuit(target: str, session: DbSession, settings: AppSettings) -> ControlStatusRead:
    refuse_in_demo_mode(settings, "autoapply_control")
    control.reset_breaker(session, target.strip().lower()[:60])
    return control_status(session, settings)


@router.post(
    "/evidence/cleanup",
    summary="Delete screenshots, staged uploads and events past their retention period",
)
def cleanup_evidence(session: DbSession, settings: AppSettings) -> dict[str, int]:
    refuse_in_demo_mode(settings, "autoapply_control")
    report = control.cleanup_evidence(
        session, data_dir=settings.data_dir, retention_days=settings.evidence_retention_days
    )
    return report.as_dict()


# --------------------------------------------------------------------------------------
# Attempts: timeline, evidence, and settling an unclear outcome
# --------------------------------------------------------------------------------------


def _require_attempt(
    session: DbSession, attempt_id: int, profile: CandidateProfile
) -> SubmissionAttempt:
    attempt = session.get(SubmissionAttempt, attempt_id)
    run = session.get(AutoApplyRun, attempt.autoapply_run_id) if attempt is not None else None
    if attempt is None or run is None or run.profile_id != profile.id:
        raise ApiError("not_found", f"no attempt {attempt_id}", status.HTTP_404_NOT_FOUND)
    return attempt


@router.get(
    "/attempts/{attempt_id}",
    response_model=SubmissionAttemptDetail,
    summary="One attempt with its answers, artifacts and event timeline",
)
def get_attempt(attempt_id: int, session: DbSession, profile: Profile) -> SubmissionAttemptDetail:
    return SubmissionAttemptDetail.model_validate(_require_attempt(session, attempt_id, profile))


@router.get(
    "/attempts/{attempt_id}/evidence",
    response_class=FileResponse,
    summary="The attempt's screenshot (authorised, never a public URL)",
)
def attempt_evidence(
    attempt_id: int, session: DbSession, settings: AppSettings, profile: Profile
) -> FileResponse:
    refuse_in_demo_mode(settings, "autoapply_control")
    path = control.evidence_file(_require_attempt(session, attempt_id, profile), settings.data_dir)
    if path is None:
        raise ApiError(
            "not_found",
            "no screenshot is kept for this attempt (none was taken, or it passed retention)",
            status.HTTP_404_NOT_FOUND,
        )
    return FileResponse(
        path,
        media_type="image/png",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post(
    "/attempts/{attempt_id}/recheck",
    response_model=SubmissionAttemptDetail,
    summary="Look again for confirmation of an unclear outcome, without resubmitting",
)
def recheck_attempt(
    attempt_id: int, session: DbSession, settings: AppSettings, profile: Profile
) -> SubmissionAttemptDetail:
    """Re-reads the tab left open after the attempt, and any confirmation email already
    linked to the application. Never presses Submit again."""
    refuse_in_demo_mode(settings, "autoapply_control")
    attempt = _require_attempt(session, attempt_id, profile)
    if attempt.state not in (SubmissionState.OUTCOME_UNKNOWN, SubmissionState.REQUIRES_USER_ACTION):
        raise ApiError(
            "not_unclear",
            f"attempt {attempt_id} is {attempt.state.value}; only unclear outcomes are rechecked",
            status.HTTP_409_CONFLICT,
        )
    from app.services.autoapply_resolution import recheck

    recheck(session, attempt)
    session.flush()
    return SubmissionAttemptDetail.model_validate(attempt)


@router.post(
    "/attempts/{attempt_id}/resolve",
    response_model=SubmissionAttemptDetail,
    summary="Record what you found when you checked an unclear outcome yourself",
)
def resolve_attempt(
    attempt_id: int,
    payload: ResolveAttemptIn,
    session: DbSession,
    settings: AppSettings,
    profile: Profile,
) -> SubmissionAttemptDetail:
    refuse_in_demo_mode(settings, "autoapply_control")
    attempt = _require_attempt(session, attempt_id, profile)
    from app.services.autoapply_resolution import ResolutionError, resolve

    try:
        resolve(session, attempt, outcome=payload.outcome, evidence=payload.evidence)
    except ResolutionError as error:
        raise ApiError("cannot_resolve", str(error), status.HTTP_409_CONFLICT) from error
    session.flush()
    return SubmissionAttemptDetail.model_validate(attempt)
