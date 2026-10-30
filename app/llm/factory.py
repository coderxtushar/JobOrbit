"""Provider selection.

A misconfigured LLM must never break the application, so construction failures are logged
and downgraded to :class:`NullProvider` rather than raised.
"""

from __future__ import annotations

from app.config import Settings, get_settings
from app.llm.base import LLMProvider, LLMUnavailable
from app.llm.null_provider import NullProvider
from app.logging_conf import get_logger

logger = get_logger(__name__)


def build_provider(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    if settings.llm_provider == "none":
        return NullProvider()
    if not settings.llm_api_key:
        logger.warning(
            "llm provider selected without an api key; falling back to rule-based generation",
            extra={"provider": settings.llm_provider},
        )
        return NullProvider()

    from app.llm.openai_provider import OpenAIProvider

    try:
        return OpenAIProvider(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_seconds,
        )
    except LLMUnavailable as exc:
        logger.warning(
            "llm provider unavailable, using rule-based generation", extra={"reason": str(exc)}
        )
        return NullProvider()
