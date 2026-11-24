"""Redaction of personal data before it reaches a log line or an event record.

Submission events, logs and error strings are written from places that hold the user's
email address, phone number and answers. Rather than trusting every call site to leave
them out, text passes through :func:`redact` on the way to storage. It removes what can be
recognised mechanically — email addresses, phone numbers, bearer tokens, OAuth codes,
API keys and URL query strings that carry tokens — and the profile's own identifiers when
they are supplied.

It is a safety net, not permission to log personal data: callers still write the least
they can.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
#: International or Indian phone numbers: optional +CC, then 9-12 digits with separators.
_PHONE = re.compile(
    r"(?<![\w/.-])(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,5}\)?[\s.-]?){2,4}\d{2,5}(?![\w/-])"
)
_BEARER = re.compile(
    r"(?i)\b(bearer|token|authorization|api[_-]?key|password|secret)(?:\s*[:=]\s*|\s+)"
    r"[A-Za-z0-9._~+/-]{8,}=*"
)
_SECRET_PARAM = re.compile(
    r"(?i)([?&](?:code|token|access_token|refresh_token|id_token|key|api_key|apikey|"
    r"secret|password|pwd|sig|signature|state)=)[^&#\s]+"
)
_LONG_SECRET = re.compile(r"\b(?:sk|ya29|ghp|gho|xox[abp])[-_.][A-Za-z0-9._-]{16,}\b")

PLACEHOLDER_EMAIL = "[email]"
PLACEHOLDER_PHONE = "[phone]"
PLACEHOLDER_SECRET = "[redacted]"


def _digits(value: str) -> int:
    return sum(character.isdigit() for character in value)


def redact(text: str, *, extra: Iterable[str] = ()) -> str:
    """Return ``text`` with personal identifiers and secrets replaced by placeholders.

    ``extra`` holds exact strings to remove as well, such as the profile's full name; each
    must be at least four characters so a short value cannot blank out ordinary words.
    """
    if not text:
        return ""
    result = _SECRET_PARAM.sub(lambda match: match.group(1) + PLACEHOLDER_SECRET, text)
    result = _BEARER.sub(lambda match: f"{match.group(1)} {PLACEHOLDER_SECRET}", result)
    result = _LONG_SECRET.sub(PLACEHOLDER_SECRET, result)
    result = _EMAIL.sub(PLACEHOLDER_EMAIL, result)
    result = _PHONE.sub(
        lambda match: PLACEHOLDER_PHONE if 9 <= _digits(match.group(0)) <= 15 else match.group(0),
        result,
    )
    for value in extra:
        value = (value or "").strip()
        if len(value) >= 4:
            result = re.sub(re.escape(value), "[profile]", result, flags=re.IGNORECASE)
    return result


def mask_value(value: str) -> str:
    """Keep only enough of a sensitive answer to recognise it: its length and first letter."""
    value = (value or "").strip()
    if not value:
        return ""
    return f"{value[0]}… ({len(value)} chars, masked)"


class RedactingFilter(logging.Filter):
    """Logging filter that redacts the formatted message and string ``extra`` fields."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a bad format string must not drop the record
            return True
        record.msg = redact(message)
        record.args = ()
        for key, value in list(record.__dict__.items()):
            if key in {"reason", "detail", "error", "url", "message_text"} and isinstance(
                value, str
            ):
                setattr(record, key, redact(value))
        return True


__all__ = ["PLACEHOLDER_EMAIL", "PLACEHOLDER_PHONE", "RedactingFilter", "mask_value", "redact"]
