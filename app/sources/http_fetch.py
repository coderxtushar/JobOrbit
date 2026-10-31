"""One HTTP fetch path for every automated-discovery adapter.

Shared by the per-company ATS board adapters and the open job-feed adapters so that
timeout, bounded retry, backoff and error-message behaviour cannot drift between them.
Nothing here follows redirects to a different scheme, sends credentials, or retries
forever: the attempt count is bounded by configuration.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import requests
from pydantic import ValidationError

from app.schemas.job import RawJobRecord

USER_AGENT = "job-search-assistant/1.0 (personal jobseeker tool; one user)"

#: HTTP statuses worth another attempt. A 404 means the board identifier is wrong, which
#: retrying cannot fix, so it is reported against that board and the run continues.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

_MAX_BACKOFF_SECONDS = 8.0

#: Display fields whose length limit is a storage detail, not a correctness requirement.
#: ``url`` is deliberately absent: a clipped URL is a broken link, so an over-long URL
#: skips that one posting instead.
_CLIPPED_FIELDS: dict[str, int] = {
    "external_id": 300,
    "title": 400,
    "company": 300,
    "location": 300,
    "salary_raw": 200,
    "experience_raw": 200,
}


def build_record(**fields: Any) -> RawJobRecord | None:
    """Build one record, clipping over-long display fields, or ``None`` if it is unusable.

    A board occasionally carries a single pathological posting — Greenhouse's databricks
    board lists one role whose location is a 300-plus character list of US states. Letting
    that raise discarded the *entire* company board, losing every other posting from it,
    because a parse failure is reported per board rather than per row. Clipping the display
    fields removes that cause, and returning ``None`` keeps any remaining surprise confined
    to the one posting that caused it.
    """
    for name, limit in _CLIPPED_FIELDS.items():
        value = fields.get(name)
        if isinstance(value, str) and len(value) > limit:
            fields[name] = value[:limit].rstrip()
    try:
        return RawJobRecord(**fields)
    except ValidationError:
        return None


def usable_records(
    records: list[RawJobRecord | None], skipped: int
) -> tuple[list[RawJobRecord], int]:
    """Drop the postings :func:`build_record` could not build, counting them as skipped."""
    usable = [record for record in records if record is not None]
    return usable, skipped + len(records) - len(usable)


@dataclass(slots=True)
class BoardFetch:
    """Outcome of fetching one URL: either a decoded payload or a human-readable error."""

    board: str
    payload: Any
    error: str = ""


def fetch_json(
    url: str,
    *,
    board: str,
    display_name: str,
    timeout_seconds: int,
    max_attempts: int,
) -> BoardFetch:
    """GET one JSON document, retrying only statuses that a retry could fix."""
    attempts = max(1, max_attempts)
    delay = 1.0
    last = ""
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(
                url,
                timeout=timeout_seconds,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
        except requests.RequestException as exc:
            last = f"{type(exc).__name__}: {exc}"
        else:
            if response.status_code == 404:
                return BoardFetch(
                    board,
                    None,
                    f"'{board}' is not a board on {display_name} (HTTP 404). "
                    "Check the identifier in the company's careers-page URL.",
                )
            if response.status_code in RETRYABLE_STATUS:
                last = f"HTTP {response.status_code}"
            elif not response.ok:
                return BoardFetch(board, None, f"HTTP {response.status_code}")
            else:
                try:
                    return BoardFetch(board, response.json())
                except ValueError:
                    return BoardFetch(
                        board, None, "the response was not valid JSON and was discarded"
                    )
        if attempt < attempts:
            time.sleep(delay)
            delay = min(delay * 2, _MAX_BACKOFF_SECONDS)
    return BoardFetch(board, None, f"gave up after {attempts} attempt(s): {last}")


def parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_epoch_millis(value: Any) -> datetime | None:
    return _parse_epoch(value, divisor=1000.0)


def parse_epoch_seconds(value: Any) -> datetime | None:
    return _parse_epoch(value, divisor=1.0)


def _parse_epoch(value: Any, *, divisor: float) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(float(value) / divisor, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
