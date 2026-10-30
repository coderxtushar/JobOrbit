"""Request dependencies."""

from __future__ import annotations

import hmac
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, status
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.config import Settings, get_settings
from app.db.base import get_session_factory
from app.db.models import CandidateProfile
from app.db.repositories import ProfileRepository
from app.llm.base import LLMProvider
from app.llm.factory import build_provider


def get_db() -> Iterator[Session]:
    """Per-request transactional session."""
    session = get_session_factory()()
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


DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_app_settings)]
Profile = Annotated[CandidateProfile, Depends(get_profile)]
Llm = Annotated[LLMProvider, Depends(get_llm)]
Authorized = Depends(require_auth)
