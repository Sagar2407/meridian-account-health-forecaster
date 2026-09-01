"""Runtime spending and tool-surface guardrails (plan section 16.3)."""

from typing import Any, cast

import pytest

from meridian.guardrails.runtime import (
    ALLOWED_TOOL_NAMES,
    DangerousToolError,
    RunBudget,
    assert_no_dangerous_tools,
)
from meridian.tools.contracts import AccountRequest
from meridian.tools.registry import ToolDescriptor, ToolRegistry


def test_the_real_tool_surface_is_exactly_the_frozen_read_only_set() -> None:
    assert set(assert_no_dangerous_tools()) == ALLOWED_TOOL_NAMES


@pytest.mark.parametrize("name", ["run_sql_query", "execute_shell", "open_file", "browse_web"])
def test_a_general_purpose_tool_shape_is_rejected(name: str) -> None:
    descriptor = ToolDescriptor(
        name=name,
        description="unsafe test tool",
        request_model=AccountRequest,
        handler="unused",
    )

    class UnsafeRegistry:
        @staticmethod
        def describe() -> tuple[ToolDescriptor, ...]:
            return (descriptor,)

    with pytest.raises(DangerousToolError):
        assert_no_dangerous_tools(cast(ToolRegistry, cast(Any, UnsafeRegistry())))


def test_the_budget_stops_at_each_frozen_boundary() -> None:
    within = RunBudget(
        model_calls=1,
        tokens=100,
        elapsed_seconds=1.0,
        max_model_calls=2,
        max_tokens=200,
        max_seconds=2.0,
    )
    assert within.may_spend is True
    assert within.verdict().outcome == "pass"

    spent = RunBudget(
        model_calls=2,
        tokens=200,
        elapsed_seconds=2.0,
        max_model_calls=2,
        max_tokens=200,
        max_seconds=2.0,
    )
    assert spent.may_spend is False
    assert spent.exceeded == ("model_calls", "tokens", "wall_clock")
    decision = spent.verdict()
    assert decision.stage == "execution"
    assert decision.outcome == "review"
    assert decision.reason_codes == ("budget_exhausted",)
