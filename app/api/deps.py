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
from app.db.models import CandidateProfile
from app.db.repositories import ProfileRepository
from app.llm.base import LLMProvider
from app.llm.factory import build_provider
from app.services.demo_sessions import get_store as get_demo_store

DEMO_SESSION_HEADER = "X-Demo-Session"


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


def require_auth(
    settings: Annotated[Settings, Depends(get_app_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Enforce a bearer token whenever one is configured.

    A token is mandatory when the API is not bound to loopback (enforced in
    :class:`~app.config.Settings`), and optional but honoured when it is.
    """
    if not settings.api_token:
        return
    expected = f"Bearer {settings.api_token}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise ApiError(
            "unauthorized",
            "A valid bearer token is required.",
            status.HTTP_401_UNAUTHORIZED,
        )


def get_profile(session: Annotated[Session, Depends(get_db)]) -> CandidateProfile:
    """The single local user's profile, created on first use."""
    return ProfileRepository(session).get_or_create_default()


def get_llm(settings: Annotated[Settings, Depends(get_app_settings)]) -> LLMProvider:
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
        "save_answer",
        "delete_answer",
        "update_profile",
        "create_variant",
        "set_primary",
        "create_search",
        "update_search",
        "delete_search",
        "run_search",
        "preview_batch",
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
