"""Structured logging.

Logs are emitted as single-line JSON so they can be grepped or piped into any log tool.
Two properties are enforced here rather than left to call sites:

* Known secret-bearing keys are redacted.
* Long free-text values are truncated, so a full resume or job description can never be
  dumped into a log file by accident.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

_REDACTED = "***redacted***"
_SECRET_KEY_FRAGMENTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "session",
)
_MAX_VALUE_CHARS = 300
_STANDARD_RECORD_KEYS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()) | {
    "message",
    "asctime",
    "taskName",
}


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in _SECRET_KEY_FRAGMENTS)


def scrub(value: Any, _depth: int = 0) -> Any:
    """Recursively redact secrets and truncate long text."""
    if _depth > 6:
        return "<max-depth>"
    if isinstance(value, dict):
        return {
            key: (_REDACTED if _is_secret_key(str(key)) else scrub(item, _depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, list | tuple | set):
        return [scrub(item, _depth + 1) for item in list(value)[:50]]
    if isinstance(value, str) and len(value) > _MAX_VALUE_CHARS:
        return value[:_MAX_VALUE_CHARS] + f"...<truncated {len(value) - _MAX_VALUE_CHARS} chars>"
    if isinstance(value, int | float | bool) or value is None:
        return value
    if isinstance(value, str):
        return value
    return scrub(str(value), _depth + 1)


class JsonFormatter(logging.Formatter):
    """Render a log record as one line of JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": scrub(record.getMessage()),
        }
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_RECORD_KEYS and not key.startswith("_")
        }
        if extras:
            payload["context"] = scrub(extras)
        if record.exc_info:
            payload["error"] = {
                "type": getattr(record.exc_info[0], "__name__", "Exception"),
                "detail": scrub(str(record.exc_info[1])),
            }
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger exactly once."""
    root = logging.getLogger()
    root.setLevel(level)
    for existing in list(root.handlers):
        root.removeHandler(existing)
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    # Uvicorn's access log duplicates our request logging and leaks query strings.
    logging.getLogger("uvicorn.access").setLevel("WARNING")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
