"""Tool dispatch, per-role allowlisting, and audit (plan section 12.3).

Section 12.3 asks for six things: allowlist tools by agent role, validate every
argument with Pydantic before execution, deny path/SQL/URL/code parameters, add
timeouts and one bounded transient retry, record an audit line, and never log
secrets or unnecessary personal fields. All six live here, so a service in
`services.py` stays a plain function and every caller gets the same policy
whether it arrives through MCP, the API, or the graph.

The allowlist is derived from plan section 13, not invented. The Orchestrator
plans and does no arithmetic or retrieval; the Quantitative Analyst computes and
does not retrieve; the Evidence Retriever retrieves and does not compute; and the
Forecast Adjudicator is prohibited from making new tool calls at all, so its
allowlist is deliberately empty.
"""

import sqlite3
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from typing import Any, cast

from pydantic import BaseModel, ValidationError

from meridian.data.repository import UnknownAccountError
from meridian.tools.contracts import (
    AccountEvidenceResponse,
    AccountMetricsResponse,
    AccountRequest,
    EvidenceRequest,
    KnowledgeRequest,
    KnowledgeResponse,
    PointInTimeRequest,
    PriorAssessmentsResponse,
    RequesterRole,
    SupportSummaryResponse,
    ToolRequest,
    ToolResponse,
    WindowedRequest,
)
from meridian.tools.services import ToolServices, ToolUnavailableError

DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_TRANSIENT_RETRIES = 1
MAX_LOGGED_TEXT_CHARACTERS = 120

#: Errors worth one retry: they can succeed on a second attempt without the
#: caller changing anything. A validation error or an unknown account never can,
#: so retrying either would only double the latency of a certain failure.
TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    sqlite3.OperationalError,
    ConnectionError,
    TimeoutError,
)

#: Argument names safe to record verbatim in an audit line. Anything absent is
#: either free text (truncated) or a field this layer has no reason to keep.
_LOGGABLE_ARGUMENTS = frozenset({"account_id", "as_of", "window_weeks", "role", "source_families"})


class ToolPermissionError(PermissionError):
    """Raised when a role calls a tool outside its allowlist."""


class ToolNotFoundError(KeyError):
    """Raised when a caller names a tool that does not exist."""


@dataclass(frozen=True)
class ToolDescriptor:
    """One callable tool: its name, contract, and the service that answers it."""

    name: str
    description: str
    request_model: type[ToolRequest]
    handler: str

    def input_schema(self) -> dict[str, Any]:
        """Return the JSON Schema a client needs to call this tool.

        `role` is removed deliberately. It is authoritative from the session or
        the caller, never from the payload, so advertising it would invite a
        client to supply one -- and a client that can name its own role makes
        the allowlist advisory rather than enforced.
        """

        schema = self.request_model.model_json_schema()
        properties = {
            name: value for name, value in schema.get("properties", {}).items() if name != "role"
        }
        schema["properties"] = properties
        required = [name for name in schema.get("required", []) if name != "role"]
        if required:
            schema["required"] = required
        else:
            schema.pop("required", None)
        return schema


TOOLS: tuple[ToolDescriptor, ...] = (
    ToolDescriptor(
        name="get_account_profile",
        description="Sanitized identity and commercial terms for one account.",
        request_model=AccountRequest,
        handler="get_account_profile",
    ),
    ToolDescriptor(
        name="compute_account_metrics",
        description="Exact point-in-time features and the coverage behind them.",
        request_model=PointInTimeRequest,
        handler="compute_account_metrics",
    ),
    ToolDescriptor(
        name="get_usage_series",
        description="Bounded weekly telemetry for one account, aggregated across products.",
        request_model=WindowedRequest,
        handler="get_usage_series",
    ),
    ToolDescriptor(
        name="get_support_summary",
        description="Ticket counts, severity mix, sentiment, and CSAT over a window.",
        request_model=WindowedRequest,
        handler="get_support_summary",
    ),
    ToolDescriptor(
        name="get_external_events",
        description="Verified external events inside a window, capped at the dataset horizon.",
        request_model=WindowedRequest,
        handler="get_external_events",
    ),
    ToolDescriptor(
        name="retrieve_account_evidence",
        description="Graded, account-scoped citations for one qualitative sub-goal.",
        request_model=EvidenceRequest,
        handler="retrieve_account_evidence",
    ),
    ToolDescriptor(
        name="retrieve_knowledge",
        description="Knowledge-base guidance for one sub-goal; never account scoped.",
        request_model=KnowledgeRequest,
        handler="retrieve_knowledge",
    ),
    ToolDescriptor(
        name="get_prior_assessments",
        description="This system's own previous advisory decisions for one account.",
        request_model=AccountRequest,
        handler="get_prior_assessments",
    ),
)

TOOLS_BY_NAME: Mapping[str, ToolDescriptor] = {tool.name: tool for tool in TOOLS}

ROLE_ALLOWLIST: Mapping[RequesterRole, frozenset[str]] = {
    # Plans and inspects coverage; section 13.1 forbids arithmetic and direct
    # retrieval, so it may read identity and its own history and nothing else.
    "orchestrator": frozenset({"get_account_profile", "get_prior_assessments"}),
    # Section 13.2 produces metrics and numeric signals; retrieval is not its job.
    "quantitative_analyst": frozenset(
        {
            "get_account_profile",
            "compute_account_metrics",
            "get_usage_series",
            "get_support_summary",
            "get_external_events",
        }
    ),
    # Section 13.3 retrieves and grades qualitative evidence; it computes nothing.
    "evidence_retriever": frozenset(
        {"get_account_profile", "retrieve_account_evidence", "retrieve_knowledge"}
    ),
    # Section 13.4: "No new tool calls." An empty allowlist is the enforcement.
    "forecast_adjudicator": frozenset(),
}


@dataclass(frozen=True)
class ToolAuditRecord:
    """One line of the tool audit trail required by section 12.3."""

    tool: str
    role: str
    arguments: Mapping[str, Any]
    source_ids: tuple[str, ...] = ()
    coverage: Mapping[str, int] = field(default_factory=dict)
    latency_ms: float = 0.0
    attempts: int = 1
    error_category: str | None = None


def _safe_arguments(arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Return only the arguments that are safe and useful to record.

    Free text is truncated rather than dropped: an audit line that cannot show
    what was asked is not much of an audit line, but one that stores an
    unbounded caller-supplied string is a liability.
    """

    safe: dict[str, Any] = {}
    for key, value in arguments.items():
        if key in _LOGGABLE_ARGUMENTS:
            safe[key] = value
        elif key == "sub_goal" and isinstance(value, str):
            safe[key] = value[:MAX_LOGGED_TEXT_CHARACTERS]
    return safe


def _source_ids(response: ToolResponse) -> tuple[str, ...]:
    """Return the identifiers of the source rows behind a response.

    Section 12.3 wants source ids recorded so a claim can be traced to the rows
    that produced it.
    """

    if isinstance(response, SupportSummaryResponse):
        return response.ticket_ids
    if isinstance(response, AccountEvidenceResponse | KnowledgeResponse):
        return tuple(citation.doc_id for citation in response.citations)
    if isinstance(response, PriorAssessmentsResponse):
        return tuple(item.assessment_id for item in response.assessments)
    return ()


def _coverage(response: ToolResponse) -> dict[str, int]:
    """Return the coverage a response reports, if it reports any."""

    if isinstance(response, AccountEvidenceResponse):
        return {str(key): int(count) for key, count in response.source_coverage.items()}
    if isinstance(response, AccountMetricsResponse):
        return {str(key): int(count) for key, count in response.coverage.items()}
    return {}


def error_category(error: BaseException) -> str:
    """Classify a failure for the audit line without leaking its message."""

    if isinstance(error, ValidationError):
        return "validation"
    if isinstance(error, ToolPermissionError):
        return "forbidden"
    if isinstance(error, ToolNotFoundError):
        return "unknown_tool"
    if isinstance(error, UnknownAccountError):
        return "not_found"
    if isinstance(error, ToolUnavailableError):
        return "unavailable"
    if isinstance(error, FutureTimeoutError | TimeoutError):
        return "timeout"
    return "internal"


class ToolRegistry:
    """Dispatch validated, allowlisted tool calls and record what happened."""

    def __init__(
        self,
        services: ToolServices,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        retries: int = MAX_TRANSIENT_RETRIES,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not 0 <= retries <= MAX_TRANSIENT_RETRIES:
            raise ValueError(f"retries must be between 0 and {MAX_TRANSIENT_RETRIES}")
        self._services = services
        self._timeout_seconds = timeout_seconds
        self._retries = retries
        self._audit: list[ToolAuditRecord] = []

    @property
    def audit_log(self) -> tuple[ToolAuditRecord, ...]:
        """Return every call attempted through this registry, in order."""

        return tuple(self._audit)

    @staticmethod
    def describe(role: RequesterRole | None = None) -> tuple[ToolDescriptor, ...]:
        """Return the tools available, optionally narrowed to one role."""

        if role is None:
            return TOOLS
        allowed = ROLE_ALLOWLIST[role]
        return tuple(tool for tool in TOOLS if tool.name in allowed)

    def _authorize(self, role: RequesterRole, tool_name: str) -> ToolDescriptor:
        """Return the descriptor for an allowlisted call.

        Raises:
            ToolNotFoundError: If no such tool exists.
            ToolPermissionError: If this role may not call it.
        """

        tool = TOOLS_BY_NAME.get(tool_name)
        if tool is None:
            raise ToolNotFoundError(tool_name)
        if tool_name not in ROLE_ALLOWLIST[role]:
            raise ToolPermissionError(f"role {role!r} may not call {tool_name!r}")
        return tool

    def _run_with_timeout(self, tool: ToolDescriptor, request: ToolRequest) -> ToolResponse:
        """Run one service call, bounding how long a caller waits for it.

        The bound is on the wait, not on the work: Python cannot safely kill a
        running thread, so a genuinely stuck call still occupies its worker. The
        services here are local and CPU-bound, so this bounds the realistic
        failure -- a slow index load or a locked database -- without pretending
        to offer cancellation the runtime does not have.
        """

        handler = cast(Callable[[ToolRequest], ToolResponse], getattr(self._services, tool.handler))
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(handler, request).result(timeout=self._timeout_seconds)

    def call(
        self,
        role: RequesterRole,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> ToolResponse:
        """Validate, authorize, execute, and record one tool call.

        Raises:
            ToolNotFoundError: If no such tool exists.
            ToolPermissionError: If this role may not call the tool.
            ValidationError: If the arguments do not satisfy the contract.
        """

        payload = dict(arguments or {})
        # The role is authoritative from the caller, never from the payload: a
        # request that could name its own role would make the allowlist advisory.
        payload["role"] = role
        started = time.perf_counter()
        attempts = 0
        try:
            tool = self._authorize(role, tool_name)
            request = tool.request_model.model_validate(payload)
            last_error: BaseException | None = None
            for attempt in range(self._retries + 1):
                attempts = attempt + 1
                try:
                    response = self._run_with_timeout(tool, request)
                    break
                except TRANSIENT_ERRORS as error:
                    last_error = error
                    if attempt == self._retries:
                        raise
            else:  # pragma: no cover - the loop always breaks or raises
                raise last_error or RuntimeError("tool call failed without an error")
        except BaseException as error:
            self._audit.append(
                ToolAuditRecord(
                    tool=tool_name,
                    role=role,
                    arguments=_safe_arguments(payload),
                    latency_ms=round((time.perf_counter() - started) * 1000, 3),
                    attempts=max(attempts, 1),
                    error_category=error_category(error),
                )
            )
            raise

        self._audit.append(
            ToolAuditRecord(
                tool=tool_name,
                role=role,
                arguments=_safe_arguments(payload),
                source_ids=_source_ids(response),
                coverage=_coverage(response),
                latency_ms=round((time.perf_counter() - started) * 1000, 3),
                attempts=attempts,
            )
        )
        return response

    def call_json(
        self,
        role: RequesterRole,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return one tool result as JSON-ready data, for transport."""

        response = self.call(role, tool_name, arguments)
        assert isinstance(response, BaseModel)
        return response.model_dump(mode="json")
