"""Stepping down when a server cannot enforce a JSON Schema (ADR 0004).

Hosted frontier models enforce a JSON Schema server-side, and that is what the
adapter asks for first. Small open-weight models -- and the servers that host
them, Ollama and llama.cpp among them -- often support only `json_object`, or
nothing, and reject the stricter request outright. Before this, that failed the
whole call: a 3B model could not be used to demonstrate the system at all.

Two properties matter and are both tested here. `auto` steps down only for a
refusal of the parameter, never for an authentication or transport failure that
would be hidden by retrying in a weaker mode. And every weaker mode puts the
schema in the system message, because nothing else would tell the model what to
produce -- without it a step-down does not degrade the output, it destroys it.

Correctness never rests on the mode: `generate_structured` validates every reply
against the Pydantic model whatever the server promised.
"""

from types import SimpleNamespace
from typing import Any

import pytest

from meridian.llm.base import GenerationError, GenerationRequest
from meridian.llm.openai_compatible import OpenAICompatibleGenerator

REQUEST = GenerationRequest(
    instructions="Plan the sub-goals.",
    input_text="ACC-1042",
    schema_name="SubGoalPlan",
    json_schema={"type": "object", "properties": {"sub_goals": {"type": "array"}}},
)


class RecordingClient:
    """A stand-in for the SDK that records calls and can refuse the first n.

    Built from `SimpleNamespace` rather than nested classes so the recorded
    calls live on one object: `client.chat.completions.create` is the only
    shape the adapter depends on.
    """

    def __init__(self, refusals: int = 0, message: str = "") -> None:
        self.calls: list[dict[str, Any]] = []
        self.refusals = refusals
        self.message = message or (
            "Error code: 400 - response_format json_schema is not supported by this model"
        )
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create),
        )

    def _create(self, **kwargs: Any) -> Any:
        """Record the call, refuse while owed a refusal, then reply."""

        self.calls.append(kwargs)
        if len(self.calls) <= self.refusals:
            raise RuntimeError(self.message)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=7),
        )


def _generator(client: RecordingClient, **kwargs: Any) -> OpenAICompatibleGenerator:
    """Return an adapter wired to the recording client."""

    return OpenAICompatibleGenerator(api_key="unused", client=client, **kwargs)


def test_the_strongest_mode_is_tried_first_and_carries_no_schema_in_the_prompt() -> None:
    """A capable server is told the schema once, through the API."""

    client = RecordingClient()
    generator = _generator(client)
    generator.complete_json(REQUEST)

    sent = client.calls[0]
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["strict"] is True
    # The API carries the schema, so repeating it in the prompt would spend
    # tokens on every call to say what the server already enforces.
    assert "properties" not in sent["messages"][0]["content"]
    assert generator.structured_mode == "json_schema"


def test_a_server_that_refuses_schemas_is_retried_in_a_weaker_mode() -> None:
    """The whole point: a 3B model behind Ollama still produces a result."""

    client = RecordingClient(refusals=1)
    generator = _generator(client)
    content, usage = generator.complete_json(REQUEST)

    assert content == "{}"
    assert usage.prompt_tokens == 5
    assert len(client.calls) == 2
    assert client.calls[1]["response_format"] == {"type": "json_object"}
    assert generator.structured_mode == "json_object"


def test_a_weaker_mode_puts_the_schema_in_the_system_message() -> None:
    """Nothing else would tell the model what fields to produce."""

    client = RecordingClient(refusals=1)
    generator = _generator(client)
    generator.complete_json(REQUEST)

    instructions = client.calls[1]["messages"][0]["content"]
    assert "Plan the sub-goals." in instructions
    assert "sub_goals" in instructions
    assert "single JSON object" in instructions


def test_the_step_down_is_remembered_rather_than_rediscovered() -> None:
    """Paying for the refusal once per call would double every run's latency."""

    client = RecordingClient(refusals=1)
    generator = _generator(client)
    generator.complete_json(REQUEST)
    generator.complete_json(REQUEST)

    # Three calls, not four: refusal, success, success.
    assert len(client.calls) == 3
    assert client.calls[2]["response_format"] == {"type": "json_object"}


def test_the_ladder_ends_at_a_bare_request_with_no_response_format() -> None:
    """A server supporting neither mode still gets a well-instructed prompt."""

    client = RecordingClient(refusals=2)
    generator = _generator(client)
    generator.complete_json(REQUEST)

    assert len(client.calls) == 3
    assert "response_format" not in client.calls[2]
    assert "sub_goals" in client.calls[2]["messages"][0]["content"]
    assert generator.structured_mode == "prompt"


def test_an_exhausted_ladder_fails_rather_than_looping() -> None:
    """Every mode refused is a real failure, not something to retry forever."""

    client = RecordingClient(refusals=99)
    with pytest.raises(GenerationError):
        _generator(client).complete_json(REQUEST)
    assert len(client.calls) == 3


def test_an_authentication_failure_does_not_step_down() -> None:
    """Retrying a 401 in a weaker mode would hide the actual problem."""

    client = RecordingClient(refusals=99, message="Error code: 401 - Unauthorized")
    generator = _generator(client)
    with pytest.raises(GenerationError):
        generator.complete_json(REQUEST)

    assert len(client.calls) == 1
    assert generator.structured_mode == "json_schema"


def test_a_transport_failure_does_not_step_down() -> None:
    """A connection reset says nothing about what the server supports."""

    client = RecordingClient(refusals=99, message="Connection error: peer reset")
    with pytest.raises(GenerationError):
        _generator(client).complete_json(REQUEST)
    assert len(client.calls) == 1


@pytest.mark.parametrize("mode", ["json_schema", "json_object", "prompt"])
def test_an_explicit_mode_is_obeyed_and_never_downgraded(mode: str) -> None:
    """A deployment that asked for enforced schemas must learn if it lost them.

    Stepping down silently would leave an operator believing the server was
    validating output when it had stopped.
    """

    client = RecordingClient(refusals=99)
    generator = _generator(client, structured_output=mode)
    with pytest.raises(GenerationError):
        generator.complete_json(REQUEST)

    assert len(client.calls) == 1
    assert generator.structured_mode == mode


def test_an_explicit_weak_mode_still_sends_the_schema_in_the_prompt() -> None:
    """Choosing json_object deliberately must not lose the field list."""

    client = RecordingClient()
    generator = _generator(client, structured_output="json_object")
    generator.complete_json(REQUEST)

    assert client.calls[0]["response_format"] == {"type": "json_object"}
    assert "sub_goals" in client.calls[0]["messages"][0]["content"]
