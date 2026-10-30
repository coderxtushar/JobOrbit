"""Source adapter contract.

Every discovery or import path in the application goes through a :class:`SourceAdapter`.
An adapter declares what it is *permitted* to do via :class:`AdapterCapabilities`, and the
pipeline refuses to call an operation the adapter has not declared. An adapter that cannot
perform discovery raises :class:`CapabilityNotAvailable` with the policy reason, which is
surfaced verbatim on the diagnostics page — it never returns an empty list pretending to
have searched, and it never returns invented listings.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.db.models import SourceName
from app.schemas.job import RawJobRecord


@dataclass(frozen=True, slots=True)
class AdapterCapabilities:
    """What an adapter may do, grounded in the platform's published policy."""

    manual_import_enabled: bool = True
    authorized_discovery_enabled: bool = False
    browser_assistance_enabled: bool = False
    automated_submission_enabled: bool = False

    def __post_init__(self) -> None:
        if self.automated_submission_enabled:
            raise ValueError(
                "automated_submission_enabled must stay False: automated application "
                "submission is prohibited by every platform in scope"
            )

    def as_dict(self) -> dict[str, bool]:
        return {
            "manual_import_enabled": self.manual_import_enabled,
            "authorized_discovery_enabled": self.authorized_discovery_enabled,
            "browser_assistance_enabled": self.browser_assistance_enabled,
            "automated_submission_enabled": False,
        }


class CapabilityNotAvailable(RuntimeError):
    """Raised when an operation is not permitted or not possible for a source.

    The message is user-facing and must state the policy reason, not a generic failure.
    """

    def __init__(self, source: SourceName, capability: str, reason: str) -> None:
        super().__init__(reason)
        self.source = source
        self.capability = capability
        self.reason = reason


class SourceUnavailable(RuntimeError):
    """Raised for a transient failure (timeout, network error, rate limit).

    Distinct from :class:`CapabilityNotAvailable`: this one is worth retrying.
    """

    def __init__(self, source: SourceName, reason: str, retryable: bool = True) -> None:
        super().__init__(reason)
        self.source = source
        self.reason = reason
        self.retryable = retryable


@dataclass(slots=True)
class DiscoveryResult:
    """Records returned by an adapter, plus what went wrong while fetching them."""

    records: list[RawJobRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    invalid_count: int = 0
    metadata: dict[str, object] = field(default_factory=dict)


class SourceAdapter(ABC):
    """Base class for every job source."""

    source: SourceName
    display_name: str
    capabilities: AdapterCapabilities
    policy_basis: str
    limitations: tuple[str, ...] = ()

    @abstractmethod
    def discover(self, *, query: dict[str, object] | None = None) -> DiscoveryResult:
        """Fetch jobs through an authorized interface.

        Adapters without ``authorized_discovery_enabled`` must raise
        :class:`CapabilityNotAvailable`.
        """

    def import_payload(self, payload: bytes, filename: str = "") -> DiscoveryResult:
        """Parse a user-supplied export for this source.

        The default implementation delegates to the generic manual importer, which accepts
        the same JSON and CSV shapes for every source.
        """
        from app.sources.manual_import import parse_payload

        if not self.capabilities.manual_import_enabled:
            raise CapabilityNotAvailable(
                self.source, "manual_import", f"{self.display_name} imports are disabled"
            )
        return parse_payload(payload, filename=filename, default_source=self.source)

    def health(self) -> tuple[bool, str]:
        """Return (healthy, reason). 'Healthy' means the adapter can do something useful."""
        if self.capabilities.authorized_discovery_enabled:
            return True, "authorized discovery is available"
        if self.capabilities.manual_import_enabled:
            return True, "manual import is available; automated discovery is not permitted"
        return False, "no permitted access method is available for this source"


class ImportOnlyAdapter(SourceAdapter):
    """An adapter for a platform that permits import but not automated discovery.

    Used for every external job board in this build. ``discover`` always raises with the
    documented reason rather than returning a fabricated result set.
    """

    def discover(self, *, query: dict[str, object] | None = None) -> DiscoveryResult:
        raise CapabilityNotAvailable(
            self.source,
            "authorized_discovery",
            f"{self.display_name} does not offer an authorized job-search interface for "
            f"individual jobseekers in this build. {self.policy_basis} "
            "Use manual import, a CSV export, or email job-alert ingestion instead.",
        )
