"""Accounts for hosted (Google sign-in) mode: verified identity, sessions, deletion.

The website never hands the API a claim of who someone is. It hands over the ID token
Google signed, and this module checks it itself: the signature against Google's published
keys, the issuer, the audience (this installation's client id), expiry, and that Google
verified the email. Only then is a session created.

A session token is 32 random bytes shown once to the website, which keeps it in an
httpOnly cookie. The database stores its SHA-256, so a copy of the database cannot be
replayed as anyone's session.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import jwt
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import CandidateProfile, User, UserSession, utcnow
from app.logging_conf import get_logger

logger = get_logger(__name__)

GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")
#: How stale ``last_seen_at`` may get before a request refreshes it (saves a write a call).
_SEEN_REFRESH = timedelta(minutes=10)

_jwks_client: jwt.PyJWKClient | None = None


class SignInError(Exception):
    """The sign-in was refused; ``code`` is stable, ``message`` is shown to the person."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    subject: str
    email: str
    name: str
    picture_url: str


@dataclass(frozen=True, slots=True)
class IssuedSession:
    token: str
    expires_at: datetime
    user: User
    profile: CandidateProfile
    is_new_user: bool


def _signing_key(id_token: str) -> Any:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(GOOGLE_CERTS_URL, cache_keys=True, lifespan=3600)
    return _jwks_client.get_signing_key_from_jwt(id_token).key


def verify_google_id_token(
    id_token: str, client_id: str, *, key: Any | None = None
) -> GoogleIdentity:
    """Check an ID token exactly as Google documents; ``key`` is injectable for tests."""
    try:
        claims = jwt.decode(
            id_token,
            key if key is not None else _signing_key(id_token),
            algorithms=["RS256"],
            audience=client_id,
            issuer=GOOGLE_ISSUERS,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            leeway=30,
        )
    except jwt.PyJWTError as error:
        raise SignInError(
            "invalid_id_token", f"Google's sign-in could not be verified ({type(error).__name__})."
        ) from error
    except Exception as error:  # noqa: BLE001 - key fetch failures surface as one refusal
        raise SignInError(
            "google_keys_unavailable", "Google's signing keys could not be fetched; try again."
        ) from error
    email = str(claims.get("email") or "").strip().lower()
    if not email or claims.get("email_verified") is not True:
        raise SignInError(
            "email_not_verified", "Google has not verified this account's email address."
        )
    return GoogleIdentity(
        subject=str(claims["sub"]),
        email=email,
        name=str(claims.get("name") or "")[:200],
        picture_url=str(claims.get("picture") or "")[:1000],
    )


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def profile_for(session: Session, user: User) -> CandidateProfile:
    """The user's own profile, created on first use and pre-filled from Google."""
    profile = session.scalars(
        select(CandidateProfile).where(CandidateProfile.user_id == user.id)
    ).first()
    if profile is None:
        profile = CandidateProfile(user_id=user.id, full_name=user.name, email=user.email)
        session.add(profile)
        session.flush()
    return profile


def sign_in(
    session: Session,
    settings: Settings,
    identity: GoogleIdentity,
    *,
    user_agent: str = "",
) -> IssuedSession:
    """Find or create the user, then issue a new session for this browser."""
    user = session.scalars(select(User).where(User.google_sub == identity.subject)).first()
    is_new = user is None
    if user is None:
        existing = int(session.scalar(select(func.count(User.id))) or 0)
        if existing >= settings.max_users:
            raise SignInError(
                "sign_ups_closed",
                "JobOrbit has reached its account limit for now, so new sign-ups are paused.",
            )
        user = User(google_sub=identity.subject, email=identity.email)
        session.add(user)
    if user.is_disabled:
        raise SignInError("account_disabled", "This account has been disabled.")
    user.email = identity.email
    user.name = identity.name or user.name
    user.picture_url = identity.picture_url or user.picture_url
    user.last_login_at = utcnow()
    session.flush()
    profile = profile_for(session, user)

    token = secrets.token_urlsafe(32)
    expires_at = utcnow() + timedelta(days=settings.session_days)
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=expires_at,
            user_agent=user_agent[:300],
        )
    )
    session.flush()
    logger.info("signed in", extra={"detail": f"user {user.id}", "new": is_new})
    return IssuedSession(
        token=token, expires_at=expires_at, user=user, profile=profile, is_new_user=is_new
    )


def user_for_session(session: Session, token: str) -> User | None:
    """The live, enabled user a session token belongs to, or ``None``."""
    if not token or len(token) > 200:
        return None
    row = session.scalars(
        select(UserSession).where(UserSession.token_hash == hash_token(token))
    ).first()
    now = utcnow()
    if row is None or row.expires_at <= now:
        return None
    user = session.get(User, row.user_id)
    if user is None or user.is_disabled:
        return None
    if now - row.last_seen_at > _SEEN_REFRESH:
        row.last_seen_at = now
        session.flush()
    return user


def sign_out(session: Session, token: str) -> bool:
    result = session.execute(delete(UserSession).where(UserSession.token_hash == hash_token(token)))
    session.flush()
    return bool(result.rowcount)


def delete_account(session: Session, user: User) -> None:
    """Delete the user, their profile and everything derived from it.

    The profile's foreign keys cascade to resumes, matches, applications (and their
    answers, artifacts and events), saved answers, searches, batches, auto-apply runs and
    per-user job marks. Jobs themselves are shared and stay.
    """
    profile = session.scalars(
        select(CandidateProfile).where(CandidateProfile.user_id == user.id)
    ).first()
    if profile is not None:
        session.delete(profile)
        session.flush()
    session.execute(delete(UserSession).where(UserSession.user_id == user.id))
    session.delete(user)
    session.flush()
    logger.info("account deleted", extra={"detail": f"user {user.id}"})


def purge_expired_sessions(session: Session) -> int:
    result = session.execute(delete(UserSession).where(UserSession.expires_at <= utcnow()))
    return int(result.rowcount or 0)
