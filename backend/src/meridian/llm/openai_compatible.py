"""The OpenAI-compatible adapter (ADR 0004).

This is the only module in the repository permitted to import the `openai`
package, and `test_import_boundary.py` enforces that. The SDK is imported inside
the method that needs it, so importing this module -- which the provider
registry does at startup -- costs nothing and works with no credentials present.

"OpenAI-compatible" rather than "OpenAI" is deliberate. The same wire format is
served by OpenRouter, Azure OpenAI, Together, and a local vLLM or Ollama
endpoint, and this project reaches Anthropic's models through OpenRouter. The
only difference is the base URL and the model slug, so both are configuration
rather than separate adapters.
"""

from typing import Any

from meridian.llm.base import (
    GenerationError,
    GenerationRequest,
    ProviderNotConfiguredError,
    Usage,
)

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"
DEFAULT_TIMEOUT_SECONDS = 60.0


class OpenAICompatibleGenerator:
    """Structured generation over any OpenAI-compatible chat completions API."""

    def __init__(
        self,
        api_key: str | None,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        client: Any | None = None,
    ) -> None:
        if client is None and not api_key:
            raise ProviderNotConfiguredError(
                "no API key configured; set MERIDIAN_LLM_API_KEY to enable model-backed features"
            )
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._client = client

    @property
    def model_name(self) -> str:
        """Return the model slug this generator will call."""

        return self._model

    @property
    def base_url(self) -> str:
        """Return the endpoint this generator will call."""

        return self._base_url

    def _ensure_client(self) -> Any:
        """Return the SDK client, constructing it on first use.

        Raises:
            ProviderNotConfiguredError: If the SDK is not installed.
        """

        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as error:  # pragma: no cover - dependency is declared
                raise ProviderNotConfiguredError(
                    "the openai package is not installed; run `make setup`"
                ) from error
            self._client = OpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            )
        return self._client

    def complete_json(self, request: GenerationRequest) -> tuple[str, Usage]:
        """Ask the provider for schema-constrained JSON.

        Validation is not done here. `generate_structured` owns it, so a model
        that ignores the schema fails the same way whichever provider served it.

        Raises:
            GenerationError: If the provider errors or returns empty content.
        """

        client = self._ensure_client()
        try:
            completion = client.chat.completions.create(
                model=self._model,
                temperature=request.temperature,
                max_tokens=request.max_output_tokens,
                messages=[
                    {"role": "system", "content": request.instructions},
                    {"role": "user", "content": request.input_text},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": request.schema_name,
                        "schema": request.json_schema,
                        "strict": True,
                    },
                },
            )
        except Exception as error:
            raise GenerationError(
                f"{self._model} request failed: {type(error).__name__}"
            ) from error

        choices = getattr(completion, "choices", None)
        if not choices:
            raise GenerationError(f"{self._model} returned no choices")
        content = getattr(choices[0].message, "content", None)
        if not content:
            raise GenerationError(f"{self._model} returned empty content")

        raw_usage = getattr(completion, "usage", None)
        usage = Usage(
            prompt_tokens=int(getattr(raw_usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(raw_usage, "completion_tokens", 0) or 0),
        )
        return str(content), usage
