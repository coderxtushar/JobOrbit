"""Platform assistant endpoints.

Everything here is derived: capabilities from the adapters, counts from the database. The
route never stores a capability or a total of its own, so a platform section cannot claim
support the adapter has not documented.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import AppSettings, Authorized, DbSession
from app.api.errors import ApiError
from app.db.models import SourceName
from app.db.repositories import ApplicationRepository, JobRepository, SourceConfigRepository
from app.schemas.platform import (
    PlatformActionRead,
    PlatformDetail,
    PlatformSourceRead,
    PlatformSummary,
)
from app.schemas.source import Capabilities
from app.services.platforms import PLATFORMS, get_platform
from app.sources import default_configuration, effective_capabilities, get_adapter

router = APIRouter(prefix="/api/platforms", tags=["platforms"], dependencies=[Authorized])


def _actions(
    *, discovery: bool, browser_assistance: bool, import_enabled: bool
) -> list[PlatformActionRead]:
    """The user-facing actions a platform supports, derived from its capabilities.

    ``available=False`` entries are returned rather than omitted: a visitor needs to see
    that automated discovery exists as a concept and is *not* available here, which is the
    difference between an honest limitation and a missing feature.
    """
    return [
        PlatformActionRead(
            key="import_url",
            label="Add a saved job by URL",
            description="Paste a listing you found yourself. Nothing is fetched on your behalf.",
            available=import_enabled,
        ),
        PlatformActionRead(
            key="import_file",
            label="Import a CSV or JSON export",
            description="Bring a batch of listings you exported from the platform.",
            available=import_enabled,
        ),
        PlatformActionRead(
            key="automated_discovery",
            label="Fetch new jobs automatically",
            description=(
                "Only where the platform publishes an interface for it. Needs a company "
                "board or feed configured."
                if discovery
                else "Not available: this platform publishes no jobseeker search API and "
                "its terms prohibit automated access."
            ),
            available=discovery,
        ),
        PlatformActionRead(
            key="open_in_platform",
            label="Open the listing on the platform",
            description="Opens the employer's or platform's own page so you apply there.",
            available=browser_assistance,
        ),
        PlatformActionRead(
            key="prepare_application",
            label="Prepare an application for review",
            description=(
                "Selects a resume variant, drafts a cover letter and fills answers from "
                "your verified profile. You review and submit it yourself."
            ),
            available=True,
        ),
        PlatformActionRead(
            key="automated_submission",
            label="Submit the application for you",
            description=(
                "Never available on any platform. No endpoint, no code path and no button "
                "exists, and the database refuses to record the capability."
            ),
            available=False,
        ),
    ]


@router.get("", response_model=list[PlatformSummary], summary="List platform assistants")
def list_platforms(session: DbSession, settings: AppSettings) -> list[PlatformSummary]:
    job_counts = JobRepository(session).counts_by_source()
    app_counts = ApplicationRepository(session).counts_by_source()
    configs = {config.source: config for config in SourceConfigRepository(session).list_all()}

    summaries: list[PlatformSummary] = []
    for platform in PLATFORMS:
        discovery_sources = 0
        for source in platform.sources:
            adapter = get_adapter(source, settings)
            config = configs.get(source) or default_configuration(adapter)
            if effective_capabilities(adapter, config).authorized_discovery_enabled:
                discovery_sources += 1
        summaries.append(
            PlatformSummary(
                key=platform.key,
                display_name=platform.display_name,
                tagline=platform.tagline,
                homepage=platform.homepage,
                how_jobs_arrive=platform.how_jobs_arrive,
                notes=list(platform.notes),
                source_count=len(platform.sources),
                discovery_source_count=discovery_sources,
                jobs_stored=sum(job_counts.get(s.value, 0) for s in platform.sources),
                applications=sum(app_counts.get(s.value, 0) for s in platform.sources),
                supports_automated_discovery=discovery_sources > 0,
            )
        )
    return summaries


@router.get("/{key}", response_model=PlatformDetail, summary="One platform assistant in detail")
def read_platform(key: str, session: DbSession, settings: AppSettings) -> PlatformDetail:
    platform = get_platform(key)
    if platform is None:
        raise ApiError("platform_not_found", f"no platform assistant named '{key}'", 404)

    jobs = JobRepository(session)
    applications = ApplicationRepository(session)
    job_counts = jobs.counts_by_source()
    app_counts = applications.counts_by_source()
    configs = {config.source: config for config in SourceConfigRepository(session).list_all()}

    source_reads: list[PlatformSourceRead] = []
    discovery = False
    browser_assistance = False
    import_enabled = False
    for source in platform.sources:
        adapter = get_adapter(source, settings)
        config = configs.get(source) or default_configuration(adapter)
        effective = effective_capabilities(adapter, config)
        discovery = discovery or effective.authorized_discovery_enabled
        browser_assistance = browser_assistance or effective.browser_assistance_enabled
        import_enabled = import_enabled or effective.manual_import_enabled
        source_reads.append(
            PlatformSourceRead(
                source=source.value,
                display_name=adapter.display_name,
                enabled=bool(config.enabled),
                capabilities=Capabilities(**adapter.capabilities.as_dict()),
                effective_capabilities=Capabilities(**effective.as_dict()),
                policy_basis=adapter.policy_basis,
                limitations=list(adapter.limitations),
                last_run_at=config.last_run_at.isoformat() if config.last_run_at else None,
                last_error=config.last_error or "",
                jobs_stored=job_counts.get(source.value, 0),
            )
        )

    sources: list[SourceName] = list(platform.sources)
    return PlatformDetail(
        key=platform.key,
        display_name=platform.display_name,
        tagline=platform.tagline,
        homepage=platform.homepage,
        how_jobs_arrive=platform.how_jobs_arrive,
        notes=list(platform.notes),
        search_url_template=platform.search_url_template,
        source_count=len(platform.sources),
        discovery_source_count=sum(
            1 for read in source_reads if read.effective_capabilities.authorized_discovery_enabled
        ),
        jobs_stored=sum(job_counts.get(s.value, 0) for s in platform.sources),
        applications=sum(app_counts.get(s.value, 0) for s in platform.sources),
        supports_automated_discovery=discovery,
        actions=_actions(
            discovery=discovery,
            browser_assistance=browser_assistance,
            import_enabled=import_enabled,
        ),
        sources=source_reads,
        jobs_by_status=jobs.status_counts_for_sources(sources),
        applications_by_status=applications.status_counts_for_sources(sources),
    )
