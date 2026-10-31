"""Source configuration, diagnostics, metrics and audit endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AppSettings, Authorized, DbSession, Profile
from app.api.errors import ApiError
from app.db.models import SourceConfiguration, SourceName
from app.db.repositories import (
    AuditRepository,
    ImportRunRepository,
    SourceConfigRepository,
)
from app.schemas.common import Page
from app.schemas.source import (
    Capabilities,
    DiagnosticEntry,
    Diagnostics,
    DuplicationReportRead,
    EstimatedMetrics,
    FalseMergeSuspectRead,
    MissedMergeSuspectRead,
    NormalizationCollisionRead,
    OperationalMetrics,
    SourceRead,
    SourceUpdate,
)
from app.services.duplication import analyse_duplication
from app.services.metrics import estimated_metrics, operational_metrics
from app.sources import (
    all_adapters,
    default_configuration,
    effective_capabilities,
    get_adapter,
    unsupported_requests,
)

router = APIRouter(prefix="/api", tags=["sources"], dependencies=[Authorized])


def _ensure_configs(session, settings) -> dict[SourceName, SourceConfiguration]:
    """Seed any missing configuration row from its adapter's declared capabilities."""
    repository = SourceConfigRepository(session)
    existing = {config.source: config for config in repository.list_all()}
    for adapter in all_adapters(settings):
        if adapter.source not in existing:
            existing[adapter.source] = repository.create(default_configuration(adapter))
    return existing


def _to_read(adapter, config, settings) -> SourceRead:
    effective = effective_capabilities(adapter, config)
    healthy, reason = adapter.health()
    return SourceRead(
        source=adapter.source,
        display_name=adapter.display_name,
        enabled=bool(config.enabled),
        capabilities=Capabilities(**adapter.capabilities.as_dict()),
        effective_capabilities=Capabilities(**effective.as_dict()),
        rate_limit_per_hour=config.rate_limit_per_hour,
        last_run_at=config.last_run_at,
        last_error=config.last_error,
        consecutive_failures=config.consecutive_failures,
        policy_basis=adapter.policy_basis,
        limitations=list(adapter.limitations),
        status_detail=reason if healthy else f"Not usable: {reason}",
    )


@router.get("/sources", response_model=list[SourceRead], summary="List sources and capabilities")
def list_sources(session: DbSession, settings: AppSettings) -> list[SourceRead]:
    configs = _ensure_configs(session, settings)
    return [
        _to_read(adapter, configs[adapter.source], settings) for adapter in all_adapters(settings)
    ]


@router.patch(
    "/sources/{source}",
    response_model=SourceRead,
    summary="Narrow a source's settings (a capability can never be widened)",
)
def update_source(
    source: SourceName, payload: SourceUpdate, session: DbSession, settings: AppSettings
) -> SourceRead:
    """Update a source's configuration.

    A request to enable something the adapter does not declare is rejected with the policy
    reason, rather than accepted and silently ignored.
    """
    try:
        adapter = get_adapter(source, settings)
    except KeyError as exc:
        raise ApiError(
            "not_found", f"unknown source '{source}'", status.HTTP_404_NOT_FOUND
        ) from exc

    configs = _ensure_configs(session, settings)
    config = configs[source]

    requested = {
        name: value
        for name, value in (
            ("manual_import_enabled", payload.manual_import_enabled),
            ("authorized_discovery_enabled", payload.authorized_discovery_enabled),
            ("browser_assistance_enabled", payload.browser_assistance_enabled),
        )
        if value is not None
    }
    problems = unsupported_requests(adapter, requested)
    if problems:
        raise ApiError(
            "capability_not_available", " ".join(problems), status.HTTP_422_UNPROCESSABLE_ENTITY
        )

    changes = {
        name: value
        for name, value in payload.model_dump(exclude_unset=True).items()
        if value is not None
    }
    SourceConfigRepository(session).update(config, changes)
    AuditRepository(session).record(
        "source.updated",
        entity_type="source_configuration",
        entity_id=config.id,
        detail={"source": source.value, "changes": changes},
    )
    return _to_read(adapter, config, settings)


@router.get(
    "/diagnostics",
    response_model=Diagnostics,
    summary="Explain why each source is or is not returning jobs",
)
def diagnostics(session: DbSession, settings: AppSettings) -> Diagnostics:
    configs = _ensure_configs(session, settings)
    runs = ImportRunRepository(session)
    entries: list[DiagnosticEntry] = []

    for adapter in all_adapters(settings):
        config = configs[adapter.source]
        healthy, reason = adapter.health()
        recent = runs.list_recent(limit=1, source=adapter.source)
        last_run = recent[0] if recent else None

        if not config.enabled:
            healthy, reason = False, "You have disabled this source on the Settings page."
        elif not adapter.capabilities.authorized_discovery_enabled:
            reason = "No automated discovery: " + adapter.policy_basis + " Import a file instead."
        elif last_run is not None and last_run.status.value == "failed":
            healthy = False
            reason = f"The last run failed: {last_run.message or 'no detail recorded'}"

        entries.append(
            DiagnosticEntry(
                source=adapter.source,
                display_name=adapter.display_name,
                healthy=healthy,
                reason=reason,
                detail=(
                    f"last run {last_run.status.value} at {last_run.started_at.isoformat()}"
                    if last_run
                    else "this source has never run"
                ),
                last_run_at=config.last_run_at,
                jobs_last_run=last_run.jobs_created if last_run else None,
            )
        )

    return Diagnostics(
        entries=entries,
        llm_provider=settings.llm_provider,
        llm_enabled=settings.llm_enabled,
        scheduler_enabled=settings.scheduler_enabled,
        database_dialect=session.get_bind().dialect.name,
        api_bound_to_loopback=settings.is_loopback_only,
        display_timezone=settings.display_timezone,
    )


@router.get("/metrics", response_model=OperationalMetrics, summary="Counted operational metrics")
def metrics(session: DbSession, profile: Profile) -> OperationalMetrics:
    return operational_metrics(session, profile.id)


@router.get(
    "/metrics/estimated",
    response_model=EstimatedMetrics,
    summary="Estimated metrics, labelled as estimates",
)
def estimated(session: DbSession, profile: Profile) -> EstimatedMetrics:
    counted = operational_metrics(session, profile.id)
    return estimated_metrics(counted.applications_prepared)


@router.get(
    "/metrics/duplication",
    response_model=DuplicationReportRead,
    summary="Cross-source duplication rates and merge suspects",
)
def duplication(
    session: DbSession,
    suspect_limit: Annotated[int, Query(ge=1, le=200)] = 25,
) -> DuplicationReportRead:
    report = analyse_duplication(session, suspect_limit=suspect_limit)
    return DuplicationReportRead(
        jobs_total=report.jobs_total,
        sightings_total=report.sightings_total,
        merged_sightings=report.merged_sightings,
        duplicate_rate=report.duplicate_rate,
        exact_duplicate_sightings=report.exact_duplicate_sightings,
        fuzzy_duplicate_sightings=report.fuzzy_duplicate_sightings,
        sightings_by_rule=report.sightings_by_rule,
        multi_source_jobs=report.multi_source_jobs,
        cross_source_duplicate_rate=report.cross_source_duplicate_rate,
        sources_seen=report.sources_seen,
        source_pair_overlaps=report.source_pair_overlaps,
        jobs_with_application=report.jobs_with_application,
        multi_source_jobs_with_application=report.multi_source_jobs_with_application,
        missed_merge_suspects=[
            MissedMergeSuspectRead(
                job_ids=list(suspect.job_ids),
                titles=list(suspect.titles),
                company=suspect.company,
                sources=list(suspect.sources),
                title_overlap=suspect.title_overlap,
                reason=suspect.reason,
            )
            for suspect in report.missed_merge_suspects
        ],
        false_merge_suspects=[
            FalseMergeSuspectRead(
                job_id=suspect.job_id,
                stored_title=suspect.stored_title,
                observed_titles=list(suspect.observed_titles),
                observed_companies=list(suspect.observed_companies),
                sources=list(suspect.sources),
                title_overlap=suspect.title_overlap,
                reason=suspect.reason,
            )
            for suspect in report.false_merge_suspects
        ],
        normalization_collisions=[
            NormalizationCollisionRead(
                normalized_company=collision.normalized_company,
                raw_companies=list(collision.raw_companies),
                job_count=collision.job_count,
            )
            for collision in report.normalization_collisions
        ],
        buckets_skipped=report.buckets_skipped,
        is_healthy=report.is_healthy,
    )


@router.get("/import-runs", response_model=Page[dict], summary="Import and discovery history")
def import_runs(
    session: DbSession,
    source: Annotated[SourceName | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
) -> Page[dict]:
    runs = ImportRunRepository(session).list_recent(limit=limit, source=source)
    items = [
        {
            "id": run.id,
            "source": run.source.value,
            "trigger": run.trigger,
            "status": run.status.value,
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "records_received": run.records_received,
            "records_invalid": run.records_invalid,
            "jobs_created": run.jobs_created,
            "jobs_updated": run.jobs_updated,
            "duplicates_detected": run.duplicates_detected,
            "message": run.message,
            "errors": run.errors[:10],
        }
        for run in runs
    ]
    return Page(items=items, total=len(items), limit=limit, offset=0)


@router.get("/audit-logs", response_model=Page[dict], summary="Read the audit trail")
def audit_logs(
    session: DbSession,
    action: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[dict]:
    repository = AuditRepository(session)
    entries = repository.list_recent(limit=limit, offset=offset, action=action)
    return Page(
        items=[
            {
                "id": entry.id,
                "action": entry.action,
                "entity_type": entry.entity_type,
                "entity_id": entry.entity_id,
                "actor": entry.actor,
                "detail": entry.detail,
                "created_at": entry.created_at.isoformat(),
            }
            for entry in entries
        ],
        total=repository.count(action=action),
        limit=limit,
        offset=offset,
    )
