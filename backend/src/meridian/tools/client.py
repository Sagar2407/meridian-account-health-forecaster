"""The local MCP client adapter (plan section 12, ADR 0002).

Phase 4 needs a client for two reasons. It proves the MCP surface is real rather
than a server nobody has ever connected to, and it gives later phases a single
place to swap an in-process session for a stdio or HTTP one without touching a
caller.

The session runs in memory: no subprocess, no socket, no port. That keeps the
contract test fast enough to belong in the normal suite, which is the only way
a contract test stays honest over time.

Protocol objects stop here. A caller gets `ToolSummary` and plain dictionaries,
so nothing downstream learns what MCP's content blocks look like.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import mcp.types as types
from mcp.shared.memory import create_connected_server_and_client_session

from meridian.tools.contracts import RequesterRole
from meridian.tools.registry import ToolRegistry
from meridian.tools.server import build_server


class ToolCallError(RuntimeError):
    """Raised when the server reports a failed tool call.

    The message is the server's error category, not an internal detail: the
    transport deliberately does not carry stack traces or database errors.
    """


@dataclass(frozen=True)
class ToolSummary:
    """One tool as advertised over the protocol."""

    name: str
    description: str
    input_schema: dict[str, Any]


class LocalToolClient:
    """An MCP client speaking to an in-process Meridian server."""

    def __init__(self, session: Any) -> None:
        self._session = session

    async def list_tools(self) -> tuple[ToolSummary, ...]:
        """Return the tools this session's role may call."""

        listing = await self._session.list_tools()
        return tuple(
            ToolSummary(
                name=tool.name,
                description=tool.description or "",
                input_schema=dict(tool.inputSchema),
            )
            for tool in listing.tools
        )

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call one tool and return its decoded JSON result.

        Raises:
            ToolCallError: If the server reported an error, or returned
                something that is not the single JSON block this layer emits.
        """

        result = await self._session.call_tool(name, arguments or {})
        text = "".join(
            block.text for block in result.content if isinstance(block, types.TextContent)
        )
        if result.isError:
            raise ToolCallError(text or f"{name} failed without a reason")
        if not text:
            raise ToolCallError(f"{name} returned no content")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise ToolCallError(f"{name} returned content that is not JSON") from error
        if not isinstance(payload, dict):
            raise ToolCallError(f"{name} returned {type(payload).__name__}, not an object")
        return payload


@asynccontextmanager
async def connect(registry: ToolRegistry, role: RequesterRole) -> AsyncIterator[LocalToolClient]:
    """Open an in-process MCP session for one role.

    Yields:
        A client bound to a server that advertises only this role's tools.
    """

    server = build_server(registry, role)
    async with create_connected_server_and_client_session(server) as session:
        yield LocalToolClient(session)
