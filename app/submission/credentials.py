"""Where submission credentials may come from, and where they may not.

One function, :func:`resolve`, and a short list of rules it enforces:

* **Process environment only.** A credential is read from the environment at the moment it
  is used. It is never written to the database, never stored in ``var/``, and never
  returned in an API response.
* **Nothing is persisted.** :class:`Credential` is not an ORM model and has no table.
  There is deliberately no ``save`` anywhere in this module, because a credential that is
  never stored cannot be leaked by a backup, a migration dump or a redeployed container.
* **Never logged.** :meth:`Credential.redacted` is the only representation that may reach
  a log line or a screen, and it reveals the length and the last two characters, which is
  enough to tell two keys apart without disclosing either.
* **Loopback-bound providers may hold no secret at all.** The one provider this build
  submits to is a local test server, so the "credential" is a token this project
  generates for itself.

What this module does *not* do is store a platform password or a session cookie. Neither
is ever accepted, because the compliant way to reach a platform account is the user
signing in themselves in their own browser.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

#: Environment variable prefix. A provider ``foo`` reads ``JA_SUBMISSION_FOO_TOKEN``.
_PREFIX = "JA_SUBMISSION_"

#: Substrings that must never appear in a credential variable name. These name things
#: this project refuses to hold: a platform account password, or a captured session.
_REFUSED_FRAGMENTS: frozenset[str] = frozenset({"password", "passwd", "cookie", "session_id"})


class CredentialRefused(ValueError):
    """Raised when a credential of a kind this project will not hold is requested."""


@dataclass(frozen=True, slots=True)
class Credential:
    """A secret held for the lifetime of one call, never written anywhere."""

    provider: str
    token: str

    @property
    def present(self) -> bool:
        return bool(self.token.strip())

    def redacted(self) -> str:
        """The only form safe to log or display."""
        if not self.present:
            return "(not set)"
        tail = self.token[-2:] if len(self.token) > 6 else ""
        return f"***{tail} ({len(self.token)} chars)"

    def __repr__(self) -> str:
        """Redact in the default representation too.

        Without this an exception traceback or a debugger frame would print the secret,
        which is the most common way a credential reaches a log file in practice.
        """
        return f"Credential(provider={self.provider!r}, token={self.redacted()!r})"

    __str__ = __repr__


def variable_name(provider: str) -> str:
    return f"{_PREFIX}{provider.strip().upper().replace('-', '_')}_TOKEN"


def resolve(provider: str) -> Credential:
    """Read a provider's credential from the process environment.

    Returns an empty :class:`Credential` when none is set, rather than raising: a provider
    that needs no credential is the normal case, and the adapter is what decides whether
    an absent one is a problem.
    """
    name = variable_name(provider)
    lowered = name.lower()
    for fragment in _REFUSED_FRAGMENTS:
        if fragment in lowered:
            raise CredentialRefused(
                f"{name} names a {fragment}, which this project never stores. Sign in to "
                "the platform yourself in your own browser instead."
            )
    return Credential(provider=provider, token=os.environ.get(name, ""))


def describe_all(providers: list[str]) -> dict[str, str]:
    """Redacted presence report for a diagnostics screen. Never returns a token."""
    report: dict[str, str] = {}
    for provider in providers:
        try:
            report[provider] = resolve(provider).redacted()
        except CredentialRefused as error:
            report[provider] = f"refused: {error}"
    return report


__all__ = ["Credential", "CredentialRefused", "describe_all", "resolve", "variable_name"]
