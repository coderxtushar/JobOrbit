"""OpenAI and OpenAI-compatible provider.

The ``openai`` package is an optional extra. It is imported inside the constructor so that
importing this module never fails on an install that chose not to use an LLM.
"""

from __future__ import annotations

from app.llm.base import LLMProvider, LLMResponse, LLMUnavailable


class OpenAIProvider(LLMProvider):
    """Chat-completions provider for OpenAI or any OpenAI-compatible endpoint."""

    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = "",
        timeout: int = 60,
    ) -> None:
        if not api_key:
            raise LLMUnavailable("an API key is required for the OpenAI provider")
        self.model = model
        self._timeout = timeout
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LLMUnavailable(
                "the 'openai' package is not installed; run "
                "`pip install -e '.[llm]'` or set JA_LLM_PROVIDER=none"
            ) from exc

        kwargs: dict[str, object] = {"api_key": api_key, "timeout": timeout}
        if base_url:
            kwargs["base_url"] = base_url
            self.name = "openai_compatible"
        self._client = OpenAI(**kwargs)

    @property
    def available(self) -> bool:
        return True

    def complete(self, system: str, user: str, *, max_tokens: int = 800) -> LLMResponse:
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=0.3,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except Exception as exc:
            raise LLMUnavailable(f"the LLM request failed: {type(exc).__name__}") from exc

        choice = response.choices[0] if response.choices else None
        text = (choice.message.content or "").strip() if choice else ""
        if not text:
            raise LLMUnavailable("the LLM returned an empty response")
        return LLMResponse(
            text=text,
            provider=self.name,
            model=self.model,
            truncated=bool(choice and choice.finish_reason == "length"),
        )
