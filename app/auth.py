"""Identity boundary, prepared but not enabled.

The app is single-user and local-first: there is one :class:`~app.db.models.CandidateProfile`
and every request acts as its owner. This module names that assumption explicitly so that
adding real sign-in later is a change of provider rather than a change of every route.

**Nothing here authenticates anything today.** :class:`LocalOwnerProvider` returns the same
principal for every request, which is correct for a process bound to loopback and wrong for
anything else. The deployment-time protection is elsewhere and unchanged:

* a bearer token is mandatory when the API is not bound to loopback
  (:class:`~app.config.Settings` refuses to start otherwise);
* ``JA_DEMO_MODE`` replaces the data and refuses the writes that would leak or cost.

What a real provider must add, in this order:

1. A ``user`` table, and a ``user_id`` foreign key on ``candidate_profile``, ``resume``,
   ``job_match``, ``application`` and ``saved_answer``. Jobs can stay shared; everything
   derived from a person cannot.
2. ``current_principal`` resolved from a verified OIDC ID token, not from a header the
   client controls.
3. Authorization in the repository layer, so a query cannot return another user's rows
   even if a route forgets to filter.
4. Per-user artifact paths under ``var/`` with the owner in the key.

Until all four exist, a shared deployment must stay in demo mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

#: The principal every request runs as while the app is single-user. Chosen to be obviously
#: not an email address, so it can never collide with a real OIDC subject later.
LOCAL_OWNER_ID = "local-owner"


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """Who a request is acting as.

    ``is_authenticated`` is ``False`` for the local owner on purpose: no credential was
    presented and none was checked. A future provider sets it ``True`` only after verifying
    an ID token signature, so no code path can mistake "there is a user object" for
    "somebody proved who they are".
    """

    subject: str
    display_name: str
    email: str = ""
    is_authenticated: bool = False

    @property
    def is_local_owner(self) -> bool:
        return self.subject == LOCAL_OWNER_ID


LOCAL_OWNER = CurrentUser(
    subject=LOCAL_OWNER_ID,
    display_name="You",
    is_authenticated=False,
)


@runtime_checkable
class AuthProvider(Protocol):
    """Resolves a request to a principal. One implementation exists and it checks nothing."""

    name: str

    def current_user(self) -> CurrentUser: ...

    def login_url(self, *, redirect_to: str = "") -> str:
        """Where to send somebody to sign in, or "" when sign-in does not exist."""
        ...


class LocalOwnerProvider:
    """Every request is the single local user. Valid only on loopback or in demo mode."""

    name = "local"

    def current_user(self) -> CurrentUser:
        return LOCAL_OWNER

    def login_url(self, *, redirect_to: str = "") -> str:
        return ""


def get_auth_provider() -> AuthProvider:
    """The active provider.

    A single hard-coded return, not a registry keyed off configuration: an env var that
    silently selects an unimplemented provider is a worse failure than having no choice at
    all. Adding Google OIDC means adding the class and changing this line.
    """
    return LocalOwnerProvider()
