"""Provider-independent structured generation (plan section 12 deliverable).

Phase 4 asks for tests that hold whichever provider is configured, and that run
with no credentials. Everything here uses either the deterministic fakes that
ship in `meridian.llm.fake` or a hand-written stand-in for the OpenAI SDK
client, so the whole file runs offline.

What is under test is the contract the graph will depend on from Phase 5: a
caller names a Pydantic model and gets an instance of it, one repair attempt is
made and no more, and a provider that cannot run says so precisely.
"""

from types import SimpleNamespace
from typing import Any, Literal

import pytest
from pydantic import BaseModel, Field

from meridian.llm.base import (
    GenerationError,
    GenerationRequest,
    ProviderNotConfiguredError,
    StructuredOutputError,
    Usage,
    generate_structured,
)
from meridian.llm.fake import EchoGenerator, ScriptedGenerator
from meridian.llm.openai_compatible import OpenAICompatibleGenerator
from meridian.llm.providers import build_generator, describe_provider
from meridian.settings import Settings

# Assembled rather than written literally: a credential-shaped string in a
# tracked file is exactly what scripts/check_repository.py exists to catch,
# and it is right to catch it. The runtime value is still realistic enough
# to prove the adapter never echoes a key back in an error message.
SECRET = "sk-" + "or-v1-" + "0" * 32


class SubGoalPlan(BaseModel):
    """A stand-in for the structured outputs later phases will ask for."""

    model_config = {"extra": "forbid"}

    sub_goals: list[str] = Field(min_length=1, max_length=4)
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)
    route: Literal["fast_path", "conflict_gate", "human_review"]


VALID_REPLY = (
    '{"sub_goals": ["adoption", "support"], "rationale": "Usage fell sharply.", '
    '"confidence": 0.72, "route": "conflict_gate"}'
)


def _settings(**overrides: Any) -> Settings:
    """Return settings with the environment ignored, so tests are hermetic."""

    defaults: dict[str, Any] = {
        "llm_provider": "openai_compatible",
        "llm_model": "anthropic/claude-sonnet-4.5",
        "llm_base_url": "https://openrouter.ai/api/v1",
        "llm_api_key": "",
        "_env_file": None,
    }
    return Settings(**{**defaults, **overrides})


def test_a_caller_names_a_model_and_gets_an_instance_of_it() -> None:
    """No caller should ever parse free text."""

    generator = ScriptedGenerator([VALID_REPLY])
    result = generate_structured(
        generator, SubGoalPlan, instructions="Plan the assessment.", input_text="ACC-1042"
    )
    assert isinstance(result.value, SubGoalPlan)
    assert result.value.route == "conflict_gate"
    assert result.attempts == 1
    assert result.model == "scripted-test-model"
    assert result.usage.total_tokens == 15


def test_malformed_output_is_repaired_exactly_once() -> None:
    """A model that misses the schema gets one more chance and no more."""

    generator = ScriptedGenerator(["not json at all", VALID_REPLY])
    result = generate_structured(
        generator, SubGoalPlan, instructions="Plan.", input_text="ACC-1042"
    )
    assert result.attempts == 2
    assert generator.calls == 2
    assert result.value.confidence == pytest.approx(0.72)


def test_the_repair_prompt_says_what_was_wrong() -> None:
    """Asking again without saying why mostly produces the same failure again."""

    generator = ScriptedGenerator(['{"sub_goals": [], "rationale": "x"}', VALID_REPLY])
    generate_structured(generator, SubGoalPlan, instructions="Plan.", input_text="ACC-1042")
    repair = generator.requests[1].input_text
    assert "did not satisfy the schema" in repair
    assert "sub_goals" in repair


def test_a_model_that_never_conforms_fails_instead_of_looping() -> None:
    """An unbounded repair loop turns one bad reply into an unbounded bill."""

    generator = ScriptedGenerator(['{"unexpected": true}'])
    with pytest.raises(StructuredOutputError) as failure:
        generate_structured(generator, SubGoalPlan, instructions="Plan.", input_text="ACC-1042")
    assert generator.calls == 2
    assert "SubGoalPlan" in str(failure.value)
    assert failure.value.attempts == 2
    assert failure.value.usage.prompt_tokens == 20
    assert failure.value.usage.completion_tokens == 10


def test_usage_accumulates_across_attempts() -> None:
    """A repair is billed too, so it has to be counted."""

    generator = ScriptedGenerator(["nonsense", VALID_REPLY])
    result = generate_structured(
        generator, SubGoalPlan, instructions="Plan.", input_text="ACC-1042"
    )
    assert result.usage.prompt_tokens == 20
    assert result.usage.completion_tokens == 10


def test_the_schema_sent_to_a_provider_is_strict() -> None:
    """Strict schema enforcement rejects a schema that permits unknown keys."""

    generator = ScriptedGenerator([VALID_REPLY])
    generate_structured(generator, SubGoalPlan, instructions="Plan.", input_text="ACC-1042")
    schema = generator.requests[0].json_schema
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert generator.requests[0].schema_name == "SubGoalPlan"


def test_the_echo_generator_satisfies_whatever_schema_it_is_given() -> None:
    """Later phases need a fake that works without scripting every reply."""

    result = generate_structured(
        EchoGenerator(), SubGoalPlan, instructions="Plan.", input_text="ACC-1042"
    )
    assert isinstance(result.value, SubGoalPlan)
    assert result.value.route == "fast_path"


def test_a_provider_failure_is_wrapped_without_its_internals() -> None:
    """A provider's own exception text can carry a URL, a key, or a request id."""

    class ExplodingClient:
        class chat:  # noqa: N801 - mirrors the SDK's attribute layout
            class completions:  # noqa: N801
                @staticmethod
                def create(**_: Any) -> Any:
                    raise RuntimeError(f"401 Unauthorized for key {SECRET}")

    generator = OpenAICompatibleGenerator(api_key=SECRET, client=ExplodingClient())
    with pytest.raises(GenerationError) as failure:
        generator.complete_json(
            GenerationRequest(
                instructions="Plan.",
                input_text="ACC-1042",
                schema_name="SubGoalPlan",
                json_schema={"type": "object"},
            )
        )
    assert SECRET not in str(failure.value)
    assert "RuntimeError" in str(failure.value)


def test_the_adapter_asks_for_a_strict_json_schema() -> None:
    """Structured output is enforced at the provider, not only after the fact."""

    captured: dict[str, Any] = {}

    class RecordingClient:
        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                def create(**kwargs: Any) -> Any:
                    captured.update(kwargs)

                    class Message:
                        content = VALID_REPLY

                    class Choice:
                        message = Message()

                    usage = SimpleNamespace(prompt_tokens=11, completion_tokens=7)
                    return SimpleNamespace(choices=[Choice()], usage=usage)

    generator = OpenAICompatibleGenerator(
        api_key=SECRET, model="anthropic/claude-sonnet-4.5", client=RecordingClient()
    )
    result = generate_structured(
        generator, SubGoalPlan, instructions="Plan.", input_text="ACC-1042"
    )

    assert result.value.route == "conflict_gate"
    assert result.usage.prompt_tokens == 11
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert captured["model"] == "anthropic/claude-sonnet-4.5"
    assert [message["role"] for message in captured["messages"]] == ["system", "user"]


def test_an_adapter_without_a_key_refuses_to_be_constructed() -> None:
    """Failing at construction beats failing with a 401 several layers down."""

    with pytest.raises(ProviderNotConfiguredError, match="MERIDIAN_LLM_API_KEY"):
        OpenAICompatibleGenerator(api_key="")


def test_an_empty_response_is_an_error_not_an_empty_model() -> None:
    """Silently returning a default-constructed model would hide a real failure."""

    class EmptyClient:
        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                def create(**_: Any) -> Any:
                    class Message:
                        content = ""

                    class Choice:
                        message = Message()

                    return SimpleNamespace(choices=[Choice()], usage=None)

    generator = OpenAICompatibleGenerator(api_key=SECRET, client=EmptyClient())
    with pytest.raises(GenerationError, match="empty content"):
        generator.complete_json(
            GenerationRequest(
                instructions="Plan.",
                input_text="ACC-1042",
                schema_name="SubGoalPlan",
                json_schema={"type": "object"},
            )
        )


@pytest.mark.parametrize("provider", ["anthropic", "azure_openai", "ollama", "disabled"])
def test_an_unimplemented_provider_says_what_to_do_instead(provider: str) -> None:
    """Section 12: skeletons must fail clearly, not with a KeyError."""

    settings = _settings(llm_provider=provider, llm_api_key=SECRET)
    with pytest.raises(ProviderNotConfiguredError) as failure:
        build_generator(settings)
    message = str(failure.value)
    assert "not implemented" in message or "switched off" in message
    # An actionable message names the setting the reader should change.
    assert "MERIDIAN_LLM_PROVIDER" in message or "deterministic" in message


def test_building_without_a_key_names_the_variable_to_set() -> None:
    """The repository is meant to run without credentials; say so usefully."""

    with pytest.raises(ProviderNotConfiguredError, match="MERIDIAN_LLM_API_KEY"):
        build_generator(_settings(llm_api_key=""))


def test_the_provider_description_never_contains_the_credential() -> None:
    """Status is logged and shown in a health view, so it must be safe."""

    described = describe_provider(_settings(llm_api_key=SECRET))
    rendered = f"{described} {described.summary}"
    assert SECRET not in rendered
    assert described.configured is True
    assert described.model == "anthropic/claude-sonnet-4.5"
    assert "openrouter.ai" in described.base_url


def test_an_unconfigured_provider_is_reported_as_unavailable_not_broken() -> None:
    """Running without a key is a supported state through Phase 4."""

    described = describe_provider(_settings(llm_api_key=""))
    assert described.configured is False
    assert "MERIDIAN_LLM_API_KEY" in described.detail
    assert "unavailable" in described.summary


def test_the_openai_key_variable_still_works_as_a_second_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """This project's .env has always used OPENAI_API_KEY, holding an OpenRouter key."""

    monkeypatch.delenv("MERIDIAN_LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    assert Settings(_env_file=None).llm_api_key == SECRET


def test_the_generator_protocol_is_satisfied_by_the_fakes() -> None:
    """The fakes must be usable wherever the graph expects a real provider."""

    from meridian.llm.base import StructuredGenerator

    for candidate in (ScriptedGenerator([VALID_REPLY]), EchoGenerator()):
        assert isinstance(candidate, StructuredGenerator)


def test_scripted_replies_can_raise_to_exercise_failure_paths() -> None:
    """A test double that can only succeed cannot test error handling."""

    generator = ScriptedGenerator([GenerationError("provider down")])
    with pytest.raises(GenerationError, match="provider down"):
        generate_structured(generator, SubGoalPlan, instructions="Plan.", input_text="ACC-1042")


def test_usage_reports_a_total() -> None:
    """Cost reporting in Phase 10 needs one number, not two."""

    assert Usage(prompt_tokens=3, completion_tokens=4).total_tokens == 7
