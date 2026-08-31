"""The MCP surface over the read-only tool layer (plan section 12, ADR 0002).

MCP is a boundary here, not an orchestration engine. This module owns every
protocol object in the repository: it turns `ToolRegistry` descriptors into MCP
tools and JSON results back into content blocks, and nothing it imports leaks
into the services, which stay callable with no transport at all.

A server is built for exactly one requester role. That is what makes the section
12.3 allowlist real over the wire: an Evidence Retriever's session cannot
enumerate, let alone call, a tool it is not entitled to, because the server it
is connected to never advertised one.
"""

import json
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server

from meridian.tools.contracts import RequesterRole
from meridian.tools.registry import ToolRegistry, error_category

SERVER_NAME = "meridian"
SERVER_INSTRUCTIONS = (
    "Read-only, point-in-time-safe access to one synthetic B2B SaaS account at a "
    "time. Every result carries the effective cutoff it was computed at. No tool "
    "writes to source data, and none returns an outcome label."
)


def build_server(registry: ToolRegistry, role: RequesterRole) -> Server[Any, Any]:
    """Return an MCP server exposing exactly what `role` may call.

    Args:
        registry: The registry that owns validation, allowlisting, and audit.
        role: The single agent role this server serves.
    """

    server: Server[Any, Any] = Server(SERVER_NAME, instructions=SERVER_INSTRUCTIONS)
    available = registry.describe(role)

    # The SDK's decorators are untyped, so strict mode cannot see through
    # them. The handlers below are annotated; only the decorator is opaque.
    @server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
    async def list_tools() -> list[types.Tool]:
        """Advertise only the tools this role is allowed to call."""

        return [
            types.Tool(
                name=tool.name,
                description=tool.description,
                inputSchema=tool.input_schema(),
            )
            for tool in available
        ]

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
        """Execute one tool and return its result as JSON text.

        Failures are re-raised with the registry's error category and no
        internal detail. The category is what a caller can act on; a stack
        trace or a SQL message travelling over a transport is a liability.

        Raises:
            ValueError: For any failed call, carrying only its category.
        """

        try:
            payload = registry.call_json(role, name, arguments)
        except Exception as error:
            raise ValueError(f"{error_category(error)}: {name}") from error
        return [types.TextContent(type="text", text=json.dumps(payload, sort_keys=True))]

    return server
