"""MCP contract tests (plan section 12 deliverable, ADR 0002).

The risk with a protocol boundary is that it drifts from the thing it wraps:
the registry gains a tool, or tightens a rule, and the transport quietly keeps
serving the old contract. These tests pin the two together by running a real
in-memory MCP session and comparing what it advertises and returns against the
registry directly.
"""

import json

import pytest

from meridian.data.repository import RuntimeRepository
from meridian.memory.store import AssessmentStore
from meridian.tools.client import ToolCallError, connect
from meridian.tools.contracts import RequesterRole
from meridian.tools.registry import ROLE_ALLOWLIST, ToolRegistry
from meridian.tools.services import ToolServices

pytestmark = [pytest.mark.requires_dataset, pytest.mark.anyio]

ANALYST: RequesterRole = "quantitative_analyst"


@pytest.fixture
def anyio_backend() -> str:
    """Run these tests on asyncio only; the SDK supports both, we need one."""

    return "asyncio"


@pytest.fixture
def registry(runtime: RuntimeRepository, tmp_path: object) -> ToolRegistry:
    """Return a registry over the real dataset and temporary application memory."""

    store = AssessmentStore(tmp_path / "assessments.sqlite")  # type: ignore[operator]
    return ToolRegistry(ToolServices(runtime, store=store))


@pytest.fixture
def account_id(runtime: RuntimeRepository) -> str:
    """Return a stable account for per-call assertions."""

    return runtime.account_ids()[0]


async def test_the_session_advertises_exactly_the_role_allowlist(
    registry: ToolRegistry,
) -> None:
    """What a role can see over the wire is what section 12.3 permits."""

    async with connect(registry, ANALYST) as client:
        advertised = {tool.name for tool in await client.list_tools()}
    assert advertised == set(ROLE_ALLOWLIST[ANALYST])


async def test_the_adjudicator_session_advertises_nothing(registry: ToolRegistry) -> None:
    """Section 13.4 prohibits new tool calls; the session must show none."""

    async with connect(registry, "forecast_adjudicator") as client:
        assert await client.list_tools() == ()


async def test_every_advertised_tool_carries_a_callable_schema(
    registry: ToolRegistry,
) -> None:
    """A client can only construct a call from the schema it is given."""

    async with connect(registry, ANALYST) as client:
        tools = await client.list_tools()
    assert tools, "no tools advertised; the assertions below would be vacuous"
    for tool in tools:
        assert tool.description.strip()
        assert tool.input_schema["type"] == "object"
        assert "account_id" in tool.input_schema["properties"]
        # The role is supplied by the session, not the caller, so it must not be
        # something a client is asked to fill in.
        assert "role" not in tool.input_schema.get("required", [])


async def test_a_result_over_mcp_matches_the_registry_exactly(
    registry: ToolRegistry, runtime: RuntimeRepository, account_id: str
) -> None:
    """The transport must not reshape, round, or drop anything."""

    direct = ToolRegistry(ToolServices(runtime)).call_json(
        ANALYST, "get_support_summary", {"account_id": account_id}
    )
    async with connect(registry, ANALYST) as client:
        over_mcp = await client.call("get_support_summary", {"account_id": account_id})
    assert over_mcp == direct


async def test_the_cutoff_survives_the_transport(
    registry: ToolRegistry, runtime: RuntimeRepository, account_id: str
) -> None:
    """Every response carries its cutoff; JSON must not lose it."""

    async with connect(registry, ANALYST) as client:
        payload = await client.call("compute_account_metrics", {"account_id": account_id})
    assert payload["cutoff"] == runtime.cutoff_for(account_id).isoformat()


async def test_a_disallowed_tool_cannot_be_called_even_when_named_directly(
    registry: ToolRegistry, account_id: str
) -> None:
    """Not advertising a tool is not enough; calling it must fail too."""

    async with connect(registry, ANALYST) as client:
        with pytest.raises(ToolCallError) as failure:
            await client.call(
                "retrieve_account_evidence",
                {"account_id": account_id, "sub_goal": "renewal risk"},
            )
    assert "forbidden" in str(failure.value)


async def test_a_malicious_argument_is_refused_over_the_transport(
    registry: ToolRegistry,
) -> None:
    """The contract holds at the boundary, not only in a direct Python call."""

    async with connect(registry, ANALYST) as client:
        with pytest.raises(ToolCallError) as failure:
            await client.call("compute_account_metrics", {"account_id": "../../etc/passwd"})
    assert "validation" in str(failure.value)


async def test_an_error_carries_a_category_and_no_internal_detail(
    registry: ToolRegistry,
) -> None:
    """A transport that leaks SQL or a stack trace is a liability."""

    async with connect(registry, ANALYST) as client:
        with pytest.raises(ToolCallError) as failure:
            await client.call("compute_account_metrics", {"account_id": "ACC-999999"})
    message = str(failure.value)
    assert "not_found" in message
    for leak in ("Traceback", "sqlite", "SELECT", "/workspace", "/Users"):
        assert leak not in message


async def test_the_audit_log_records_calls_that_arrived_over_mcp(
    registry: ToolRegistry, account_id: str
) -> None:
    """Section 12.3's audit must not have a hole for the transport path."""

    async with connect(registry, ANALYST) as client:
        await client.call("get_external_events", {"account_id": account_id})
    recorded = registry.audit_log[-1]
    assert recorded.tool == "get_external_events"
    assert recorded.role == ANALYST
    assert recorded.error_category is None


async def test_results_are_a_single_json_object(registry: ToolRegistry, account_id: str) -> None:
    """One tool call returns one decodable object, not a stream of fragments."""

    async with connect(registry, ANALYST) as client:
        payload = await client.call("get_account_profile", {"account_id": account_id})
    assert isinstance(payload, dict)
    assert json.dumps(payload)
