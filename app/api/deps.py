"""Request dependencies."""

from __future__ import annotations

import hmac
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, Request, status
from sqlalchemy.orm import Session, sessionmaker

from app.api.errors import ApiError
from app.config import Settings, get_settings
from app.db.base import get_session_factory
from app.db.models import CandidateProfile, User
from app.db.repositories import ProfileRepository
from app.llm.base import LLMProvider
from app.llm.factory import build_provider
from app.services.demo_sessions import get_store as get_demo_store

DEMO_SESSION_HEADER = "X-Demo-Session"
#: Set by the website's server from its httpOnly cookie; never by page script.
SESSION_HEADER = "X-JobOrbit-Session"


def _demo_session_factory(request: Request, settings: Settings) -> sessionmaker[Session] | None:
    """Resolve the visitor's own database, or refuse a write that cannot be isolated.

    Enforced here rather than in each route body because every mutating route depends on
    :func:`get_db`: a new endpoint is covered the moment it is added, and the check cannot
    be forgotten at one call site. The endpoint name is read from the request scope, which
    Starlette fills in during routing — before dependencies are solved.
    """
    if not settings.demo_mode:
        return None

    store = get_demo_store()
    key = (request.headers.get(DEMO_SESSION_HEADER) or "").strip()
    if store is not None and key:
        return store.factory_for(key)

    endpoint = request.scope.get("endpoint")
    operation = getattr(endpoint, "__name__", "")
    if operation in DEMO_SESSION_SCOPED:
        raise ApiError(
            "demo_mode_write_disabled",
            DEMO_WRITE_DISABLED_MESSAGE,
            status.HTTP_403_FORBIDDEN,
        )
    return None


def get_db(
    request: Request,
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> Iterator[Session]:
    """Per-request transactional session, isolated per visitor in demo mode."""
    factory = _demo_session_factory(request, settings) or get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_app_settings() -> Settings:
    return get_settings()


def _check_service_token(settings: Settings, authorization: str | None) -> None:
    if not settings.api_token:
        return
    expected = f"Bearer {settings.api_token}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise ApiError(
            "unauthorized",
            "A valid bearer token is required.",
            status.HTTP_401_UNAUTHORIZED,
        )


def require_auth(
    request: Request,
    settings: Annotated[Settings, Depends(get_app_settings)],
    session: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
    x_joborbit_session: Annotated[str | None, Header()] = None,
) -> None:
    """Enforce the service token, and in hosted mode a signed-in user and route policy.

    The bearer token proves the caller is the website's server (mandatory off loopback,
    enforced in :class:`~app.config.Settings`). In ``google`` mode that is not enough: the
    request must also carry a session created from a verified Google sign-in, and the
    route must be one a signed-in user may call (:data:`HOSTED_POLICY`).
    """
    _check_service_token(settings, authorization)
    if not settings.is_multi_user:
        return
    endpoint = _endpoint_name(request)
    if endpoint in HOSTED_OPEN:
        return
    from app.services.accounts import user_for_session

    user = user_for_session(session, x_joborbit_session or "")
    if user is None:
        raise ApiError("signin_required", "Sign in to use JobOrbit.", status.HTTP_401_UNAUTHORIZED)
    request.state.user = user
    policy = HOSTED_POLICY.get(endpoint)
    if policy is None:  # pragma: no cover - the guard test keeps this unreachable
        raise ApiError("forbidden", "This action is not available.", status.HTTP_403_FORBIDDEN)
    if policy == "admin" and user.email.lower() not in settings.admin_email_set:
        raise ApiError(
            "admin_only",
            "Only the people who run this JobOrbit installation can do that.",
            status.HTTP_403_FORBIDDEN,
        )
    if policy == "blocked":
        raise ApiError(
            f"hosted_{endpoint}_unavailable",
            HOSTED_BLOCKED_REASONS[_HOSTED_BLOCKED_GROUP[endpoint]],
            status.HTTP_403_FORBIDDEN,
        )


def _endpoint_name(request: Request) -> str:
    endpoint = request.scope.get("endpoint")
    return getattr(endpoint, "__name__", "")


def current_user(request: Request) -> User | None:
    """The signed-in user in hosted mode (set by :func:`require_auth`); ``None`` locally."""
    return getattr(request.state, "user", None)


def get_profile(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> CandidateProfile:
    """The profile this request acts for.

    Locally that is the single local owner's profile, created on first use. In hosted
    mode it is the signed-in user's own profile; there is no default to fall back to, so
    a route that forgot :data:`Authorized` fails closed instead of serving someone else.
    """
    if not settings.is_multi_user:
        return ProfileRepository(session).get_or_create_default()
    user = current_user(request)
    if user is None:
        raise ApiError("signin_required", "Sign in to use JobOrbit.", status.HTTP_401_UNAUTHORIZED)
    from app.services.accounts import profile_for

    return profile_for(session, user)


#: Hosted (google) mode route policy, by endpoint function name:
#:
#: * ``personal`` — any signed-in user; the route acts only on their own profile.
#: * ``admin`` — installation-wide actions, for the emails in ``JA_ADMIN_EMAILS``.
#: * ``blocked`` — cannot work for a hosted user at all; the reason says why.
#:
#: ``tests/test_accounts.py`` fails if a route is in neither this map nor
#: :data:`HOSTED_OPEN`, so a new endpoint cannot ship without a decision.
HOSTED_OPEN: frozenset[str] = frozenset({"health", "create_session", "gmail_oauth_callback"})

HOSTED_BLOCKED_REASONS: dict[str, str] = {
    "browser_autoapply": (
        "Auto-apply fills forms in a Chrome window on your own computer, where you can "
        "solve a CAPTCHA or type a code. The hosted site has no such window, so runs are "
        "local-only for now. The preflight still shows what a run would do."
    ),
    "email": (
        "Reading Gmail from a public app needs Google's security assessment for the "
        "restricted Gmail scope, so email tracking is available in a local install only."
    ),
    "capture": (
        "The capture extension sends pages to a JobOrbit running on your own computer, "
        "so it is available in a local install only."
    ),
}

_HOSTED_BLOCKED_GROUP: dict[str, str] = {
    **{
        name: "browser_autoapply"
        for name in (
            "start_run",
            "resume_run",
            "attempt_evidence",
            "recheck_attempt",
            "resolve_attempt",
        )
    },
    **{
        name: "email"
        for name in (
            "email_tracking_status",
            "gmail_connect_url",
            "sync_email",
            "ingest_email",
            "list_email_messages",
            "list_status_suggestions",
            "accept_status_suggestion",
            "dismiss_status_suggestion",
            "link_email_message",
            "dismiss_email_message",
            "disconnect_email",
            "delete_email_data",
        )
    },
    **{name: "capture" for name in ("capture_status", "capture_job")},
}

_HOSTED_ADMIN: frozenset[str] = frozenset(
    {
        "import_jobs",
        "import_jobs_csv",
        "discover_jobs",
        "update_source",
        "emergency_stop",
        "clear_emergency_stop",
        "reset_circuit",
        "cleanup_evidence",
        "diagnostics",
        "audit_logs",
        "refresh_company_research",
    }
)

_HOSTED_PERSONAL: frozenset[str] = frozenset(
    {
        # account
        "read_me",
        "delete_session",
        "delete_my_account",
        # profile and resumes
        "read_profile",
        "update_profile",
        "complete_onboarding",
        "upload_resume",
        "list_resumes",
        "read_resume",
        "read_parsed",
        "set_primary",
        "list_variants",
        "create_variant",
        # jobs (shared listings, per-user matches and marks)
        "score_jobs",
        "list_jobs",
        "read_job",
        "explain_job",
        "shortlist_job",
        "skip_job",
        # applications
        "prepare_application",
        "list_applications",
        "read_application",
        "record_opened",
        "update_application",
        "list_artifacts",
        "regenerate_application",
        # bulk preparation
        "preview_batch",
        "start_batch",
        "list_batches",
        "get_batch",
        "cancel_batch",
        "resume_batch",
        # auto-apply planning (runs themselves are blocked above)
        "submission_capabilities",
        "preview_run",
        "list_runs",
        "get_run",
        "pause_run",
        "cancel_run",
        "run_report",
        "preflight_run",
        "read_preferences",
        "save_preferences",
        "control_status",
        "get_attempt",
        # answers, platforms, searches
        "list_answers",
        "action_inbox",
        "save_answer",
        "delete_answer",
        "list_platforms",
        "read_platform",
        "list_searches",
        "create_search",
        "update_search",
        "delete_search",
        "preview_search",
        "run_search",
        # sources (read-only for users) and analytics over their own data
        "list_sources",
        "metrics",
        "estimated",
        "analytics",
        "duplication",
        "import_runs",
        "outcome_analytics",
        # research and interviews
        "parse_salary_text",
        "read_job_salary",
        "read_company_research",
        "read_job_company_research",
        "read_interview_prep",
        "generate_interview_prep",
        "read_next_practice_question",
        "record_practice_answer",
        "list_interview_rounds",
        "create_interview_round",
        "update_interview_round",
        "delete_interview_round",
    }
)

HOSTED_POLICY: dict[str, str] = {
    **{name: "personal" for name in _HOSTED_PERSONAL},
    **{name: "admin" for name in _HOSTED_ADMIN},
    **{name: "blocked" for name in _HOSTED_BLOCKED_GROUP},
}


def get_llm(settings: Annotated[Settings, Depends(get_app_settings)]) -> LLMProvider:
    if settings.is_multi_user:
        # Every draft would be billed to whoever runs the installation; hosted users get
        # the rule-based letter, which is checked against the same facts.
        from app.llm.null_provider import NullProvider

        return NullProvider()
    return build_provider(settings)


#: Every mutating operation in the API, classified for demo mode. The two classes differ in
#: *who pays* for the write:
#:
#: * ``DEMO_BLOCKED_REASONS`` — the cost or blast radius lands on somebody other than the
#:   visitor: a third party's API quota, the container's CPU, or a compliance setting. No
#:   session isolation makes these safe, so they are refused outright.
#: * ``DEMO_SESSION_SCOPED`` — the write only touches fictional rows and is the point of
#:   the demo, so it is allowed, but only against the visitor's *own* copy of the database
#:   (see :mod:`app.services.demo_sessions`). Without a session key it is refused, because
#:   the fallback would be the shared template that every later visitor reads.
#:
#: ``tests/test_demo_mode.py`` fails if a mutating route appears in neither set, so a new
#: endpoint cannot be added without deciding which one it belongs to.
DEMO_BLOCKED_REASONS: dict[str, str] = {
    "discovery": (
        "Running discovery calls other companies' job-board APIs. On a shared public demo "
        "that would spend somebody else's rate limit on every visitor, so it is disabled "
        "here. Run the app locally to use it."
    ),
    "job_import": (
        "Importing jobs writes arbitrary text into the demo database that every later "
        "visitor would see, so it is disabled here. Run the app locally to import your own "
        "listings."
    ),
    "batch_run": (
        "A bulk run prepares a hundred or more applications at once, which is too "
        "expensive for a shared container. Preview still works, and single preparation "
        "from the job feed still works."
    ),
    "source_config": (
        "Source capabilities are a compliance setting, not a preference, so they cannot be "
        "changed from a shared demo."
    ),
    "autoapply_run": (
        "An auto-apply run calls other companies' job-board APIs and prepares a hundred "
        "or more applications, so it is disabled on a shared container. Preview still "
        "works and shows exactly what a run would do."
    ),
    "autoapply_resume": (
        "Resuming an auto-apply run would restart the same work, so it is disabled here "
        "for the same reason as starting one."
    ),
    "email_tracking": (
        "Email tracking reads a personal mailbox. A shared public demo has no per-user "
        "login, so connecting one here would expose it to every visitor; it is disabled. "
        "Run JobOrbit locally to connect your own Gmail read-only."
    ),
    "job_capture": (
        "Capturing a job writes a listing from your browser into the database every later "
        "visitor reads, so it is disabled on the shared demo. Run JobOrbit locally and the "
        "extension sends listings to your own copy."
    ),
    "external_research": (
        "Fetching a company's website spends this container's network on every visitor's "
        "request, so it is disabled here. Research built from the listings already held "
        "still works."
    ),
    "autoapply_control": (
        "The emergency stop and evidence cleanup act on every run in the installation, not "
        "one visitor's copy, so they cannot be used from a shared demo."
    ),
    "resume_upload": (
        "This is a shared public demo, so resume upload is disabled. A deployment like "
        "this has no per-user login, which means one visitor's resume would be readable by "
        "the next. Run the app locally to use your own resume: the README has the two "
        "commands."
    ),
}

#: Writes that are allowed in the demo, each against the visitor's own database copy. The
#: value is the user-facing label shown when the write cannot be isolated.
DEMO_SESSION_SCOPED: frozenset[str] = frozenset(
    {
        "shortlist_job",
        "skip_job",
        "score_jobs",
        "prepare_application",
        "update_application",
        "record_opened",
        "save_answer",
        "delete_answer",
        "update_profile",
        "complete_onboarding",
        "create_variant",
        "set_primary",
        "create_search",
        "update_search",
        "delete_search",
        "run_search",
        "preview_batch",
        "preview_run",
        "preflight_run",
        "save_preferences",
        "regenerate_application",
        # Company research and interview preparation write only the visitor's own copy.
        # The two GETs are listed because they fill the research cache.
        "read_company_research",
        "read_job_company_research",
        "refresh_company_research",
        "generate_interview_prep",
        "record_practice_answer",
        "create_interview_round",
        "update_interview_round",
        "delete_interview_round",
        "pause_run",
        "cancel_run",
        "cancel_batch",
        "resume_batch",
    }
)

DEMO_WRITE_DISABLED_MESSAGE = (
    "This demo gives every visitor their own private copy of the sample data, and this "
    "browser session has not been given one. Reload the page to start a fresh demo "
    "session, or run JobOrbit locally where every write is yours."
)


def refuse_in_demo_mode(settings: Settings, operation: str) -> None:
    """Raise 403 when ``operation`` is not safe to expose on a shared deployment.

    Called as the first statement of the route rather than attached as a dependency, so for
    an upload it runs before ``file.file.read()`` and before :func:`store_resume`: the
    bytes are never read into memory by this application and never written to ``var/``.
    FastAPI has already spooled the request body to a temporary file by this point, which
    it discards — so this prevents retention, not receipt.
    """
    if not settings.demo_mode:
        return
    reason = DEMO_BLOCKED_REASONS.get(operation)
    if reason is None:  # pragma: no cover - guards a typo in a new call site
        raise KeyError(f"no demo-mode reason registered for operation {operation!r}")
    raise ApiError(f"demo_mode_{operation}_blocked", reason, status.HTTP_403_FORBIDDEN)


DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_app_settings)]
Profile = Annotated[CandidateProfile, Depends(get_profile)]
Llm = Annotated[LLMProvider, Depends(get_llm)]
Authorized = Depends(require_auth)
CurrentUser = Annotated[User | None, Depends(current_user)]
