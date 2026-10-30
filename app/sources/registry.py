"""Source registry.

Resolves a :class:`SourceName` to its adapter and computes *effective* capabilities by
intersecting what the adapter declares with what the user has configured. The intersection
direction matters: a user can narrow a capability but never widen one, so no setting in
the UI or in ``.env`` can turn on something the adapter has not documented a basis for.
"""

from __future__ import annotations

from app.config import Settings, get_settings
from app.db.models import SourceConfiguration, SourceName
from app.sources.aggregators import (
    ArbeitnowAdapter,
    HimalayasAdapter,
    JobicyAdapter,
    RemoteOkAdapter,
    RemotiveAdapter,
)
from app.sources.ats import (
    AshbyAdapter,
    GreenhouseAdapter,
    LeverAdapter,
    SmartRecruitersAdapter,
    WorkableAdapter,
)
from app.sources.base import AdapterCapabilities, SourceAdapter
from app.sources.boards import (
    CompanySiteAdapter,
    CutshortAdapter,
    HiristAdapter,
    InstahyreAdapter,
    WorkdayAdapter,
)
from app.sources.email_alerts import EmailAlertAdapter
from app.sources.indeed import IndeedAdapter
from app.sources.linkedin import LinkedInAdapter
from app.sources.manual_import import CsvImportAdapter, ManualImportAdapter
from app.sources.naukri import NaukriAdapter
from app.sources.wellfound import WellfoundAdapter

_STATIC_ADAPTERS: dict[SourceName, type[SourceAdapter]] = {
    SourceName.MANUAL: ManualImportAdapter,
    SourceName.CSV: CsvImportAdapter,
    SourceName.LINKEDIN: LinkedInAdapter,
    SourceName.INDEED: IndeedAdapter,
    SourceName.NAUKRI: NaukriAdapter,
    SourceName.WELLFOUND: WellfoundAdapter,
    SourceName.INSTAHYRE: InstahyreAdapter,
    SourceName.CUTSHORT: CutshortAdapter,
    SourceName.HIRIST: HiristAdapter,
    SourceName.WORKDAY: WorkdayAdapter,
    SourceName.COMPANY_SITE: CompanySiteAdapter,
}

#: Adapters that need the runtime settings object (board tokens, mailbox credentials).
_SETTINGS_ADAPTERS: dict[SourceName, type[SourceAdapter]] = {
    SourceName.GREENHOUSE: GreenhouseAdapter,
    SourceName.LEVER: LeverAdapter,
    SourceName.WORKABLE: WorkableAdapter,
    SourceName.ASHBY: AshbyAdapter,
    SourceName.SMARTRECRUITERS: SmartRecruitersAdapter,
    SourceName.ARBEITNOW: ArbeitnowAdapter,
    SourceName.REMOTEOK: RemoteOkAdapter,
    SourceName.REMOTIVE: RemotiveAdapter,
    SourceName.HIMALAYAS: HimalayasAdapter,
    SourceName.JOBICY: JobicyAdapter,
}

ALL_SOURCES: tuple[SourceName, ...] = (
    SourceName.MANUAL,
    SourceName.CSV,
    SourceName.EMAIL_ALERT,
    SourceName.LINKEDIN,
    SourceName.INDEED,
    SourceName.NAUKRI,
    SourceName.WELLFOUND,
    SourceName.INSTAHYRE,
    SourceName.CUTSHORT,
    SourceName.HIRIST,
    SourceName.GREENHOUSE,
    SourceName.LEVER,
    SourceName.WORKABLE,
    SourceName.ASHBY,
    SourceName.SMARTRECRUITERS,
    SourceName.ARBEITNOW,
    SourceName.REMOTEOK,
    SourceName.REMOTIVE,
    SourceName.HIMALAYAS,
    SourceName.JOBICY,
    SourceName.WORKDAY,
    SourceName.COMPANY_SITE,
)

DISCOVERY_SOURCES: tuple[SourceName, ...] = (
    SourceName.EMAIL_ALERT,
    SourceName.GREENHOUSE,
    SourceName.LEVER,
    SourceName.WORKABLE,
    SourceName.ASHBY,
    SourceName.SMARTRECRUITERS,
    SourceName.ARBEITNOW,
    SourceName.REMOTEOK,
    SourceName.REMOTIVE,
    SourceName.HIMALAYAS,
    SourceName.JOBICY,
)


def get_adapter(source: SourceName, settings: Settings | None = None) -> SourceAdapter:
    """Return the adapter for a source."""
    if source is SourceName.EMAIL_ALERT:
        return EmailAlertAdapter(settings or get_settings())
    settings_adapter = _SETTINGS_ADAPTERS.get(source)
    if settings_adapter is not None:
        return settings_adapter(settings or get_settings())  # type: ignore[call-arg]
    adapter_class = _STATIC_ADAPTERS.get(source)
    if adapter_class is None:
        raise KeyError(f"no adapter registered for source '{source.value}'")
    return adapter_class()


def all_adapters(settings: Settings | None = None) -> list[SourceAdapter]:
    return [get_adapter(source, settings) for source in ALL_SOURCES]


def effective_capabilities(
    adapter: SourceAdapter, config: SourceConfiguration | None
) -> AdapterCapabilities:
    """Intersect declared capabilities with user configuration."""
    declared = adapter.capabilities
    if config is None:
        return declared
    return AdapterCapabilities(
        manual_import_enabled=declared.manual_import_enabled and config.manual_import_enabled,
        authorized_discovery_enabled=(
            declared.authorized_discovery_enabled and config.authorized_discovery_enabled
        ),
        browser_assistance_enabled=(
            declared.browser_assistance_enabled and config.browser_assistance_enabled
        ),
    )


def default_configuration(adapter: SourceAdapter) -> SourceConfiguration:
    """A configuration row seeded from the adapter's declared capabilities."""
    declared = adapter.capabilities
    return SourceConfiguration(
        source=adapter.source,
        enabled=True,
        manual_import_enabled=declared.manual_import_enabled,
        authorized_discovery_enabled=declared.authorized_discovery_enabled,
        browser_assistance_enabled=declared.browser_assistance_enabled,
        automated_submission_enabled=False,
        rate_limit_per_hour=30,
    )


def unsupported_requests(adapter: SourceAdapter, requested: dict[str, bool]) -> list[str]:
    """Report requested capabilities the adapter cannot grant, for a clear error."""
    declared = adapter.capabilities.as_dict()
    problems: list[str] = []
    for name, wanted in requested.items():
        if not wanted:
            continue
        if name == "automated_submission_enabled":
            problems.append(
                "automated_submission_enabled cannot be enabled for any source: automated "
                "application submission is prohibited and is not implemented"
            )
        elif not declared.get(name, False):
            problems.append(
                f"{adapter.display_name} does not support '{name}'. {adapter.policy_basis}"
            )
    return problems
