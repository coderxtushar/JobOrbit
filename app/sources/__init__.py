"""Job sources. Every acquisition path is a :class:`~app.sources.base.SourceAdapter`."""

from app.sources.base import (
    AdapterCapabilities,
    CapabilityNotAvailable,
    DiscoveryResult,
    ImportOnlyAdapter,
    SourceAdapter,
    SourceUnavailable,
)
from app.sources.registry import (
    ALL_SOURCES,
    DISCOVERY_SOURCES,
    all_adapters,
    default_configuration,
    effective_capabilities,
    get_adapter,
    unsupported_requests,
)

__all__ = [
    "ALL_SOURCES",
    "AdapterCapabilities",
    "CapabilityNotAvailable",
    "DISCOVERY_SOURCES",
    "DiscoveryResult",
    "ImportOnlyAdapter",
    "SourceAdapter",
    "SourceUnavailable",
    "all_adapters",
    "default_configuration",
    "effective_capabilities",
    "get_adapter",
    "unsupported_requests",
]
