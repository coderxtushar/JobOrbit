"""URL validation.

Imported job records carry URLs that the dashboard turns into clickable links and that the
"open the application page" action hands to the operating system. An unchecked URL there is
a real attack surface: ``javascript:`` and ``file:`` links, credentials embedded in the
authority, and loopback/metadata addresses that would make the local machine the target.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ALLOWED_SCHEMES = frozenset({"http", "https"})

_BLOCKED_HOST_SUFFIXES = (".localhost", ".internal", ".local")
_BLOCKED_HOSTNAMES = frozenset({"localhost", "metadata.google.internal", "instance-data"})

_TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "refid",
        "ref",
        "trk",
        "trackingid",
        "originalsubdomain",
        "gclid",
        "fbclid",
        "src",
        "source",
        "position",
        "pagenum",
        "eboost",
        "fromjob",
    }
)


@dataclass(frozen=True, slots=True)
class UrlVerdict:
    safe: bool
    reason: str = ""
    normalized: str = ""


def inspect_url(raw: str) -> UrlVerdict:
    """Classify a URL as safe-to-link or not, with a reason when it is not."""
    candidate = (raw or "").strip()
    if not candidate:
        return UrlVerdict(False, "empty url")
    if len(candidate) > 1200:
        return UrlVerdict(False, "url exceeds 1200 characters")

    try:
        parts = urlsplit(candidate)
    except ValueError as exc:
        return UrlVerdict(False, f"unparseable url: {exc}")

    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        return UrlVerdict(False, f"scheme '{scheme or 'missing'}' is not http or https")
    if parts.username or parts.password:
        return UrlVerdict(False, "credentials embedded in url")

    host = (parts.hostname or "").lower()
    if not host:
        return UrlVerdict(False, "url has no host")
    if host in _BLOCKED_HOSTNAMES or host.endswith(_BLOCKED_HOST_SUFFIXES):
        return UrlVerdict(False, f"host '{host}' is a local or internal name")

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and (
        address.is_loopback or address.is_private or address.is_link_local or address.is_reserved
    ):
        return UrlVerdict(False, f"host '{host}' is a private or loopback address")

    return UrlVerdict(True, normalized=canonicalize_url(candidate))


def is_safe_url(raw: str) -> bool:
    return inspect_url(raw).safe


def canonicalize_url(raw: str) -> str:
    """Produce a stable URL for duplicate detection.

    Lowercases the host, drops the fragment, removes tracking parameters and sorts the
    remainder, so the same posting shared with different campaign tags collapses to one key.
    """
    candidate = (raw or "").strip()
    if not candidate:
        return ""
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return ""
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        return ""

    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    netloc = host
    if parts.port and parts.port not in (80, 443):
        netloc = f"{host}:{parts.port}"

    path = parts.path.rstrip("/") or "/"
    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=False)
        if key.lower() not in _TRACKING_PARAMS
    ]
    query = urlencode(sorted(kept))
    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))
