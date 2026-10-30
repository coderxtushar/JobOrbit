"""Indeed source adapter — import only.

Basis: Indeed's Terms of Service revoke a jobseeker's licence on "any attempt to use the
Site for any other purpose" than personal job seeking, and state explicitly that "use of
any automation, scripting, or bots to automate the Indeed Apply process outside of Indeed's
official vendors and tooling is prohibited". No public jobseeker job-search API is offered.
See docs/COMPLIANCE.md.

This adapter performs no network access. Indeed's own "recommended jobs" alert emails are
the supported discovery route, read from the user's mailbox by the email adapter.
"""

from __future__ import annotations

from app.db.models import SourceName
from app.sources.base import AdapterCapabilities, ImportOnlyAdapter


class IndeedAdapter(ImportOnlyAdapter):
    source = SourceName.INDEED
    display_name = "Indeed"
    capabilities = AdapterCapabilities(
        manual_import_enabled=True,
        authorized_discovery_enabled=False,
        browser_assistance_enabled=True,
    )
    policy_basis = (
        "Indeed's Terms of Service limit jobseeker use to personal job seeking and state "
        "that automating the Indeed Apply process with scripts or bots is prohibited. "
        "Indeed offers no public job-search API for individual jobseekers."
    )
    limitations = (
        "No automated discovery and no Indeed Apply automation. Nothing is fetched from "
        "indeed.com.",
        "Turn on Indeed job alerts, then let the email adapter read them from your mailbox.",
        "CSV or JSON import works for jobs you collect yourself.",
    )
