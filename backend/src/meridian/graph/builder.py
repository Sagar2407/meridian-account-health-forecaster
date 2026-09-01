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
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from pydantic import ValidationError

from meridian.contracts import (
    AssessmentRequest,
    BlockedDecision,
    FinalResult,
    GuardrailDecision,
    NodeError,
    ReviewerDecision,
    ReviewInterrupt,
    Route,
    TraceEvent,
)
from meridian.data.paths import application_directory
from meridian.graph.nodes import GraphNodes
from meridian.graph.observability import TraceSink
from meridian.graph.routing import (
    route_conflict,
    route_coverage,
    route_human_review,
    route_intake,
    route_tot,
    route_verification,
)
from meridian.graph.runtime import GraphRuntime
from meridian.graph.state import GRAPH_RECURSION_LIMIT, ForecasterState
from meridian.graph.tracing import ordered


def _always_linear(_: ForecasterState) -> str:
    """Send every run down the fast path (the ablation control arm)."""

    return "fast_adjudication"


CHECKPOINT_FILENAME = "graph_checkpoints.sqlite"


#: How a run adjudicates. `conflict_gated` is the system; `linear` is the arm
#: section 15.7's ablation compares it against, and exists for no other reason.
Adjudication = Literal["conflict_gated", "linear"]


def build_graph(
    runtime: GraphRuntime,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    adjudication: Adjudication = "conflict_gated",
) -> Any:
    """Compile the assessment graph for one runtime.

    Args:
        runtime: The assembled dependencies.
        checkpointer: Optional persistence for resumable runs.
        adjudication: `conflict_gated` routes a material conflict into the
            bounded Tree-of-Thought search. `linear` sends every run down the
            fast path instead, which is the control arm section 15.7's ablation
            needs. The gate still runs and still records what it found, so the
            control arm can be compared case by case rather than in aggregate.

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
    graph.add_node("tot_adjudication", nodes.tot_adjudication)
    graph.add_node("verify_output", nodes.verify_output)
    graph.add_node("safe_fallback", nodes.fallback)
    graph.add_node("assign_route", nodes.route)
    graph.add_node("persist", nodes.persist)
    graph.add_node("await_review", nodes.await_review)

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

    # Section 15: the bounded Tree-of-Thought subgraph runs only when the
    # deterministic gate fires. It is a conditional branch, never the default
    # reasoning mode, because it costs four generations and a critic pass.
    graph.add_conditional_edges(
        "conflict_gate",
        route_conflict if adjudication == "conflict_gated" else _always_linear,
        {"fast_adjudication": "fast_adjudication", "tot_adjudication": "tot_adjudication"},
    )
    graph.add_edge("fast_adjudication", "verify_output")
    # A search that selected a winner is verified like any other draft; one that
    # abstained has already written its result and has nothing left to check.
    graph.add_conditional_edges(
        "tot_adjudication",
        route_tot,
        {"verify_output": "verify_output", "persist": "persist"},
    )
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
    # Section 16.6's interrupt. It sits *after* persistence on purpose: the
    # reviewer is shown a case that already exists in application memory, so a
    # run abandoned at the pause still leaves an open queue item rather than
    # nothing at all.
    graph.add_conditional_edges(
        "persist",
        route_human_review,
        {"await_review": "await_review", "end": END},
    )
    graph.add_edge("await_review", END)

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
    #: Set when the run paused on section 16.6's interrupt. The run is not
    #: finished: `resume_assessment` continues it with a typed decision.
    interrupt: ReviewInterrupt | None = None
    reviewer_decision: ReviewerDecision | None = None
    guardrails: tuple[GuardrailDecision, ...] = ()
    #: Provider attempts this run actually made, as the nodes charged them.
    #: The portfolio scan's shared budget is measured against this rather than
    #: against a count of trace events that happen to carry tokens.
    model_calls: int = 0

    @property
    def awaiting_review(self) -> bool:
        """Return whether this run is paused waiting for a person."""

        return self.interrupt is not None

    @property
    def completed(self) -> bool:
        """Return whether the run produced an advisory result."""

        return self.result is not None and not self.awaiting_review

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

    def guardrail(self, stage: str) -> GuardrailDecision | None:
        """Return the last verdict recorded for one guardrail stage."""

        for decision in reversed(self.guardrails):
            if decision.stage == stage:
                return decision
        return None


def _pending_interrupt(chunk: dict[str, Any]) -> ReviewInterrupt | None:
    """Return the review payload from a LangGraph interrupt chunk, if there is one.

    LangGraph reports a pause as an `__interrupt__` entry carrying its own
    `Interrupt` objects. Only the payload this graph put there is of interest,
    so anything that does not validate as one is ignored rather than guessed at.
    """

    pending = chunk.get("__interrupt__")
    if not pending:
        return None
    for item in pending if isinstance(pending, list | tuple) else [pending]:
        value = getattr(item, "value", item)
        if not isinstance(value, dict):
            continue
        try:
            return ReviewInterrupt.model_validate(value)
        except ValidationError:
            continue
    return None


def _collect(
    graph: Any,
    payload: Any,
    config: dict[str, Any],
    on_event: Callable[[TraceEvent], None] | None,
) -> tuple[dict[str, Any], ReviewInterrupt | None]:
    """Stream one graph invocation, returning its final state and any pause."""

    final: dict[str, Any] = {}
    pending: ReviewInterrupt | None = None
    for mode, chunk in graph.stream(payload, config, stream_mode=["updates", "values"]):
        if mode == "values":
            final = chunk
            continue
        pending = pending or _pending_interrupt(chunk)
        for update in chunk.values():
            if not isinstance(update, dict):
                continue
            for event in update.get("trace_summary") or ():
                if on_event is not None:
                    on_event(event)
    return final, pending


def _finish(
    identifier: str,
    thread: str,
    request: AssessmentRequest,
    final: dict[str, Any],
    pending: ReviewInterrupt | None,
) -> AssessmentRun:
    """Assemble the run record from the graph's final state."""

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
        interrupt=pending,
        reviewer_decision=final.get("reviewer_decision"),
        guardrails=tuple(final.get("guardrails") or ()),
        model_calls=int(final.get("model_calls") or 0),
    )


def _tee(
    on_event: Callable[[TraceEvent], None] | None, sink: TraceSink | None
) -> Callable[[TraceEvent], None] | None:
    """Return one callback that feeds both the caller and the trace sink.

    A sink failure must not end a run. Section 21.1 makes tracing mandatory, but
    a run that completed and could not write its trace is still a completed
    run, and losing the answer as well would be the worse outcome.
    """

    if sink is None:
        return on_event

    def publish(event: TraceEvent) -> None:
        """Hand one event to the caller, then to the sink."""

        if on_event is not None:
            on_event(event)
        with suppress(Exception):
            sink.write(event)

    return publish


def run_assessment(
    graph: Any,
    request: AssessmentRequest,
    run_id: str | None = None,
    thread_id: str | None = None,
    on_event: Callable[[TraceEvent], None] | None = None,
    pause_on_red: bool = False,
    sink: TraceSink | None = None,
) -> AssessmentRun:
    """Run one assessment to completion, streaming safe events as they happen.

    Args:
        graph: A compiled graph from `build_graph`.
        request: The validated request.
        run_id: Identifier for this attempt; generated when omitted.
        thread_id: Identifier for the conversation a checkpointer resumes on.
            Defaults to the run id, which makes each run its own thread.
        on_event: Called with each trace event as the graph produces it. This
            is the streaming surface of plan section 19.2; the SSE endpoint at
            `GET /api/assessments/{run_id}/events` is a thin wrapper over it.
        sink: Where to record the run's trace (plan section 21.1). Local
            tracing is mandatory, but *which* sink is the caller's choice: the
            API streams to a browser, an evaluation collects in memory, and a
            CLI appends to a file.
        pause_on_red: Stop on section 16.6's interrupt when the run routes red,
            instead of completing and leaving an open case. Requires the graph
            to have been compiled with a checkpointer -- there is nowhere to
            resume from without one -- and is never set for a portfolio scan,
            which must not block on a person.

    Returns:
        The finished run, including its full trace. A run that paused has
        `interrupt` set and is continued with `resume_assessment`.

    Raises:
        ValueError: If `pause_on_red` is set on a graph with no checkpointer.
    """

    if pause_on_red and getattr(graph, "checkpointer", None) is None:
        raise ValueError(
            "pause_on_red needs a checkpointer: a paused run has nowhere to resume from"
        )

    identifier = run_id or f"RUN-{uuid.uuid4().hex[:12]}"
    thread = thread_id or identifier
    payload: ForecasterState = {
        "run_id": identifier,
        "thread_id": thread,
        "request": request,
        "evidence_round": 0,
        "retrieval_retries": 0,
        "model_calls": 0,
        "spent_tokens": 0,
        "pause_on_red": pause_on_red,
        "errors": [],
        "trace_summary": [],
        "guardrails": [],
    }
    config: dict[str, Any] = {
        "configurable": {"thread_id": thread},
        "recursion_limit": GRAPH_RECURSION_LIMIT,
    }

    final, pending = _collect(graph, payload, config, _tee(on_event, sink))
    return _finish(identifier, thread, request, final, pending)


def resume_assessment(
    graph: Any,
    thread_id: str,
    decision: ReviewerDecision,
    on_event: Callable[[TraceEvent], None] | None = None,
    sink: TraceSink | None = None,
) -> AssessmentRun:
    """Continue a paused run with a reviewer's typed decision (section 16.6).

    Args:
        graph: The same compiled graph, with the same checkpointer.
        thread_id: The thread the run paused on.
        decision: The reviewer's action. It names the case it resolves, and the
            paused node refuses a decision naming a different one.
        on_event: Called with each trace event the resumed run produces.

    Returns:
        The completed run, with `reviewer_decision` set.

    Raises:
        ValueError: If the graph has no checkpointer to resume from.
    """

    if getattr(graph, "checkpointer", None) is None:
        raise ValueError("a paused run can only be resumed on a graph with a checkpointer")

    config: dict[str, Any] = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": GRAPH_RECURSION_LIMIT,
    }
    final, pending = _collect(
        graph, Command(resume=decision.model_dump(mode="json")), config, _tee(on_event, sink)
    )
    request = final.get("request")
    assert request is not None, "a resumed thread must carry the request it paused on"
    return _finish(final.get("run_id", thread_id), thread_id, request, final, pending)


__all__ = [
    "CHECKPOINT_FILENAME",
    "Adjudication",
    "AssessmentRun",
    "build_graph",
    "checkpoint_path",
    "resume_assessment",
    "run_assessment",
    "sqlite_checkpointer",
]
