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

import json
from typing import Any, Literal

from meridian.llm.base import (
    GenerationError,
    GenerationRequest,
    ProviderNotConfiguredError,
    Usage,
)

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"
DEFAULT_TIMEOUT_SECONDS = 60.0

#: How JSON is requested, strongest first.
StructuredMode = Literal["auto", "json_schema", "json_object", "prompt"]

#: The step-down order `auto` walks. `json_schema` is enforced by the server;
#: `json_object` only guarantees syntactic JSON; `prompt` guarantees nothing and
#: relies entirely on the instructions and on validation upstream.
_LADDER: tuple[str, ...] = ("json_schema", "json_object", "prompt")

#: Substrings that mean "this server does not support that parameter", as
#: opposed to "your request was wrong" or "the service is down". Matched against
#: the provider's error text, because the OpenAI SDK raises the same
#: `BadRequestError` for both and only the message distinguishes them.
_UNSUPPORTED_SIGNALS: tuple[str, ...] = (
    "response_format",
    "json_schema",
    "structured output",
    "not supported",
    "unsupported",
    "unrecognized",
    "unknown parameter",
    "invalid_request_error",
)


class OpenAICompatibleGenerator:
    """Structured generation over any OpenAI-compatible chat completions API."""

    def __init__(
        self,
        api_key: str | None,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        client: Any | None = None,
        structured_output: StructuredMode = "auto",
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
        self._requested_mode = structured_output
        # Negotiated once per generator, not per call: a server that rejects
        # `json_schema` will reject it every time, and paying for that round
        # trip on every request would double the latency of the whole run.
        self._mode: str = _LADDER[0] if structured_output == "auto" else structured_output

    @property
    def structured_mode(self) -> str:
        """Return the mode currently in use, after any step-down."""

        return self._mode

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
        completion = self._create(client, request)

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

    def _create(self, client: Any, request: GenerationRequest) -> Any:
        """Call the provider, stepping down the ladder if it refuses a mode.

        Raises:
            GenerationError: If the call fails for any reason other than the
                server not supporting the requested structured-output mode, or
                if every mode has been exhausted.
        """

        while True:
            try:
                return client.chat.completions.create(
                    model=self._model,
                    temperature=request.temperature,
                    max_tokens=request.max_output_tokens,
                    messages=self._messages(request),
                    **self._response_format(request),
                )
            except Exception as error:
                nxt = self._step_down(error)
                if nxt is None:
                    raise GenerationError(
                        f"{self._model} request failed: {type(error).__name__}"
                    ) from error
                self._mode = nxt

    def _step_down(self, error: Exception) -> str | None:
        """Return the next weaker mode to try, or None to give up.

        Only `auto` steps down. An explicit mode is a decision, and silently
        doing something else would hide a misconfiguration -- the caller asked
        for server-enforced schemas and would never learn they were not getting
        them.
        """

        if self._requested_mode != "auto" or self._mode == _LADDER[-1]:
            return None
        text = str(error).lower()
        if not any(signal in text for signal in _UNSUPPORTED_SIGNALS):
            return None
        return _LADDER[_LADDER.index(self._mode) + 1]

    def _response_format(self, request: GenerationRequest) -> dict[str, Any]:
        """Return the `response_format` keyword for the current mode."""

        if self._mode == "json_schema":
            return {
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": request.schema_name,
                        "schema": request.json_schema,
                        "strict": True,
                    },
                }
            }
        if self._mode == "json_object":
            return {"response_format": {"type": "json_object"}}
        return {}

    def _messages(self, request: GenerationRequest) -> list[dict[str, str]]:
        """Return the chat messages, carrying the schema when the API cannot.

        In `json_schema` mode the server is told the shape and enforces it. In
        every weaker mode nothing else would tell the model what to produce, so
        the schema goes into the system message. Without this a step-down does
        not degrade the output, it destroys it: the model has no idea what
        fields were wanted and every reply fails validation.
        """

        instructions = request.instructions
        if self._mode != "json_schema":
            instructions = (
                f"{instructions}\n\n"
                "Reply with a single JSON object and nothing else: no prose, no "
                "explanation, and no code fence. It must validate against this "
                f"JSON Schema:\n{json.dumps(request.json_schema, sort_keys=True)}"
            )
        return [
            {"role": "system", "content": instructions},
            {"role": "user", "content": request.input_text},
        ]
