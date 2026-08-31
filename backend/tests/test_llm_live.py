"""One opt-in live check that the adapter really talks to a provider.

Every other test in this repository runs offline. This one does not: it spends
money and sends a prompt to a third party, so it is skipped unless a reader
explicitly asks for it.

    MERIDIAN_LLM_LIVE=1 ./scripts/python_in_docker.sh pytest backend/tests/test_llm_live.py

It exists because the offline suite proves the adapter's shape, not that the
shape is the one the provider expects. Strict `json_schema` support in
particular varies between providers, and a mock cannot tell you whether the one
you configured honours it.
"""

import os

import pytest
from pydantic import BaseModel, Field

from meridian.llm.base import generate_structured
from meridian.llm.providers import build_generator, describe_provider
from meridian.settings import get_settings

LIVE_ENV_VAR = "MERIDIAN_LLM_LIVE"

pytestmark = pytest.mark.skipif(
    os.environ.get(LIVE_ENV_VAR) != "1",
    reason=f"live provider check is opt-in; set {LIVE_ENV_VAR}=1 to run it",
)


class AccountRisk(BaseModel):
    """A small structured answer, shaped like what Phase 5 will ask for."""

    model_config = {"extra": "forbid"}

    headline: str = Field(min_length=1, max_length=200)
    confidence: float = Field(ge=0.0, le=1.0)
    drivers: list[str] = Field(min_length=1, max_length=3)


def test_the_configured_provider_returns_schema_conformant_json() -> None:
    """The configured provider must honour strict structured output."""

    settings = get_settings()
    status = describe_provider(settings)
    if not status.configured:
        pytest.skip(f"provider not configured: {status.detail}")

    result = generate_structured(
        build_generator(settings),
        AccountRisk,
        instructions=(
            "You summarise synthetic B2B SaaS account health. Reply only with JSON "
            "matching the schema."
        ),
        input_text=(
            "Weekly active users fell 40% over one quarter, the executive sponsor "
            "left, and two P1 tickets are unresolved. Summarise the renewal risk."
        ),
        max_output_tokens=300,
    )

    assert result.value.headline.strip()
    assert result.value.drivers
    assert result.attempts == 1, "the provider needed a repair round for a simple schema"
    assert result.usage.total_tokens > 0
    print(f"\n  provider : {status.provider} @ {status.base_url}")
    print(f"  model    : {result.model}")
    print(f"  tokens   : {result.usage.total_tokens}")
    print(f"  headline : {result.value.headline}")
