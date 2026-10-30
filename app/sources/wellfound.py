"""Wellfound source adapter — import only.

Basis: Wellfound's Talent General Terms section III prohibits copying or distributing
Content "including through the use of automated or non-automated harvesting, collection or
'scraping'", and prohibits using "any automated system (including a spider, robot, or
offline reader) to access the Site or Services" beyond what a human produces with a
conventional browser. No job-search API and no public jobseeker feed were found.
See docs/COMPLIANCE.md.

This adapter performs no network access.
"""

from __future__ import annotations

from app.db.models import SourceName
from app.sources.base import AdapterCapabilities, ImportOnlyAdapter


class WellfoundAdapter(ImportOnlyAdapter):
    source = SourceName.WELLFOUND
    display_name = "Wellfound"
    capabilities = AdapterCapabilities(
        manual_import_enabled=True,
        authorized_discovery_enabled=False,
        browser_assistance_enabled=True,
    )
    policy_basis = (
        "Wellfound's Talent General Terms prohibit automated and non-automated harvesting "
        "or scraping of Content and prohibit automated systems accessing the Site. No "
        "job-search API is offered."
    )
    limitations = (
        "No automated discovery. Nothing is fetched from wellfound.com.",
        "No RSS or public machine-readable jobseeker feed exists, so manual import is the "
        "only route for this source.",
        "Wellfound's terms require deleting Content acquired from the Site when you stop "
        "using it; use the per-source delete control on the Settings page.",
    )
