"""Shared helpers for the four agents.

Agents reach data through `ToolRegistry`, never through the repository or the
retrieval service directly. That is where plan section 12.3's policy lives --
the per-role allowlist, argument validation, the timeout, and the audit line --
so an agent that went around it would be unaudited and unconstrained even though
it produced the same numbers.
"""

from collections.abc import Mapping
from typing import Any, TypeVar

from meridian.tools.contracts import RequesterRole, ToolResponse
from meridian.tools.registry import ToolRegistry

ResponseT = TypeVar("ResponseT", bound=ToolResponse)


def call_tool(
    registry: ToolRegistry,
    role: RequesterRole,
    tool: str,
    arguments: Mapping[str, Any],
    expected: type[ResponseT],
) -> ResponseT:
    """Call one tool and return its response, narrowed to the expected type.

    Raises:
        TypeError: If the registry returned a different response type, which
            would mean the tool table and this caller have diverged.
    """

    response = registry.call(role, tool, arguments)
    if not isinstance(response, expected):
        raise TypeError(f"{tool} returned {type(response).__name__}, expected {expected.__name__}")
    return response


__all__ = ["call_tool"]
