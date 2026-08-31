"""Deterministic generators for offline tests (ADR 0004).

ADR 0004 promises that "graph nodes and tests remain portable and offline tests
can use deterministic fakes". These are those fakes. They ship in the runtime
package rather than the test tree so that every phase after this one can write
an offline test of a graph node without inventing its own stub, and so the
protocol has at least one implementation that never touches the network.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from meridian.llm.base import GenerationError, GenerationRequest, Usage


class ScriptedGenerator:
    """Return queued replies in order, recording what it was asked.

    Give it JSON strings to replay a provider exactly, or Pydantic models and
    dicts when a test only cares about the happy path. A reply may also be an
    exception instance, which is raised instead of returned -- that is how a
    test exercises the failure branches without patching anything.
    """

    def __init__(
        self,
        replies: Sequence[Any],
        model_name: str = "scripted-test-model",
        usage: Usage | None = None,
    ) -> None:
        if not replies:
            raise ValueError("ScriptedGenerator needs at least one reply")
        self._replies = list(replies)
        self._model_name = model_name
        self._usage = usage if usage is not None else Usage(prompt_tokens=10, completion_tokens=5)
        self.requests: list[GenerationRequest] = []

    @property
    def model_name(self) -> str:
        """Return the fake model identifier."""

        return self._model_name

    @property
    def calls(self) -> int:
        """Return how many times this generator was asked to complete."""

        return len(self.requests)

    def complete_json(self, request: GenerationRequest) -> tuple[str, Usage]:
        """Return the next scripted reply as JSON text.

        Raises:
            GenerationError: If the script is exhausted.
        """

        self.requests.append(request)
        if not self._replies:
            raise GenerationError("ScriptedGenerator ran out of replies")
        # The last reply repeats, so a test that only cares about one shape does
        # not have to count how many repair attempts the caller will make.
        reply = self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]
        if isinstance(reply, BaseException):
            raise reply
        if isinstance(reply, str):
            return reply, self._usage
        if hasattr(reply, "model_dump_json"):
            return str(reply.model_dump_json()), self._usage
        return json.dumps(reply), self._usage


@dataclass
class EchoGenerator:
    """Return whatever satisfies the requested schema's required scalar fields.

    Useful when a test needs *a* valid answer and does not care which one, so
    it can assert on plumbing rather than content.
    """

    model_name: str = "echo-test-model"
    usage: Usage = field(default_factory=lambda: Usage(prompt_tokens=1, completion_tokens=1))

    def complete_json(self, request: GenerationRequest) -> tuple[str, Usage]:
        """Return minimal JSON satisfying the request's schema."""

        return json.dumps(_minimal_instance(request.json_schema)), self.usage


def _minimal_instance(schema: dict[str, Any]) -> Any:
    """Return the smallest value satisfying a simple JSON Schema node."""

    if schema.get("enum"):
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    for key in ("anyOf", "oneOf", "allOf"):
        options = schema.get(key)
        if isinstance(options, list) and options:
            return _minimal_instance(options[0])

    node_type = schema.get("type")
    if node_type == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", list(properties))
        return {name: _minimal_instance(properties.get(name, {})) for name in required}
    if node_type == "array":
        minimum_items = int(schema.get("minItems", 0))
        item_schema = schema.get("items", {})
        return [_minimal_instance(item_schema) for _ in range(minimum_items)]
    if node_type == "integer":
        return int(schema.get("minimum", 0))
    if node_type == "number":
        return float(schema.get("minimum", 0.0))
    if node_type == "boolean":
        return False
    if node_type == "null":
        return None
    return ""
