"""Import-only adapters for the remaining platforms.

Each one was checked for a public jobseeker search interface and none has one. They are
declared import-only with the reason stated, so the diagnostics page can explain exactly
why a source returns nothing instead of leaving the user to guess.

Workday is the interesting case. Every Workday tenant serves its careers page from a
``/wday/cxs/<tenant>/<site>/jobs`` endpoint, so a feed is technically reachable. It is not
used here: that path is an internal interface for Workday's own front end, not a published
integration, and Workday's documented job APIs require tenant credentials issued to the
employer. Reading it would be exactly the "technically possible, not authorized" case the
project refuses, so Workday takes CSV and JSON exports like the rest.
"""

from __future__ import annotations

from app.db.models import SourceName
from app.sources.base import AdapterCapabilities, ImportOnlyAdapter

_IMPORT_ONLY = AdapterCapabilities(
    manual_import_enabled=True,
    authorized_discovery_enabled=False,
    browser_assistance_enabled=True,
)


class InstahyreAdapter(ImportOnlyAdapter):
    source = SourceName.INSTAHYRE
    display_name = "Instahyre"
    capabilities = _IMPORT_ONLY
    policy_basis = (
        "Instahyre publishes no jobseeker job-search API. Its listings sit behind a "
        "candidate login, and its terms reserve the service for personal, manual use, so "
        "automated collection is not authorized."
    )
    limitations = (
        "No automated discovery; nothing is fetched from instahyre.com.",
        "Instahyre's own match emails can be read by the email job-alert adapter.",
        "CSV or JSON import works for roles you shortlist yourself.",
    )


class CutshortAdapter(ImportOnlyAdapter):
    source = SourceName.CUTSHORT
    display_name = "Cutshort"
    capabilities = _IMPORT_ONLY
    policy_basis = (
        "Cutshort offers no public jobseeker search API. Its job pages require an "
        "authenticated candidate session, which this project never automates."
    )
    limitations = (
        "No automated discovery; nothing is fetched from cutshort.io.",
        "CSV or JSON import works for roles you shortlist yourself.",
    )


class HiristAdapter(ImportOnlyAdapter):
    source = SourceName.HIRIST
    display_name = "Hirist"
    capabilities = _IMPORT_ONLY
    policy_basis = (
        "Hirist (Info Edge, the same group as Naukri) publishes no jobseeker job-search "
        "API, and its terms restrict the site to personal non-automated use."
    )
    limitations = (
        "No automated discovery; nothing is fetched from hirist.tech.",
        "Hirist job-alert emails can be read by the email job-alert adapter.",
        "CSV or JSON import works for roles you shortlist yourself.",
    )


class WorkdayAdapter(ImportOnlyAdapter):
    source = SourceName.WORKDAY
    display_name = "Workday"
    capabilities = _IMPORT_ONLY
    policy_basis = (
        "Workday's documented recruiting APIs are tenant-scoped and require credentials "
        "issued by the employer. The /wday/cxs/ endpoint that each careers site calls is "
        "an internal interface for Workday's own front end, not a published jobseeker "
        "integration, so it is deliberately not used."
    )
    limitations = (
        "No automated discovery, even though a tenant endpoint is technically reachable.",
        "Export the roles you want from the employer's careers site and import them.",
        "If your employer grants you authorized API credentials, a discovery adapter can "
        "be added with that basis recorded in docs/COMPLIANCE.md.",
    )


class CompanySiteAdapter(ImportOnlyAdapter):
    source = SourceName.COMPANY_SITE
    display_name = "Company career page"
    capabilities = _IMPORT_ONLY
    policy_basis = (
        "A generic bucket for roles found directly on an employer's own site. There is no "
        "single operator to obtain permission from, so nothing is fetched automatically; "
        "if the employer runs Greenhouse, Lever or Workable, use that adapter instead and "
        "the listing arrives through a published interface."
    )
    limitations = (
        "Import only. Paste or export the listing yourself.",
        "Use the Greenhouse, Lever or Workable adapter where the employer uses one of "
        "those systems — that path is automated and authorized.",
    )
