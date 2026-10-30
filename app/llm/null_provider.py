"""The default provider: no LLM at all.

:class:`NullProvider` reports itself unavailable and raises on use. Callers must therefore
have a rule-based path, and because this is the default in tests and in a fresh install,
that path is the one that is actually exercised.
"""

from __future__ import annotations

from app.llm.base import LLMProvider, LLMResponse, LLMUnavailable


class NullProvider(LLMProvider):
    name = "none"
    model = "none"

    @property
    def available(self) -> bool:
        return False

    def complete(self, system: str, user: str, *, max_tokens: int = 800) -> LLMResponse:
        raise LLMUnavailable(
            "No LLM provider is configured. Set JA_LLM_PROVIDER and JA_LLM_API_KEY to "
            "enable AI drafting; all core features work without it."
        )

    def __repr__(self) -> str:
        return "NullProvider()"


class EchoProvider(LLMProvider):
    """A provider used only by tests that need an 'available' provider without network."""

    name = "echo"
    model = "echo"

    def __init__(self, reply: str = "") -> None:
        self._reply = reply

    @property
    def available(self) -> bool:
        return True

    def complete(self, system: str, user: str, *, max_tokens: int = 800) -> LLMResponse:
        return LLMResponse(
            text=self._reply or user[:max_tokens], provider=self.name, model=self.model
        )
