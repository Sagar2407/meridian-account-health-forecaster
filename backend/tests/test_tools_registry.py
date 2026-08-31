"""Tool allowlisting, argument validation, and audit (plan section 12.3).

The Phase 4 exit gate is that tools hold their guarantees "even when called with
malicious arguments". These tests supply those arguments: identifiers shaped
like paths and SQL, sub-goals carrying URLs and shell metacharacters, windows
large enough to reach past a cutoff, dates beyond the dataset, unknown fields,
and a payload that tries to name its own role.
"""

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from meridian.data.constants import DATASET_AS_OF_DATE, FORBIDDEN_RUNTIME_FIELDS
from meridian.data.repository import RuntimeRepository, UnknownAccountError
from meridian.memory.store import AssessmentStore
from meridian.tools.contracts import MAX_SUB_GOAL_CHARACTERS, MAX_WINDOW_WEEKS
from meridian.tools.registry import (
    ROLE_ALLOWLIST,
    TOOLS,
    ToolNotFoundError,
    ToolPermissionError,
    ToolRegistry,
)
from meridian.tools.services import ToolServices

pytestmark = pytest.mark.requires_dataset

DETERMINISTIC_TOOLS = (
    "get_account_profile",
    "compute_account_metrics",
    "get_usage_series",
    "get_support_summary",
    "get_external_events",
)


@pytest.fixture
def registry(runtime: RuntimeRepository, tmp_path: object) -> ToolRegistry:
    """Return a registry over the real dataset and a temporary memory store."""

    store = AssessmentStore(tmp_path / "assessments.sqlite")  # type: ignore[operator]
    return ToolRegistry(ToolServices(runtime, store=store))


@pytest.fixture
def account_id(runtime: RuntimeRepository) -> str:
    """Return a stable account for per-call assertions."""

    return runtime.account_ids()[0]


def test_the_registry_exposes_every_tool_the_plan_requires() -> None:
    """Section 12.1 names eight read-only tools; all eight must be callable."""

    assert {tool.name for tool in TOOLS} == {
        "get_account_profile",
        "compute_account_metrics",
        "get_usage_series",
        "get_support_summary",
        "get_external_events",
        "retrieve_account_evidence",
        "retrieve_knowledge",
        "get_prior_assessments",
    }


def test_every_tool_publishes_a_usable_input_schema() -> None:
    """An MCP client can only call a tool it can describe."""

    for tool in TOOLS:
        schema = tool.input_schema()
        assert schema["type"] == "object"
        assert tool.description.strip()
        # The role comes from the session, so a client is never asked for it.
        assert "role" not in schema["properties"]
        assert "role" not in schema.get("required", [])


def test_the_adjudicator_may_call_nothing(registry: ToolRegistry, account_id: str) -> None:
    """Section 13.4 prohibits new tool calls, so the allowlist is empty."""

    assert ROLE_ALLOWLIST["forecast_adjudicator"] == frozenset()
    assert registry.describe("forecast_adjudicator") == ()
    for tool in TOOLS:
        with pytest.raises(ToolPermissionError):
            registry.call("forecast_adjudicator", tool.name, {"account_id": account_id})


@pytest.mark.parametrize(
    ("role", "tool_name"),
    [
        ("orchestrator", "compute_account_metrics"),
        ("orchestrator", "retrieve_account_evidence"),
        ("quantitative_analyst", "retrieve_account_evidence"),
        ("quantitative_analyst", "retrieve_knowledge"),
        ("evidence_retriever", "compute_account_metrics"),
        ("evidence_retriever", "get_usage_series"),
    ],
)
def test_roles_cannot_reach_outside_their_allowlist(
    registry: ToolRegistry, account_id: str, role: str, tool_name: str
) -> None:
    """Section 13 gives each agent a job; the allowlist is how that is enforced."""

    with pytest.raises(ToolPermissionError):
        registry.call(role, tool_name, {"account_id": account_id, "sub_goal": "renewal risk"})  # type: ignore[arg-type]


def test_a_payload_cannot_promote_itself_to_another_role(
    registry: ToolRegistry, account_id: str
) -> None:
    """The caller's role is authoritative; a role inside the payload is ignored."""

    with pytest.raises(ToolPermissionError):
        registry.call(
            "orchestrator",
            "compute_account_metrics",
            {"account_id": account_id, "role": "quantitative_analyst"},
        )


@pytest.mark.parametrize(
    "malicious",
    [
        "../../etc/passwd",
        "ACC-1042; DROP TABLE accounts",
        "ACC-1042 OR 1=1",
        "ACC-*",
        "acc-1042",
        "ACC-1042/../ACC-1043",
        "'; SELECT * FROM renewal_outcomes --",
        "ACC-" + "9" * 40,
        "",
    ],
)
def test_a_malformed_account_id_never_reaches_a_service(
    registry: ToolRegistry, malicious: str
) -> None:
    """The identifier is a pattern, so injection shapes fail before execution."""

    with pytest.raises(ValidationError):
        registry.call("quantitative_analyst", "compute_account_metrics", {"account_id": malicious})


@pytest.mark.parametrize(
    "malicious",
    [
        "read file:///etc/passwd",
        "fetch https://example.com/leak",
        "../../../secrets",
        "/etc/shadow",
        "~/.ssh/id_rsa",
        "renewal risk; rm -rf /",
        "risk `whoami`",
        "risk $(cat /etc/passwd)",
        "SELECT * FROM renewal_outcomes",
        "drop table accounts",
        "risk\x00truncated",
    ],
)
def test_a_sub_goal_carrying_an_injection_shape_is_refused(
    registry: ToolRegistry, account_id: str, malicious: str
) -> None:
    """Section 12.3 denies path, SQL, URL, and code parameters outright."""

    with pytest.raises(ValidationError):
        registry.call(
            "evidence_retriever",
            "retrieve_account_evidence",
            {"account_id": account_id, "sub_goal": malicious},
        )


def test_ordinary_sub_goals_still_pass(registry: ToolRegistry) -> None:
    """The rejection rule must not be so broad that real questions fail.

    Without this, a stricter and stricter filter would look like progress while
    quietly making the tool useless.
    """

    from meridian.tools.contracts import EvidenceRequest

    for wording in (
        "Why is this account at risk before renewal?",
        "What did the champion say in the last QBR?",
        "Summarise unresolved P1 escalations and their impact.",
        "Has adoption fallen more than 20% quarter-over-quarter?",
        "renewal risk: sponsor change, low adoption & open tickets",
    ):
        request = EvidenceRequest(
            role="evidence_retriever", account_id="ACC-1042", sub_goal=wording
        )
        assert request.sub_goal


def test_an_oversized_sub_goal_is_refused(registry: ToolRegistry, account_id: str) -> None:
    """Free text is bounded so a caller cannot push unbounded input downstream."""

    with pytest.raises(ValidationError):
        registry.call(
            "evidence_retriever",
            "retrieve_account_evidence",
            {"account_id": account_id, "sub_goal": "a" * (MAX_SUB_GOAL_CHARACTERS + 1)},
        )


def test_unknown_arguments_are_refused_rather_than_ignored(
    registry: ToolRegistry, account_id: str
) -> None:
    """Silently dropping an argument hides a caller's mistaken assumption."""

    with pytest.raises(ValidationError):
        registry.call(
            "quantitative_analyst",
            "compute_account_metrics",
            {"account_id": account_id, "include_labels": True},
        )


def test_an_as_of_beyond_the_dataset_is_refused(registry: ToolRegistry, account_id: str) -> None:
    """A caller asking past the horizon has made a mistake worth surfacing."""

    with pytest.raises(ValidationError):
        registry.call(
            "quantitative_analyst",
            "compute_account_metrics",
            {
                "account_id": account_id,
                "as_of": (DATASET_AS_OF_DATE + timedelta(days=1)).isoformat(),
            },
        )


@pytest.mark.parametrize("tool_name", DETERMINISTIC_TOOLS)
def test_no_tool_can_be_argued_past_its_cutoff(
    registry: ToolRegistry, account_id: str, runtime: RuntimeRepository, tool_name: str
) -> None:
    """A later as-of must not widen visibility, whatever the caller asks for."""

    canonical = runtime.cutoff_for(account_id)
    arguments: dict[str, object] = {"account_id": account_id}
    if tool_name != "get_account_profile":
        arguments["as_of"] = DATASET_AS_OF_DATE.isoformat()
    if tool_name in {"get_usage_series", "get_support_summary", "get_external_events"}:
        arguments["window_weeks"] = MAX_WINDOW_WEEKS
    response = registry.call("quantitative_analyst", tool_name, arguments)
    assert response.cutoff <= canonical
    assert response.cutoff <= DATASET_AS_OF_DATE


def test_an_enormous_window_still_cannot_reach_past_the_cutoff(
    registry: ToolRegistry, account_id: str, runtime: RuntimeRepository
) -> None:
    """The window is bounded, and it is measured backwards from the cutoff."""

    cutoff = runtime.cutoff_for(account_id)
    usage = registry.call(
        "quantitative_analyst",
        "get_usage_series",
        {"account_id": account_id, "window_weeks": MAX_WINDOW_WEEKS},
    )
    points = usage.points  # type: ignore[attr-defined]
    assert points, "no telemetry returned; the cutoff assertion below would be vacuous"
    assert max(point.week_start for point in points) <= cutoff

    with pytest.raises(ValidationError):
        registry.call(
            "quantitative_analyst",
            "get_usage_series",
            {"account_id": account_id, "window_weeks": MAX_WINDOW_WEEKS + 1},
        )


@pytest.mark.parametrize("tool_name", ["get_account_profile", "compute_account_metrics"])
def test_no_forbidden_field_survives_the_tool_boundary(
    registry: ToolRegistry, account_id: str, tool_name: str
) -> None:
    """Latent targets must not reach an agent under any tool name."""

    payload = registry.call_json("quantitative_analyst", tool_name, {"account_id": account_id})
    flattened = str(payload).lower()
    for forbidden in FORBIDDEN_RUNTIME_FIELDS:
        assert forbidden not in flattened


def test_an_unknown_account_is_rejected_not_answered(registry: ToolRegistry) -> None:
    """A well-formed but non-existent account must not return an empty answer."""

    with pytest.raises(UnknownAccountError):
        registry.call(
            "quantitative_analyst", "compute_account_metrics", {"account_id": "ACC-999999"}
        )


def test_an_unknown_tool_is_rejected(registry: ToolRegistry, account_id: str) -> None:
    """A caller cannot reach a service by naming something that does not exist."""

    with pytest.raises(ToolNotFoundError):
        registry.call("quantitative_analyst", "get_renewal_outcome", {"account_id": account_id})


def test_every_call_is_audited_with_its_sources_and_no_free_text(
    registry: ToolRegistry, account_id: str
) -> None:
    """Section 12.3: record tool, safe arguments, source ids, latency, coverage."""

    registry.call("quantitative_analyst", "get_support_summary", {"account_id": account_id})
    with pytest.raises(ToolPermissionError):
        registry.call("orchestrator", "get_usage_series", {"account_id": account_id})

    log = registry.audit_log
    assert len(log) == 2

    succeeded, refused = log
    assert succeeded.tool == "get_support_summary"
    assert succeeded.role == "quantitative_analyst"
    assert succeeded.error_category is None
    assert succeeded.latency_ms >= 0.0
    assert succeeded.attempts == 1
    assert set(succeeded.arguments) <= {"account_id", "as_of", "window_weeks", "role"}
    assert all(ticket.startswith("TCK-") for ticket in succeeded.source_ids)

    assert refused.error_category == "forbidden"
    assert refused.source_ids == ()


def test_audit_truncates_free_text_rather_than_storing_it_whole(
    registry: ToolRegistry, account_id: str
) -> None:
    """A sub-goal is recorded so a call is explicable, but never unbounded."""

    from meridian.tools.registry import MAX_LOGGED_TEXT_CHARACTERS

    long_goal = "renewal risk " * 60
    with pytest.raises(Exception):  # noqa: B017 - retrieval is not configured here
        registry.call(
            "evidence_retriever",
            "retrieve_account_evidence",
            {"account_id": account_id, "sub_goal": long_goal},
        )
    recorded = registry.audit_log[-1].arguments["sub_goal"]
    assert len(recorded) <= MAX_LOGGED_TEXT_CHARACTERS


def test_a_missing_collaborator_is_a_precise_error(
    runtime: RuntimeRepository, account_id: str
) -> None:
    """Retrieval needs an index; its absence must not look like an empty result."""

    from meridian.tools.services import ToolUnavailableError

    bare = ToolRegistry(ToolServices(runtime))
    with pytest.raises(ToolUnavailableError):
        bare.call(
            "evidence_retriever",
            "retrieve_account_evidence",
            {"account_id": account_id, "sub_goal": "renewal risk"},
        )
    assert bare.audit_log[-1].error_category == "unavailable"


def test_dates_are_serialised_as_iso_strings_for_transport(
    registry: ToolRegistry, account_id: str
) -> None:
    """MCP carries JSON, so a response has to survive the round trip."""

    payload = registry.call_json(
        "quantitative_analyst", "get_external_events", {"account_id": account_id}
    )
    assert date.fromisoformat(str(payload["cutoff"]))
