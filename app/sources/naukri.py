"""Naukri source adapter — import only.

Basis: Naukri's Terms & Conditions page could not be retrieved programmatically on
2026-10-28, so **no clause has been verified**. Rather than assume a permission, this
adapter applies the most restrictive defaults and tells the user precisely that. No public
jobseeker job-search API was found.

To enable discovery here, a maintainer must read Naukri's current terms, record the clause
and URL in docs/COMPLIANCE.md, and change the declared capability in this module.
Configuration alone cannot enable it.
"""

from __future__ import annotations

from app.db.models import SourceName
from app.sources.base import AdapterCapabilities, ImportOnlyAdapter


class NaukriAdapter(ImportOnlyAdapter):
    source = SourceName.NAUKRI
    display_name = "Naukri"
    capabilities = AdapterCapabilities(
        manual_import_enabled=True,
        authorized_discovery_enabled=False,
        browser_assistance_enabled=True,
    )
    policy_basis = (
        "Naukri's Terms & Conditions could not be verified programmatically, and no public "
        "jobseeker job-search API was found. Because nothing was verified, this source "
        "defaults to the most restrictive setting: no automated access of any kind."
    )
    limitations = (
        "No automated discovery. Nothing is fetched from naukri.com.",
        "Naukri's own job-alert emails can be read from your mailbox by the email adapter.",
        "CSV or JSON import works for jobs you collect yourself.",
        "Capability is unverified rather than denied: see docs/COMPLIANCE.md for what would "
        "need to be confirmed before discovery could be enabled.",
    )
