"""Submission provider registry.

Maps a job to the adapter that could submit it. By default every real platform reports
``submission_not_supported`` with its reason; with ``JA_BROWSER_SUBMISSION_ENABLED`` the
Greenhouse, Lever and Ashby providers are served by the browser form adapter instead.

The routing rule is the application URL's host, not the source the listing came from. A
job discovered through a job-alert email may live on a Greenhouse board; a job imported
from a LinkedIn export is still a LinkedIn job. Where the host matches nothing known the
job routes to :data:`UNKNOWN_PROVIDER`, which is also unsupported — an unrecognised form
is precisely the case where a program must not start typing.

:func:`supported_targets` returns the exact set of providers this build will submit to.
A test pins that set, mirroring how discovery capabilities are pinned, so enabling a new
submission target cannot happen without the test and the feasibility document changing
together.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlsplit

from app.db.models import Job
from app.submission.base import (
    CredentialOwner,
    SubmissionAdapter,
    SubmissionTarget,
    UnsupportedSubmissionAdapter,
)

# --------------------------------------------------------------------------------------
# Targets
# --------------------------------------------------------------------------------------

LINKEDIN = SubmissionTarget("linkedin", "LinkedIn")
INDEED = SubmissionTarget("indeed", "Indeed")
NAUKRI = SubmissionTarget("naukri", "Naukri")
WELLFOUND = SubmissionTarget("wellfound", "Wellfound")
GREENHOUSE = SubmissionTarget("greenhouse", "Greenhouse")
LEVER = SubmissionTarget("lever", "Lever")
ASHBY = SubmissionTarget("ashby", "Ashby")
SMARTRECRUITERS = SubmissionTarget("smartrecruiters", "SmartRecruiters")
WORKABLE = SubmissionTarget("workable", "Workable")
UNKNOWN_PROVIDER = SubmissionTarget("unknown", "an unrecognised application form")
LOCAL_TEST = SubmissionTarget("local_test", "JobOrbit local test server")

#: Host fragments that identify a provider. Matched as a suffix or substring of the
#: application URL's host, because boards are served from both ``company.greenhouse.io``
#: and ``boards.greenhouse.io/company`` style hosts.
_HOST_PATTERNS: tuple[tuple[str, SubmissionTarget], ...] = (
    ("linkedin.", LINKEDIN),
    ("indeed.", INDEED),
    ("naukri.", NAUKRI),
    ("wellfound.", WELLFOUND),
    ("angel.co", WELLFOUND),
    ("greenhouse.io", GREENHOUSE),
    ("lever.co", LEVER),
    ("ashbyhq.com", ASHBY),
    ("smartrecruiters.com", SMARTRECRUITERS),
    ("workable.com", WORKABLE),
)


# --------------------------------------------------------------------------------------
# The four job platforms: prohibited by published terms
# --------------------------------------------------------------------------------------

_PLATFORM_ADAPTERS: tuple[UnsupportedSubmissionAdapter, ...] = (
    UnsupportedSubmissionAdapter(
        LINKEDIN,
        reason=(
            "LinkedIn publishes no candidate-side application API, and its User Agreement "
            "section 8.2 prohibits using 'bots or other unauthorized automated methods to "
            "access the Services'. Easy Apply is a first-party feature of LinkedIn's own "
            "interface, not an interface offered to third-party software. Prepare the "
            "application here and submit it in your own browser."
        ),
        credential_owner=CredentialOwner.NONE,
        documented_api=False,
        evidence_url="https://www.linkedin.com/legal/user-agreement",
        evidence_quote=(
            "Use bots or other unauthorized automated methods to access the Services, add "
            "or download contacts, send or redirect messages..."
        ),
    ),
    UnsupportedSubmissionAdapter(
        INDEED,
        reason=(
            "Indeed's terms prohibit automating Indeed Apply outside its own approved "
            "vendor programme, and no jobseeker credential exists for it. This is the one "
            "platform in scope that bans the exact operation by name."
        ),
        credential_owner=CredentialOwner.APPROVED_VENDOR,
        documented_api=False,
        evidence_url="https://www.indeed.com/legal",
        evidence_quote=(
            "Use of any automation, scripting, or bots to automate the Indeed Apply "
            "process outside of Indeed's official vendors and tooling is prohibited."
        ),
    ),
    UnsupportedSubmissionAdapter(
        NAUKRI,
        reason=(
            "Naukri's terms page could not be retrieved programmatically to establish what "
            "it permits, so this adapter defaults to the most restrictive setting rather "
            "than assuming a permission. No jobseeker API is published. Submit on Naukri "
            "yourself."
        ),
        credential_owner=CredentialOwner.UNDOCUMENTED,
        documented_api=False,
        evidence_url="https://www.naukri.com/termsconditions",
        evidence_quote="",
    ),
    UnsupportedSubmissionAdapter(
        WELLFOUND,
        reason=(
            "Wellfound's Talent General Terms prohibit using 'any automated system "
            "(including a spider, robot, or offline reader) to access the Site', and no "
            "candidate application API is published."
        ),
        credential_owner=CredentialOwner.NONE,
        documented_api=False,
        evidence_url="https://wellfound.com/terms",
        evidence_quote=(
            "use any automated system (including a spider, robot, or offline reader) to "
            "access the Site"
        ),
    ),
)


# --------------------------------------------------------------------------------------
# The five ATS providers. Their read APIs are public and already used for discovery.
# All five document an application-submission interface, and all five authenticate it with
# a credential the *employer* holds — which is the reason none is usable here, and is
# quoted per provider so the claim can be checked rather than taken on trust.
# --------------------------------------------------------------------------------------

_ATS_PREFIX = (
    "{name} publishes a public job-board API that this project already uses to *discover* "
    "roles, and that interface is read-only. Its application-submission interface exists "
    "but authenticates with a credential the hiring company holds, which a jobseeker "
    "cannot obtain: {detail} The application is prepared here and the employer's own form "
    "is opened for you."
)

_ATS_EVIDENCE: tuple[tuple[SubmissionTarget, str, str, str], ...] = (
    (
        GREENHOUSE,
        "the Job Board API Key, which Greenhouse tells the board owner to keep secret and "
        "proxy through its own servers.",
        "https://developers.greenhouse.io/job-board.html",
        "Only the application submission endpoint requires Basic Auth. The Job Board API "
        "Key must be Base64 encoded before it can be used to post applications. [...] the "
        "HTTP Basic Auth API token is a secret key. Any form posts should be proxied by "
        "your own servers.",
    ),
    (
        LEVER,
        "an API key only an account Super Admin can generate.",
        "https://github.com/lever/postings-api#apply-to-a-job-posting",
        "To use the POST API, you need an API key, which a Super Admin of your account can "
        "generate from your integrations settings page.",
    ),
    (
        ASHBY,
        "an organization-scoped credential carrying the candidatesWrite permission.",
        "https://developers.ashbyhq.com/reference/applicationformsubmit",
        "Requires the candidatesWrite permission.",
    ),
    (
        SMARTRECRUITERS,
        "an organization credential; there is no unauthenticated per-posting route.",
        "https://developers.smartrecruiters.com/docs/application-api",
        "All endpoints are protected. [...] [An API key] can be generated by a user with "
        "Administrator access.",
    ),
    (
        WORKABLE,
        "an employer-generated token carrying the w_candidates scope. The public widget "
        "feed this project reads is for displaying openings, not for applying.",
        "https://help.workable.com/hc/en-us/articles/115012771647",
        "[The r_jobs scope suffices to show jobs; a custom application requires] "
        "w_candidates [to] create candidates in Workable.",
    ),
)

_ATS_ADAPTERS: tuple[UnsupportedSubmissionAdapter, ...] = tuple(
    UnsupportedSubmissionAdapter(
        target,
        reason=_ATS_PREFIX.format(name=target.display_name, detail=detail),
        credential_owner=CredentialOwner.EMPLOYER,
        documented_api=True,
        evidence_url=url,
        evidence_quote=quote,
    )
    for target, detail, url, quote in _ATS_EVIDENCE
)

_UNKNOWN_ADAPTER = UnsupportedSubmissionAdapter(
    UNKNOWN_PROVIDER,
    reason=(
        "This application form is not one of the providers JobOrbit knows how to read. An "
        "unrecognised form is exactly where automated filling would guess, so nothing is "
        "attempted; the page is opened for you to complete."
    ),
    credential_owner=CredentialOwner.UNDOCUMENTED,
    documented_api=False,
)


def _browser_adapters() -> tuple[SubmissionAdapter, ...]:
    """The hosted-form adapters, present only when browser submission is switched on.

    Greenhouse, Lever and Ashby host a public application form for every posting — the
    same page a candidate fills in by hand. With ``JA_BROWSER_SUBMISSION_ENABLED`` the
    browser adapter fills that form for the user; without it these providers keep their
    unsupported adapter and the reason above.
    """
    from app.config import get_settings

    settings = get_settings()
    if not settings.browser_submission_enabled:
        return ()
    from app.browser.dom import Pacing
    from app.submission.browser_ats import (
        BrowserFormAdapter,
        ashby_apply_url,
        greenhouse_apply_url,
        lever_apply_url,
    )

    def build(target: SubmissionTarget, url_for: Callable[[Job], str]) -> SubmissionAdapter:
        return BrowserFormAdapter(
            target,
            apply_url=url_for,
            data_dir=settings.data_dir,
            pacing=Pacing(
                settings.browser_action_delay_min_ms, settings.browser_action_delay_max_ms
            ),
            confirmation_timeout_s=settings.browser_confirmation_timeout_s,
            evidence_screenshots=settings.evidence_screenshots,
        )

    return (
        build(GREENHOUSE, greenhouse_apply_url),
        build(LEVER, lever_apply_url),
        build(ASHBY, ashby_apply_url),
    )


#: Providers the browser adapter can fill. Pinned by test alongside :func:`supported_targets`.
BROWSER_TARGET_KEYS: frozenset[str] = frozenset({"greenhouse", "lever", "ashby"})


def _registry() -> dict[str, SubmissionAdapter]:
    adapters: dict[str, SubmissionAdapter] = {
        adapter.target.key: adapter for adapter in (*_PLATFORM_ADAPTERS, *_ATS_ADAPTERS)
    }
    for adapter in _browser_adapters():
        adapters[adapter.target.key] = adapter
    adapters[UNKNOWN_PROVIDER.key] = _UNKNOWN_ADAPTER

    # Imported lazily: the local adapter needs a server address supplied at call time, and
    # importing it here keeps this module free of any network-capable default.
    from app.submission.local_test import build_local_test_adapter

    local = build_local_test_adapter()
    if local is not None:
        adapters[LOCAL_TEST.key] = local
    return adapters


def target_for_url(url: str) -> SubmissionTarget:
    """Identify the submission provider from an application URL."""
    host = (urlsplit(url).hostname or "").lower()
    if not host:
        return UNKNOWN_PROVIDER
    if host in {"127.0.0.1", "localhost"} or host.endswith(".localhost"):
        return LOCAL_TEST
    for fragment, target in _HOST_PATTERNS:
        if fragment in host:
            return target
    return UNKNOWN_PROVIDER


def target_for_job(job: Job) -> SubmissionTarget:
    """Identify the submission provider for a job from its application URL."""
    return target_for_url(job.url or "")


def get_submission_adapter(target: SubmissionTarget | str) -> SubmissionAdapter:
    """Return the adapter for a target, falling back to the unsupported unknown provider."""
    key = target if isinstance(target, str) else target.key
    return _registry().get(key, _UNKNOWN_ADAPTER)


def adapter_for_job(job: Job) -> SubmissionAdapter:
    return get_submission_adapter(target_for_job(job))


def all_submission_adapters() -> tuple[SubmissionAdapter, ...]:
    return tuple(_registry().values())


def supported_targets() -> frozenset[str]:
    """Keys of every provider this build will actually submit to.

    Derived from each adapter's own capability report rather than a hand-kept list, so it
    cannot drift from what the adapters do.
    """
    from app.db.models import Job as JobModel

    probe = JobModel(title="", company="", url="")
    return frozenset(
        adapter.target.key
        for adapter in all_submission_adapters()
        if adapter.check_capability(probe).supported
    )
