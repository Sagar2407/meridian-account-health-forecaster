"""The provider-neutral structured-generation interface (ADR 0004).

Graph and tool code depends on this module, never on a vendor SDK. That is not
a style preference: it is the Phase 4 exit gate, and `test_import_boundary.py`
fails the build if any module outside `meridian.llm.openai_compatible` imports
`openai`.

Two things are enforced here rather than left to each adapter:

* **Structured output.** A caller names a Pydantic model and gets an instance of
  it or an error. No adapter returns free text for a caller to parse.
* **One bounded repair retry.** Models occasionally emit JSON that does not
  satisfy the schema. `generate_structured` feeds the validation error back once
  and stops. Retrying indefinitely would turn a malformed response into an
  unbounded bill.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)

MAX_REPAIR_ATTEMPTS = 1
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_OUTPUT_TOKENS = 2_048


class GenerationError(RuntimeError):
    """Base class for every failure this layer reports."""


class ProviderNotConfiguredError(GenerationError):
    """Raised when a provider is selected but cannot run.

    This is deliberately distinct from a generation failure: it means the
    repository is running without credentials, which is a supported state for
    every phase through 4, not a bug.
    """


class StructuredOutputError(GenerationError):
    """Raised when a model could not produce output matching the schema."""


@dataclass(frozen=True)
class Usage:
    """Token accounting for one generation, for cost and latency reporting."""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Return the total tokens billed for this call."""

        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class StructuredResult(Generic[ModelT]):
    """One validated generation plus what it cost to obtain."""

    value: ModelT
    model: str
    usage: Usage = field(default_factory=Usage)
    attempts: int = 1


@dataclass(frozen=True)
class GenerationRequest:
    """One structured-generation request, independent of any provider."""

    instructions: str
    input_text: str
    schema_name: str
    json_schema: dict[str, Any]
    temperature: float = DEFAULT_TEMPERATURE
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS


@runtime_checkable
class StructuredGenerator(Protocol):
    """What the graph is allowed to know about a language model.

    Runtime-checkable so a caller assembling providers from configuration can
    assert it received something usable, rather than discovering the gap on the
    first generation.
    """

    @property
    def model_name(self) -> str:
        """Return the model identifier this generator will use."""

    def complete_json(self, request: GenerationRequest) -> tuple[str, Usage]:
        """Return raw JSON text for `request`, plus its token usage.

        Implementations ask the provider for schema-constrained JSON. They do
        not validate it; `generate_structured` owns validation and repair so
        every provider behaves identically when a model misbehaves.
        """


def _schema_for(model: type[BaseModel]) -> dict[str, Any]:
    """Return a strict JSON Schema for `model`.

    Providers that support strict schema enforcement reject a schema that
    permits unknown keys, so `additionalProperties` is closed on every object.
    """

    schema = model.model_json_schema()

    def close(node: Any) -> Any:
        if isinstance(node, dict):
            closed = {key: close(value) for key, value in node.items()}
            if closed.get("type") == "object":
                closed.setdefault("additionalProperties", False)
                properties = closed.get("properties")
                if isinstance(properties, dict):
                    closed["required"] = sorted(properties)
            return closed
        if isinstance(node, list):
            return [close(item) for item in node]
        return node

    return dict(close(schema))


def generate_structured(
    generator: StructuredGenerator,
    schema: type[ModelT],
    instructions: str,
    input_text: str,
    temperature: float = DEFAULT_TEMPERATURE,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    on_attempt: Callable[[int, str], None] | None = None,
) -> StructuredResult[ModelT]:
    """Generate one instance of `schema`, repairing at most once.

    Args:
        generator: Any provider implementing the protocol.
        schema: The Pydantic model the result must satisfy.
        instructions: System-level guidance.
        input_text: The user-level content to reason over.
        temperature: Sampling temperature; defaults to deterministic.
        max_output_tokens: Hard ceiling on generated length.
        on_attempt: Optional observer receiving each attempt's raw text, for
            tracing without teaching callers to parse it themselves.

    Returns:
        The validated value, the model that produced it, usage, and how many
        attempts it took.

    Raises:
        StructuredOutputError: If the model still fails the schema after the
            one permitted repair.
    """

    json_schema = _schema_for(schema)
    request = GenerationRequest(
        instructions=instructions,
        input_text=input_text,
        schema_name=schema.__name__,
        json_schema=json_schema,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )

    total = Usage()
    last_error = ""
    for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
        raw, usage = generator.complete_json(request)
        total = Usage(
            prompt_tokens=total.prompt_tokens + usage.prompt_tokens,
            completion_tokens=total.completion_tokens + usage.completion_tokens,
        )
        if on_attempt is not None:
            on_attempt(attempt + 1, raw)
        try:
            return StructuredResult(
                value=schema.model_validate_json(raw),
                model=generator.model_name,
                usage=total,
                attempts=attempt + 1,
            )
        except (ValidationError, ValueError) as error:
            last_error = str(error)
            if attempt == MAX_REPAIR_ATTEMPTS:
                break
            # Feed the failure back verbatim. A model repairs its own output far
            # more reliably when it is told what was wrong than when it is
            # simply asked again.
            request = GenerationRequest(
                instructions=instructions,
                input_text=(
                    f"{input_text}\n\nYour previous reply did not satisfy the schema.\n"
                    f"Error: {last_error}\n"
                    f"Reply with JSON matching this schema exactly: {json.dumps(json_schema)}"
                ),
                schema_name=request.schema_name,
                json_schema=json_schema,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )

    raise StructuredOutputError(
        f"{generator.model_name} did not produce valid {schema.__name__} "
        f"after {MAX_REPAIR_ATTEMPTS + 1} attempts: {last_error}"
    )
