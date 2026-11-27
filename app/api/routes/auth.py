"""Account endpoints for hosted (Google sign-in) mode.

Only the website's server calls these, with the service bearer token: it trades the ID
token Google gave it for a JobOrbit session (``POST /api/auth/session``), keeps that token
in an httpOnly cookie, and sends it back on every request as ``X-JobOrbit-Session``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Header, Response, status
from pydantic import BaseModel, Field

from app.api.deps import AppSettings, Authorized, CurrentUser, DbSession, Profile
from app.api.errors import ApiError
from app.services import accounts

router = APIRouter(prefix="/api/auth", tags=["accounts"], dependencies=[Authorized])


class SessionCreate(BaseModel):
    id_token: str = Field(min_length=20, max_length=8000)
    user_agent: str = Field(default="", max_length=300)


class AccountRead(BaseModel):
    auth_mode: str
    email: str = ""
    name: str = ""
    picture_url: str = ""
    is_admin: bool = False
    profile_id: int | None = None
    onboarding_completed: bool = False


class SessionRead(BaseModel):
    session_token: str
    expires_at: datetime
    is_new_user: bool
    account: AccountRead


class AccountDelete(BaseModel):
    #: The account's email, typed by the person, so a stray request cannot delete it.
    confirm_email: str = Field(min_length=3, max_length=320)


def _require_hosted(settings) -> None:
    if not settings.is_multi_user:
        raise ApiError(
            "not_hosted",
            "This JobOrbit runs locally for one person, so there is no account to sign in to.",
            status.HTTP_409_CONFLICT,
        )


def _account(settings, user, profile) -> AccountRead:
    return AccountRead(
        auth_mode=settings.auth_mode,
        email=user.email,
        name=user.name,
        picture_url=user.picture_url,
        is_admin=user.email.lower() in settings.admin_email_set,
        profile_id=profile.id,
        onboarding_completed=profile.onboarding_completed_at is not None,
    )


@router.post(
    "/session",
    response_model=SessionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Exchange a verified Google ID token for a session",
)
def create_session(
    payload: SessionCreate, session: DbSession, settings: AppSettings
) -> SessionRead:
    _require_hosted(settings)
    try:
        identity = accounts.verify_google_id_token(payload.id_token, settings.google_client_id)
        issued = accounts.sign_in(session, settings, identity, user_agent=payload.user_agent)
    except accounts.SignInError as error:
        code = (
            status.HTTP_403_FORBIDDEN
            if error.code in {"sign_ups_closed", "account_disabled"}
            else status.HTTP_401_UNAUTHORIZED
        )
        raise ApiError(error.code, error.message, code) from error
    return SessionRead(
        session_token=issued.token,
        expires_at=issued.expires_at,
        is_new_user=issued.is_new_user,
        account=_account(settings, issued.user, issued.profile),
    )


@router.get("/me", response_model=AccountRead, summary="Who this request is acting for")
def read_me(user: CurrentUser, profile: Profile, settings: AppSettings) -> AccountRead:
    if user is None:
        return AccountRead(
            auth_mode=settings.auth_mode,
            name=profile.full_name,
            email=profile.email,
            profile_id=profile.id,
            onboarding_completed=profile.onboarding_completed_at is not None,
        )
    return _account(settings, user, profile)


@router.delete(
    "/session",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Sign out this browser",
)
def delete_session(
    session: DbSession,
    settings: AppSettings,
    x_joborbit_session: Annotated[str | None, Header()] = None,
) -> Response:
    _require_hosted(settings)
    accounts.sign_out(session, x_joborbit_session or "")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/account/delete",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete this account and everything JobOrbit holds for it",
)
def delete_my_account(
    payload: AccountDelete, user: CurrentUser, session: DbSession, settings: AppSettings
) -> Response:
    _require_hosted(settings)
    if user is None:  # pragma: no cover - require_auth sets it in hosted mode
        raise ApiError("signin_required", "Sign in first.", status.HTTP_401_UNAUTHORIZED)
    if payload.confirm_email.strip().lower() != user.email.lower():
        raise ApiError(
            "confirmation_mismatch",
            "Type your account's email address exactly to confirm deletion.",
            status.HTTP_400_BAD_REQUEST,
        )
    accounts.delete_account(session, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
