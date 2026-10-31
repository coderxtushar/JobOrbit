"""Platform assistants: a user-facing grouping over the source adapters.

The dashboard's platform sections are a *view* of :mod:`app.sources.registry`, not a second
source of truth. Each entry here names the ``SourceName`` values it covers and nothing
else; every capability, policy citation and limitation shown to the user is read back from
the adapter at request time. That is deliberate — a hand-written capability list would
drift from the adapters, and the one thing this project must never get wrong is telling
someone a platform supports something it does not.

Consequences:

* **Counts come from the database, never from this file.** A platform with no stored jobs
  reports zero, not a placeholder.
* **A platform's supported actions are derived** from its effective capabilities, so a
  configuration change that narrows a capability narrows the UI in the same request.
* **No entry can declare submission.** The adapter dataclass refuses it and the database
  has a ``CHECK`` constraint; this layer has no way to override either.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.db.models import SourceName


@dataclass(frozen=True, slots=True)
class PlatformAction:
    """One thing a user can actually do for a platform, and whether it is available."""

    key: str
    label: str
    description: str
    available: bool


@dataclass(frozen=True, slots=True)
class Platform:
    """A user-facing assistant section covering one or more source adapters."""

    key: str
    display_name: str
    tagline: str
    sources: tuple[SourceName, ...]
    homepage: str
    #: Shown verbatim. Describes how jobs get in, in the user's terms rather than the
    #: adapter's, and must stay consistent with the adapter's own policy basis.
    how_jobs_arrive: str
    search_url_template: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)


#: Order is the order the sidebar renders them in: the three highest-volume Indian and
#: global jobseeker platforms first, then Wellfound, then everything that speaks a real API.
PLATFORMS: tuple[Platform, ...] = (
    Platform(
        key="naukri",
        display_name="Naukri",
        tagline="India's largest jobseeker platform. Import-only.",
        sources=(SourceName.NAUKRI,),
        homepage="https://www.naukri.com",
        search_url_template="https://www.naukri.com/{query}-jobs",
        how_jobs_arrive=(
            "You search on Naukri yourself and bring the listings here — by pasting a job "
            "URL, or by exporting a CSV. Naukri publishes no jobseeker search API, and its "
            "terms could not be verified programmatically, so this adapter defaults to the "
            "most restrictive setting rather than assuming a permission."
        ),
        notes=(
            "Job-alert emails from Naukri can be ingested if you enable mailbox reading, "
            "because that data is your own mail.",
        ),
    ),
    Platform(
        key="linkedin",
        display_name="LinkedIn",
        tagline="Strong for referrals and recruiter contact. Import-only.",
        sources=(SourceName.LINKEDIN,),
        homepage="https://www.linkedin.com/jobs",
        search_url_template="https://www.linkedin.com/jobs/search/?keywords={query}",
        how_jobs_arrive=(
            "You bring listings here by URL or CSV. LinkedIn's User Agreement section 8.2 "
            "prohibits scrapers, bots and automated access, and there is no jobseeker "
            "job-search API, so nothing is fetched automatically."
        ),
        notes=(
            "LinkedIn job-alert emails can be ingested if you enable mailbox reading.",
            "Easy Apply cannot be automated and is not attempted.",
        ),
    ),
    Platform(
        key="indeed",
        display_name="Indeed",
        tagline="Wide aggregation across employers. Import-only.",
        sources=(SourceName.INDEED,),
        homepage="https://www.indeed.com",
        search_url_template="https://www.indeed.com/jobs?q={query}",
        how_jobs_arrive=(
            "You bring listings here by URL or CSV. Indeed offers no jobseeker search API, "
            'and its terms state that "use of any automation, scripting, or bots to '
            'automate the Indeed Apply process" is prohibited, so neither discovery nor '
            "submission is automated."
        ),
        notes=("Indeed job-alert emails can be ingested if you enable mailbox reading.",),
    ),
    Platform(
        key="wellfound",
        display_name="Wellfound",
        tagline="Startup roles, often direct to founders. Import-only.",
        sources=(SourceName.WELLFOUND,),
        homepage="https://wellfound.com/jobs",
        search_url_template="https://wellfound.com/role/r/{query}",
        how_jobs_arrive=(
            "You bring listings here by URL or CSV. Wellfound's terms prohibit harvesting "
            "and automated access, and listings are login-gated, so nothing is fetched "
            "automatically."
        ),
    ),
    Platform(
        key="ats",
        display_name="ATS & other platforms",
        tagline="Greenhouse, Lever, Ashby, Workable, SmartRecruiters and open job feeds.",
        sources=(
            SourceName.GREENHOUSE,
            SourceName.LEVER,
            SourceName.ASHBY,
            SourceName.WORKABLE,
            SourceName.SMARTRECRUITERS,
            SourceName.ARBEITNOW,
            SourceName.REMOTEOK,
            SourceName.REMOTIVE,
            SourceName.HIMALAYAS,
            SourceName.JOBICY,
            SourceName.WORKDAY,
            SourceName.COMPANY_SITE,
            SourceName.INSTAHYRE,
            SourceName.CUTSHORT,
            SourceName.HIRIST,
            SourceName.EMAIL_ALERT,
            SourceName.MANUAL,
            SourceName.CSV,
        ),
        homepage="",
        how_jobs_arrive=(
            "This is the only group with real automated discovery. Greenhouse, Lever, "
            "Ashby, Workable and SmartRecruiters each publish an unauthenticated endpoint "
            "whose documented purpose is serving one company's own job board — the same one "
            "their careers page calls — so configuring a company board here is a lookup, "
            "not a crawl. Five open job feeds are also supported and are off by default."
        ),
        notes=(
            "No company board list ships with the app: bundling one would turn a "
            "per-company lookup into a crawl.",
            "Workday's feed is reachable but is an internal interface for Workday's own "
            "front end, so it is deliberately import-only.",
        ),
    ),
)

PLATFORMS_BY_KEY: dict[str, Platform] = {platform.key: platform for platform in PLATFORMS}

#: Every source must appear in exactly one platform section, or a source's jobs would be
#: invisible in the platform view while still counted on the job feed.
_COVERED: set[SourceName] = {source for platform in PLATFORMS for source in platform.sources}
_UNCOVERED: set[SourceName] = set(SourceName) - _COVERED
if _UNCOVERED:  # pragma: no cover - guards a future SourceName addition
    raise RuntimeError(
        f"these sources are not shown in any platform section: {sorted(s.value for s in _UNCOVERED)}"
    )


def get_platform(key: str) -> Platform | None:
    return PLATFORMS_BY_KEY.get(key)
