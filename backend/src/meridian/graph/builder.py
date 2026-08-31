"""Assemble and run the LangGraph workflow (plan section 14).

The topology is section 14's flowchart, box for box. Nothing here decides
anything: every branch calls a pure function from `meridian.graph.routing`, so
the graph's shape can be read off this file and checked against the plan.

Node names differ from the state keys they write on purpose -- `assign_route`
writes `route` -- because LangGraph puts nodes and channels in one namespace and
refuses a name used by both.

The checkpointer is SQLite, per section 17.1, so an interrupted run resumes from
its last completed node instead of re-spending the tools and the tokens that got
it that far.
"""

import sqlite3
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from meridian.contracts import (
    AssessmentRequest,
    BlockedDecision,
    FinalResult,
    NodeError,
    Route,
    TraceEvent,
)
from meridian.data.paths import application_directory
from meridian.graph.nodes import GraphNodes
from meridian.graph.routing import (
    route_conflict,
    route_coverage,
    route_intake,
    route_verification,
)
from meridian.graph.runtime import GraphRuntime
from meridian.graph.state import GRAPH_RECURSION_LIMIT, ForecasterState
from meridian.graph.tracing import ordered

CHECKPOINT_FILENAME = "graph_checkpoints.sqlite"


def build_graph(runtime: GraphRuntime, checkpointer: BaseCheckpointSaver[Any] | None = None) -> Any:
    """Compile the assessment graph for one runtime.

    Args:
        runtime: The assembled dependencies.
        checkpointer: Optional persistence for resumable runs.

    Returns:
        The compiled graph. Its type is LangGraph's and is deliberately not
        re-exported: callers use `run_assessment` rather than driving it.
    """

    nodes = GraphNodes(runtime)
    graph: StateGraph[ForecasterState, None, ForecasterState, ForecasterState] = StateGraph(
        ForecasterState
    )

    graph.add_node("validate_request", nodes.intake)
    graph.add_node("safe_refusal", nodes.blocked)
    graph.add_node("load_context", nodes.load_context)
    graph.add_node("plan_sub_goals", nodes.plan)
    graph.add_node("quantitative_lane", nodes.quantitative)
    graph.add_node("retrieval_lane", nodes.retrieval)
    graph.add_node("merge_evidence", nodes.merge)
    graph.add_node("targeted_retry", nodes.targeted_retry)
    graph.add_node("degraded_result", nodes.degraded)
    graph.add_node("conflict_gate", nodes.conflict_gate)
    graph.add_node("fast_adjudication", nodes.fast_adjudication)
    graph.add_node("verify_output", nodes.verify_output)
    graph.add_node("safe_fallback", nodes.fallback)
    graph.add_node("assign_route", nodes.route)
    graph.add_node("persist", nodes.persist)

    graph.add_edge(START, "validate_request")
    graph.add_conditional_edges(
        "validate_request",
        route_intake,
        {"safe_refusal": "safe_refusal", "load_context": "load_context"},
    )
    graph.add_edge("safe_refusal", END)

    graph.add_edge("load_context", "plan_sub_goals")

    # The fan-out section 14 requires. Both lanes are triggered by the same node
    # and both feed the same fan-in, so LangGraph runs them in one superstep and
    # the trace shows two `*_completed` events between one plan and one merge.
    graph.add_edge("plan_sub_goals", "quantitative_lane")
    graph.add_edge("plan_sub_goals", "retrieval_lane")
    graph.add_edge("quantitative_lane", "merge_evidence")
    graph.add_edge("retrieval_lane", "merge_evidence")

    graph.add_conditional_edges(
        "merge_evidence",
        route_coverage,
        {
            "targeted_retry": "targeted_retry",
            "degraded_result": "degraded_result",
            "conflict_gate": "conflict_gate",
        },
    )
    # The only cycle in the graph. It is bounded by MAX_EVIDENCE_ROUNDS inside
    # `coverage_verdict`, which stops offering the recoverable branch once the
    # budget is spent, so the cycle cannot be entered a third time.
    graph.add_edge("targeted_retry", "merge_evidence")
    graph.add_edge("degraded_result", "persist")

    # Phase 6 adds a `tot_adjudication` target here. Until it exists, a
    # triggered conflict has nowhere to go, and the conflict gate is written so
    # that it never claims to have found one.
    graph.add_conditional_edges(
        "conflict_gate", route_conflict, {"fast_adjudication": "fast_adjudication"}
    )
    graph.add_edge("fast_adjudication", "verify_output")
    graph.add_conditional_edges(
        "verify_output",
        route_verification,
        {
            "assign_route": "assign_route",
            "fast_adjudication": "fast_adjudication",
            "safe_fallback": "safe_fallback",
        },
    )
    graph.add_edge("safe_fallback", "assign_route")
    graph.add_edge("assign_route", "persist")
    graph.add_edge("persist", END)

    return graph.compile(checkpointer=checkpointer)


def checkpoint_path() -> Path:
    """Return where resumable run state is stored."""

    return application_directory() / CHECKPOINT_FILENAME


@contextmanager
def sqlite_checkpointer(path: Path | None = None) -> Iterator[SqliteSaver]:
    """Yield a SQLite checkpointer, creating its schema if needed.

    `check_same_thread=False` because LangGraph runs the two evidence lanes in
    worker threads; the connection is used one statement at a time behind the
    saver's own lock.
    """

    target = path if path is not None else checkpoint_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target, check_same_thread=False)
    try:
        saver = SqliteSaver(connection)
        saver.setup()
        yield saver
    finally:
        connection.close()


@dataclass(frozen=True)
class AssessmentRun:
    """One completed run: what it decided, and everything it did to decide it."""

    run_id: str
    thread_id: str
    request: AssessmentRequest
    route: Route | None
    result: FinalResult | None
    blocked: BlockedDecision | None
    trace: tuple[TraceEvent, ...]
    errors: tuple[NodeError, ...]
    assessment_id: str | None = None
    review_case_id: str | None = None

    @property
    def completed(self) -> bool:
        """Return whether the run produced an advisory result."""

        return self.result is not None

    @property
    def abstained(self) -> bool:
        """Return whether the run declined to give a categorical outcome."""

        return self.result is not None and self.result.is_abstention

    @property
    def total_tokens(self) -> int:
        """Return the tokens this run spent, across every node."""

        return sum(event.total_tokens for event in self.trace)

    def events(self, name: str) -> tuple[TraceEvent, ...]:
        """Return every trace event of one kind, in order."""

        return tuple(event for event in self.trace if event.event == name)


def run_assessment(
    graph: Any,
    request: AssessmentRequest,
    run_id: str | None = None,
    thread_id: str | None = None,
    on_event: Callable[[TraceEvent], None] | None = None,
) -> AssessmentRun:
    """Run one assessment to completion, streaming safe events as they happen.

    Args:
        graph: A compiled graph from `build_graph`.
        request: The validated request.
        run_id: Identifier for this attempt; generated when omitted.
        thread_id: Identifier for the conversation a checkpointer resumes on.
            Defaults to the run id, which makes each run its own thread.
        on_event: Called with each trace event as the graph produces it. This
            is the streaming surface of plan section 19.2; Phase 8's SSE
            endpoint is a thin wrapper over it.

    Returns:
        The finished run, including its full trace.
    """

    identifier = run_id or f"RUN-{uuid.uuid4().hex[:12]}"
    thread = thread_id or identifier
    payload: ForecasterState = {
        "run_id": identifier,
        "thread_id": thread,
        "request": request,
        "evidence_round": 0,
        "retrieval_retries": 0,
        "errors": [],
        "trace_summary": [],
    }
    config: dict[str, Any] = {
        "configurable": {"thread_id": thread},
        "recursion_limit": GRAPH_RECURSION_LIMIT,
    }

    final: dict[str, Any] = {}
    for mode, chunk in graph.stream(payload, config, stream_mode=["updates", "values"]):
        if mode == "values":
            final = chunk
            continue
        for update in chunk.values():
            if not isinstance(update, dict):
                continue
            for event in update.get("trace_summary") or ():
                if on_event is not None:
                    on_event(event)

    return AssessmentRun(
        run_id=identifier,
        thread_id=thread,
        request=request,
        route=final.get("route"),
        result=final.get("final_result"),
        blocked=final.get("blocked"),
        trace=ordered(final.get("trace_summary") or ()),
        errors=tuple(final.get("errors") or ()),
        assessment_id=final.get("assessment_id"),
        review_case_id=final.get("review_case_id"),
    )


__all__ = [
    "CHECKPOINT_FILENAME",
    "AssessmentRun",
    "build_graph",
    "checkpoint_path",
    "run_assessment",
    "sqlite_checkpointer",
]
