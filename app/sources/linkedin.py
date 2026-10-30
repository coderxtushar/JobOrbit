"""LinkedIn source adapter — import only.

Basis: LinkedIn's User Agreement s.8.2 prohibits using "software, devices, scripts, robots
or any other means or processes (such as crawlers, browser plugins and add-ons or any other
technology) to scrape or copy the Services", and prohibits "bots or other unauthorized
automated methods to access the Services". No jobseeker-facing job-search API exists.
See docs/COMPLIANCE.md for the full quotes and URLs.

Therefore this adapter performs no network access of any kind. It exists so that jobs the
user brings in themselves are correctly attributed to LinkedIn for deduplication and
tracking.
"""

from __future__ import annotations

from app.db.models import SourceName
from app.sources.base import AdapterCapabilities, ImportOnlyAdapter


class LinkedInAdapter(ImportOnlyAdapter):
    source = SourceName.LINKEDIN
    display_name = "LinkedIn"
    capabilities = AdapterCapabilities(
        manual_import_enabled=True,
        authorized_discovery_enabled=False,
        browser_assistance_enabled=True,
    )
    policy_basis = (
        "LinkedIn's User Agreement section 8.2 prohibits scrapers, crawlers, bots and "
        "browser extensions that access or copy the Services, and LinkedIn offers no "
        "job-search API to individual jobseekers."
    )
    limitations = (
        "No automated discovery. Nothing is fetched from linkedin.com.",
        "Bring jobs in by saving them to a CSV/JSON file, or let the email adapter read "
        "your LinkedIn job-alert emails from your own mailbox.",
        "Opening an application page launches your own browser. Nothing is automated there.",
        "A LinkedIn data export (Settings > Data privacy > Get a copy of your data) can be "
        "imported as CSV.",
    )
