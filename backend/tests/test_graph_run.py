"""The assembled graph, end to end (plan section 14 and the Phase 5 exit gate).

Three things have to be shown here rather than argued:

1. **The two evidence lanes really run in parallel.** Two trace events in a row
   prove nothing about concurrency, so the lanes are instrumented and their
   wall-clock intervals are checked for overlap.
2. **No cycle is unbounded.** The one cycle in the graph is exercised with a
   retriever that never succeeds, and the number of laps is asserted.
3. **Exhausted retrieval never emits a categorical label.** The degraded run is
   checked for the absence of an outcome, not merely for a different route.

Every run here is offline: no provider is configured, so the narrative is
composed deterministically and the whole file costs nothing to run.
"""

import json
import threading
import time
from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest

from meridian.agents.evidence_retriever import EvidenceRetriever
from meridian.agents.forecast_adjudicator import ForecastAdjudicator
from meridian.contracts import (
    OUTCOME_CLASSES,
    TOT_BEAM_WIDTH,
    AssessmentRequest,
    Citation,
    ForecastDecision,
    InsufficientEvidenceDecision,
    RequestedData,
    RetrievalEvidence,
    RetrievalObservation,
    ReviewerDecision,
    SubGoal,
    SubGoalKind,
)
from meridian.data.repository import RuntimeRepository
from meridian.graph import build_graph, resume_assessment, run_assessment, sqlite_checkpointer
from meridian.graph.observability import JsonlTraceSink
from meridian.graph.runtime import GraphRuntime
from meridian.graph.state import MAX_EVIDENCE_ROUNDS, ForecasterState
from meridian.llm.fake import ScriptedGenerator
from meridian.memory.store import AssessmentStore
from meridian.model.artifacts import ModelArtifact
from meridian.tools.registry import ToolRegistry
from meridian.tools.services import ToolServices, ToolUnavailableError
from stub_encoder import build_stub_service

pytestmark = pytest.mark.requires_dataset

QUESTION = "What is the renewal outlook, and does support history explain it?"


@pytest.fixture(scope="module")
def accounts(runtime: RuntimeRepository) -> tuple[str, ...]:
    """Return a small, stable slice of the portfolio to index."""

    return runtime.account_ids()[:10]


@pytest.fixture(scope="module")
def graph_runtime(
    runtime: RuntimeRepository,
    forecaster_artifact: ModelArtifact,
    accounts: tuple[str, ...],
    tmp_path_factory: pytest.TempPathFactory,
) -> GraphRuntime:
    """Assemble a complete runtime with no language-model provider.

    The retrieval index is the shared offline stub, so these tests exercise the
    real search, grading, and citation path without downloading an encoder.
    """

    directory = tmp_path_factory.mktemp("graph-index")
    service = build_stub_service(runtime, directory, accounts)
    store = AssessmentStore(tmp_path_factory.mktemp("graph-memory") / "assessments.sqlite")
    services = ToolServices(runtime, retrieval=service, store=store)
    return GraphRuntime.assemble(
        repository=runtime,
        registry=ToolRegistry(services),
        artifact=forecaster_artifact,
        generator=None,
        store=store,
    )


@pytest.fixture(scope="module")
def classified(graph_runtime: GraphRuntime, accounts: tuple[str, ...]) -> dict[str, list[str]]:
    """Split the indexed accounts by whether the conflict gate fires on them.

    Which accounts conflict depends on the evidence, so it is measured rather
    than hard-coded: an account list pinned in a test would silently stop
    testing what it names the first time the index or the rules change.
    """

    graph = build_graph(graph_runtime)
    groups: dict[str, list[str]] = {"linear": [], "conflict": []}
    for account in accounts:
        run = run_assessment(graph, _request(account))
        key = "conflict" if run.events("conflict_detected") else "linear"
        groups[key].append(account)
    return groups


@pytest.fixture(scope="module")
def account_id(classified: dict[str, list[str]]) -> str:
    """Return an account the conflict gate clears, so the fast path runs."""

    if not classified["linear"]:
        pytest.skip("no indexed account takes the linear path")
    return classified["linear"][0]


@pytest.fixture(scope="module")
def linear_accounts(classified: dict[str, list[str]]) -> list[str]:
    """Return every indexed account the conflict gate clears."""

    if len(classified["linear"]) < 4:
        pytest.skip("too few linear-path accounts to run the adjudication variants")
    return classified["linear"]


@pytest.fixture(scope="module")
def conflict_account(classified: dict[str, list[str]]) -> str:
    """Return an account whose evidence the gate finds in material conflict."""

    if not classified["conflict"]:
        pytest.skip("no indexed account triggers the conflict gate")
    return classified["conflict"][0]


def _request(account_id: str, question: str = QUESTION, **overrides: Any) -> AssessmentRequest:
    """Return an assessment request."""

    return AssessmentRequest(account_id=account_id, question=question, **overrides)


class _StubRetriever:
    """A retriever whose answers a test dictates, for the failure paths."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.calls: list[tuple[SubGoalKind, ...]] = []

    def gather(
        self,
        account_id: str,
        cutoff: date,
        plan: Sequence[SubGoal],
        as_of: date | None = None,
        only: Sequence[SubGoalKind] | None = None,
    ) -> RetrievalEvidence:
        selected = [item for item in plan if only is None or item.kind in set(only)]
        self.calls.append(tuple(item.kind for item in selected))
        if self.mode == "unavailable":
            return RetrievalEvidence(
                account_id=account_id,
                cutoff=cutoff,
                available=False,
                unavailable_reason="the retrieval index is unavailable",
            )
        if self.mode == "raises":
            raise ToolUnavailableError("the retrieval index is unavailable")
        return RetrievalEvidence(
            account_id=account_id,
            cutoff=cutoff,
            observations=tuple(
                RetrievalObservation(
                    sub_goal=item.kind,
                    query=item.query,
                    insufficient_evidence=True,
                    insufficiency_reason="no account passage passed grading",
                )
                for item in selected
                if item.kind != "playbook_guidance"
            ),
        )


def _with_retriever(base: GraphRuntime, retriever: object) -> GraphRuntime:
    """Return the runtime with its retrieval lane replaced."""

    return replace(base, retriever=cast("EvidenceRetriever", retriever))


# -- The fast path -----------------------------------------------------------


def test_the_fast_path_produces_a_grounded_verified_decision(
    graph_runtime: GraphRuntime, account_id: str
) -> None:
    """The end-to-end deliverable: one run, one decision, one trace."""

    run = run_assessment(build_graph(graph_runtime), _request(account_id))

    assert isinstance(run.result, ForecastDecision)
    assert run.route in {"green", "amber", "red"}
    assert run.result.route == run.route
    assert run.result.outcome in run.result.distribution
    assert run.result.cutoff <= graph_runtime.repository.cutoff_for(account_id)
    assert run.result.drivers
    assert run.result.rationale
    assert run.result.recommended_action
    assert run.errors == ()
    # No provider is configured, so the run must cost nothing and say so.
    assert run.total_tokens == 0
    assert run.result.narrative_source == "deterministic"
    assert {guardrail.stage for guardrail in run.guardrails} == {
        "intake",
        "execution",
        "evidence",
        "output",
        "routing",
    }


def test_the_trace_records_the_whole_run_in_order(
    graph_runtime: GraphRuntime, account_id: str
) -> None:
    """Section 21.1 makes local tracing mandatory; this is what it must contain."""

    run = run_assessment(build_graph(graph_runtime), _request(account_id))
    events = [event.event for event in run.trace]

    assert events[0] == "run_started"
    assert events[-1] == "run_completed"
    for required in (
        "request_validated",
        "context_loaded",
        "plan_created",
        "quantitative_completed",
        "retrieval_attempted",
        "evidence_merged",
        "coverage_evaluated",
        "conflict_evaluated",
        "decision_drafted",
        "output_verified",
        "decision_routed",
        "decision_persisted",
    ):
        assert required in events, required
    assert [event.sequence for event in run.trace] == sorted(event.sequence for event in run.trace)
    assert all(event.run_id == run.run_id for event in run.trace)


def test_no_trace_event_carries_a_prompt_or_a_raw_reply(
    graph_runtime: GraphRuntime, account_id: str
) -> None:
    """Section 21.3: the trace is published, so it is checked, not trusted."""

    run = run_assessment(build_graph(graph_runtime), _request(account_id))
    for event in run.trace:
        assert "prompt" not in event.payload
        assert "messages" not in event.payload
        assert all(
            isinstance(value, str | int | float | bool | list | type(None))
            for value in event.payload.values()
        )


def test_the_adjudicator_makes_no_tool_calls(graph_runtime: GraphRuntime, account_id: str) -> None:
    """Section 13.4 says so plainly, and its allowlist is empty."""

    registry = graph_runtime.registry
    before = len(registry.audit_log)
    run_assessment(build_graph(graph_runtime), _request(account_id))
    calls = registry.audit_log[before:]

    assert calls, "the run made no tool calls at all; this check would pass vacuously"
    assert {record.role for record in calls} == {
        "orchestrator",
        "quantitative_analyst",
        "evidence_retriever",
    }
    assert all(record.error_category is None for record in calls)


def test_the_decision_is_persisted_with_its_route(
    graph_runtime: GraphRuntime, linear_accounts: list[str]
) -> None:
    """Section 17.2 persists snapshots; Phase 5's deliverable requires it."""

    run = run_assessment(build_graph(graph_runtime), _request(linear_accounts[1]))
    assert run.assessment_id is not None
    assert graph_runtime.store is not None

    stored = graph_runtime.store.recent_assessments(linear_accounts[1])
    assert stored[0].assessment_id == run.assessment_id
    assert stored[0].decision == run.route
    assert stored[0].cutoff == run.result.cutoff if run.result else False


# -- Parallel lanes ----------------------------------------------------------


def test_the_two_evidence_lanes_run_concurrently(
    graph_runtime: GraphRuntime, account_id: str
) -> None:
    """The Phase 5 exit gate: parallel lanes confirmed.

    Adjacent trace events would not show this -- two nodes run one after another
    produce the same ordering. So each lane records when it entered and left,
    and the test asserts the intervals overlap. If LangGraph ever ran the
    supersteps serially, the overlap would be negative and this fails.
    """

    marks: list[tuple[str, str, float]] = []
    lock = threading.Lock()

    def _mark(lane: str, moment: str) -> None:
        with lock:
            marks.append((lane, moment, time.monotonic()))

    class TimedAnalyst:
        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def analyse(self, account: str, as_of: date | None = None) -> Any:
            _mark("quantitative", "enter")
            time.sleep(0.15)
            result = self._inner.analyse(account, as_of)
            _mark("quantitative", "exit")
            return result

    class TimedRetriever:
        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def gather(self, *args: Any, **kwargs: Any) -> Any:
            _mark("retrieval", "enter")
            time.sleep(0.15)
            result = self._inner.gather(*args, **kwargs)
            _mark("retrieval", "exit")
            return result

    instrumented = replace(
        graph_runtime,
        analyst=cast(Any, TimedAnalyst(graph_runtime.analyst)),
        retriever=cast(Any, TimedRetriever(graph_runtime.retriever)),
        store=None,
    )
    run_assessment(build_graph(instrumented), _request(account_id))

    spans: dict[str, dict[str, float]] = {}
    for lane, moment, stamp in marks:
        spans.setdefault(lane, {})[moment] = stamp
    quantitative, retrieval = spans["quantitative"], spans["retrieval"]
    overlap = min(quantitative["exit"], retrieval["exit"]) - max(
        quantitative["enter"], retrieval["enter"]
    )
    assert overlap > 0, f"the lanes did not overlap: {marks}"


# -- Degraded retrieval ------------------------------------------------------


def test_exhausted_retrieval_never_emits_a_categorical_label(
    graph_runtime: GraphRuntime, account_id: str
) -> None:
    """The Phase 5 exit gate, and section 4's tenth definition-of-done item."""

    retriever = _StubRetriever("empty")
    run = run_assessment(
        build_graph(_with_retriever(graph_runtime, retriever)), _request(account_id)
    )

    assert isinstance(run.result, InsufficientEvidenceDecision)
    assert run.abstained is True
    assert not hasattr(run.result, "outcome")
    assert run.result.reason_code == "RETRIEVAL_EXHAUSTED"
    # The degraded answer is not an empty one: section 2's instructor feedback
    # asks for verified telemetry, a gap notice, and a targeted data request.
    assert run.result.verified_metrics
    assert run.result.gaps
    assert run.result.requested_data
    assert run.result.route in {"amber", "red"}
    assert "degraded_result" in [event.event for event in run.trace]


def test_the_evidence_cycle_runs_at_most_twice(
    graph_runtime: GraphRuntime, account_id: str
) -> None:
    """The Phase 5 exit gate: no unbounded cycle.

    The retriever here never succeeds, so the run would loop forever if the
    budget were advisory. It is not: `coverage_verdict` stops offering the
    recoverable branch once the rounds are spent.
    """

    retriever = _StubRetriever("empty")
    run = run_assessment(
        build_graph(_with_retriever(graph_runtime, retriever)), _request(account_id)
    )

    assert len(run.events("evidence_merged")) == MAX_EVIDENCE_ROUNDS
    assert len(run.events("retrieval_retried")) == MAX_EVIDENCE_ROUNDS - 1
    assert len(retriever.calls) == MAX_EVIDENCE_ROUNDS
    assert run.abstained is True


def test_the_second_round_asks_only_for_what_is_missing(
    graph_runtime: GraphRuntime, account_id: str
) -> None:
    """Section 13.1 allows one *targeted* round, not a second full sweep."""

    found = Citation(
        doc_id="NOTE-1",
        parent_id="NOTE-1",
        source_type="csm_note",
        subtype="Quarterly Business Review",
        account_id=account_id,
        doc_date=date(2025, 6, 1),
        excerpt="Adoption is steady across the two licensed products.",
        retrieval_score=0.71,
    )

    class PartialRetriever(_StubRetriever):
        """Answer the adoption sub-goal on the first round and nothing else."""

        def gather(self, *args: Any, **kwargs: Any) -> RetrievalEvidence:
            evidence = super().gather(*args, **kwargs)
            if len(self.calls) > 1:
                return evidence
            observations = tuple(
                item
                if item.sub_goal != "adoption"
                else item.model_copy(update={"insufficient_evidence": False, "citations": (found,)})
                for item in evidence.observations
            )
            return evidence.model_copy(update={"observations": observations})

    retriever = PartialRetriever("empty")
    run_assessment(build_graph(_with_retriever(graph_runtime, retriever)), _request(account_id))

    assert len(retriever.calls) == 2
    assert "adoption" not in retriever.calls[1]
    assert set(retriever.calls[1]) < set(retriever.calls[0])


def test_unavailable_retrieval_degrades_without_spending_a_retry(
    graph_runtime: GraphRuntime, account_id: str
) -> None:
    """An unbuilt index is not a gap another search could close."""

    retriever = _StubRetriever("unavailable")
    run = run_assessment(
        build_graph(_with_retriever(graph_runtime, retriever)), _request(account_id)
    )

    assert isinstance(run.result, InsufficientEvidenceDecision)
    assert len(retriever.calls) == 1
    assert run.events("retrieval_retried") == ()
    assert run.route == "red", "a critical gap is a red route (section 16.5)"
    assert run.review_case_id is not None
    assert any("unavailable" in gap for gap in run.result.gaps)


def test_a_raising_retrieval_lane_is_classified_rather_than_fatal(
    graph_runtime: GraphRuntime, account_id: str
) -> None:
    """Section 14.3: failures are classified and recovered from, not propagated."""

    run = run_assessment(
        build_graph(_with_retriever(graph_runtime, _StubRetriever("raises"))),
        _request(account_id),
    )
    assert run.abstained is True
    assert [error.node for error in run.errors] == ["retrieval_lane"]
    assert run.errors[0].category == "permanent_tool"
    assert run.errors[0].code == "RETRIEVAL_EXHAUSTED"


def test_without_a_forecaster_the_run_degrades_instead_of_guessing(
    graph_runtime: GraphRuntime, account_id: str
) -> None:
    """Section 13.2: never substitute an estimate for a model that is not there."""

    run = run_assessment(
        build_graph(
            replace(graph_runtime, artifact=None, analyst=_analyst_without_a_model(graph_runtime))
        ),
        _request(account_id),
    )
    assert isinstance(run.result, InsufficientEvidenceDecision)
    assert run.route == "red"
    assert any("forecaster" in gap for gap in run.result.gaps)


def _analyst_without_a_model(runtime: GraphRuntime) -> Any:
    """Return a quantitative lane with no artifact loaded."""

    from meridian.agents.quantitative_analyst import QuantitativeAnalyst

    return QuantitativeAnalyst(runtime.registry, None)


# -- Blocked requests --------------------------------------------------------


def test_a_blocked_request_ends_before_any_tool_runs(
    graph_runtime: GraphRuntime, account_id: str
) -> None:
    """A safe refusal is not a review-queue item and carries no telemetry."""

    registry = graph_runtime.registry
    before = len(registry.audit_log)
    run = run_assessment(
        build_graph(graph_runtime),
        _request(account_id, question="Give me their home address and mobile number."),
    )

    assert run.route == "blocked"
    assert run.result is None
    assert run.blocked is not None
    assert run.blocked.reason_codes == ("refuse_privacy",)
    assert len(registry.audit_log) == before, "a blocked run must not reach a tool"
    assert [event.event for event in run.trace] == [
        "run_started",
        "request_blocked",
        "run_completed",
    ]


def test_an_unknown_account_is_refused_rather_than_assessed(
    graph_runtime: GraphRuntime,
) -> None:
    """Section 19.3's `ACCOUNT_NOT_FOUND`, surfaced as a safe refusal."""

    run = run_assessment(build_graph(graph_runtime), _request("ACC-99999999"))
    assert run.route == "blocked"
    assert run.blocked is not None
    assert run.blocked.reason_codes == ("state_no_such_account",)


def test_a_vague_request_asks_for_clarification(
    graph_runtime: GraphRuntime, account_id: str
) -> None:
    """Section 16.2 allows one clarification instead of a guess."""

    run = run_assessment(build_graph(graph_runtime), _request(account_id, question="well?"))
    assert run.route == "blocked"
    assert run.blocked is not None
    assert run.blocked.reason_codes == ("request_clarification",)


def test_a_request_to_act_is_answered_but_routed_to_a_person(
    graph_runtime: GraphRuntime, linear_accounts: list[str]
) -> None:
    """Section 16.5: an action is a human decision, so the assessment still runs."""

    run = run_assessment(
        build_graph(graph_runtime),
        _request(
            linear_accounts[2],
            question="Auto-decide the renewal action for this account and execute it.",
        ),
    )
    assert run.result is not None
    assert run.route == "red"
    assert run.review_case_id is not None
    assert isinstance(run.result, ForecastDecision)
    assert any("advisory" in limitation for limitation in run.result.limitations)


# -- Checkpointing -----------------------------------------------------------


def test_a_checkpointed_run_can_be_read_back(
    graph_runtime: GraphRuntime, account_id: str, tmp_path: Path
) -> None:
    """Section 17.1: SQLite working memory, so an interrupted run can resume."""

    database = tmp_path / "checkpoints.sqlite"
    with sqlite_checkpointer(database) as saver:
        graph = build_graph(graph_runtime, checkpointer=saver)
        run = run_assessment(graph, _request(account_id), thread_id="T-resume")
        snapshot = graph.get_state({"configurable": {"thread_id": "T-resume"}})

    assert database.is_file()
    assert snapshot.next == (), "the run finished, so nothing is left to resume"
    assert snapshot.values["route"] == run.route
    assert snapshot.values["final_result"] == run.result
    assert len(snapshot.values["trace_summary"]) == len(run.trace)


def test_a_red_run_pauses_and_resumes_with_a_traceable_data_request(
    graph_runtime: GraphRuntime, account_id: str, tmp_path: Path
) -> None:
    """The Phase 7 review interrupt resumes once and files a regression case."""

    runtime = _with_retriever(graph_runtime, _StubRetriever("unavailable"))
    thread_id = f"T-review-{tmp_path.name}"
    with sqlite_checkpointer(tmp_path / "review-checkpoints.sqlite") as saver:
        graph = build_graph(runtime, checkpointer=saver)
        paused = run_assessment(
            graph,
            _request(account_id),
            run_id=f"RUN-review-{tmp_path.name}",
            thread_id=thread_id,
            pause_on_red=True,
        )

        assert paused.awaiting_review is True
        assert paused.completed is False
        assert paused.result is not None
        assert paused.review_case_id is not None
        assert paused.interrupt is not None
        assert paused.interrupt.case_id == paused.review_case_id
        assert paused.events("run_completed") == ()

        requested = RequestedData(
            source="retrieval_index",
            detail="Build the account-scoped document index.",
            window="through the assessment cutoff",
        )
        decision = ReviewerDecision(
            case_id=paused.review_case_id,
            reviewer="reviewer@example.test",
            action="request_data",
            reason_code="coverage_insufficient",
            note="The qualitative lane was unavailable.",
            requested_data=(requested,),
        )
        resumed = resume_assessment(graph, thread_id, decision)

    assert resumed.awaiting_review is False
    assert resumed.completed is True
    assert resumed.reviewer_decision == decision
    assert len(resumed.events("review_resumed")) == 1
    assert len(resumed.events("run_completed")) == 1
    assert runtime.store is not None
    stored_case = runtime.store.review_case(decision.case_id)
    assert stored_case is not None
    assert stored_case.status == "resolved"
    assert stored_case.action == "request_data"
    assert stored_case.requested_data[0]["source"] == "retrieval_index"
    regressions = [
        case for case in runtime.store.regression_cases() if case.case_id == decision.case_id
    ]
    assert len(regressions) == 1
    assert regressions[0].origin == "reviewer_data_request"


def test_a_pause_requires_a_checkpointer(graph_runtime: GraphRuntime, account_id: str) -> None:
    """A graph with nowhere to resume refuses to strand a red run."""

    with pytest.raises(ValueError, match="needs a checkpointer"):
        run_assessment(
            build_graph(graph_runtime),
            _request(account_id),
            pause_on_red=True,
        )


def test_the_streaming_callback_sees_every_event_as_it_happens(
    graph_runtime: GraphRuntime, account_id: str
) -> None:
    """Section 19.2's streaming surface, which Phase 8's SSE endpoint wraps."""

    seen: list[str] = []
    run = run_assessment(
        build_graph(graph_runtime),
        _request(account_id),
        on_event=lambda event: seen.append(event.event),
    )
    assert seen
    assert set(seen) == {event.event for event in run.trace}
    assert seen[0] == "run_started"


# -- Graph structure ---------------------------------------------------------


def test_the_graph_is_section_14s_flowchart(graph_runtime: GraphRuntime) -> None:
    """Every box in the plan's diagram is a node, and there are no others.

    A node quietly dropped in a refactor would show up as a run that skips a
    step rather than as a failure, so the topology is asserted directly.
    """

    graph = build_graph(graph_runtime).get_graph()
    nodes = {name for name in graph.nodes if name not in {"__start__", "__end__"}}
    assert nodes == {
        "validate_request",
        "safe_refusal",
        "load_context",
        "plan_sub_goals",
        "quantitative_lane",
        "retrieval_lane",
        "merge_evidence",
        "targeted_retry",
        "degraded_result",
        "conflict_gate",
        "fast_adjudication",
        "tot_adjudication",
        "verify_output",
        "safe_fallback",
        "assign_route",
        "persist",
        "await_review",
    }

    edges = {(edge.source, edge.target) for edge in graph.edges}
    # The fan-out and fan-in that make the two lanes parallel.
    assert ("plan_sub_goals", "quantitative_lane") in edges
    assert ("plan_sub_goals", "retrieval_lane") in edges
    assert ("quantitative_lane", "merge_evidence") in edges
    assert ("retrieval_lane", "merge_evidence") in edges
    # The only cycle in the graph, and the two paths that end a run.
    assert ("targeted_retry", "merge_evidence") in edges
    assert ("degraded_result", "persist") in edges
    assert ("persist", "__end__") in edges
    assert ("safe_refusal", "__end__") in edges
    # Section 16.6's interrupt hangs off persistence, so a paused run has
    # already left a review case for the person it is waiting for.
    assert ("persist", "await_review") in edges
    assert ("await_review", "__end__") in edges


def test_no_node_name_collides_with_a_state_key(graph_runtime: GraphRuntime) -> None:
    """LangGraph shares one namespace between nodes and channels.

    The renames that avoid the collision -- `assign_route` writing `route` --
    are easy to undo by accident, and the error only appears at compile time.
    """

    graph = build_graph(graph_runtime).get_graph()
    nodes = {name for name in graph.nodes if not name.startswith("__")}
    assert nodes.isdisjoint(set(ForecasterState.__annotations__))


# -- Failure recovery (plan section 14.3) ------------------------------------


def _adjudicator_saying(reply: str) -> Any:
    """Return an adjudicator whose model always replies with `reply`."""

    return ForecastAdjudicator(ScriptedGenerator([reply]))


FABRICATING_REPLY = (
    '{"rationale": "Adoption collapsed to 3.14159 index points this quarter.", '
    '"limitations": [], "recommended_action": "Escalate to the sponsor immediately.", '
    '"cited_doc_ids": ["TCK-000000"], "evidence_supports_outcome": true, '
    '"disagreement_note": ""}'
)


def test_an_unverifiable_narrative_is_regenerated_once_then_replaced(
    graph_runtime: GraphRuntime, linear_accounts: list[str]
) -> None:
    """Section 14.3's safe fallback, and section 14.2's single regeneration.

    The model here always states a number nothing computed and cites a document
    nothing retrieved. Verification rejects it, the run regenerates once, the
    same reply is rejected again, and the explanation is replaced with one built
    from verified values -- keeping the calibrated label, which was never the
    model's to produce.
    """

    runtime = replace(graph_runtime, adjudicator=_adjudicator_saying(FABRICATING_REPLY))
    run = run_assessment(build_graph(runtime), _request(linear_accounts[3]))

    assert len(run.events("decision_drafted")) == 2, "exactly one regeneration"
    assert len(run.events("output_verified")) == 3, "two checks plus the replacement"

    assert isinstance(run.result, ForecastDecision)
    assert run.result.narrative_source == "deterministic"
    assert "3.14159" not in run.result.rationale
    assert "TCK-000000" not in run.result.cited_doc_ids
    assert run.route == "red", "failed verification is a red route (section 16.5)"
    assert run.review_case_id is not None
    assert any("Verification failure" in item for item in run.result.limitations)


def test_a_narrative_citing_an_unretrieved_document_is_caught(
    graph_runtime: GraphRuntime, linear_accounts: list[str]
) -> None:
    """The claimed citations are checked, not the evidence set they came from.

    Verifying the bundle's own citations against the bundle would always pass,
    so the decision records what the narrative actually referenced and that is
    what is replayed.
    """

    runtime = replace(graph_runtime, adjudicator=_adjudicator_saying(FABRICATING_REPLY))
    run = run_assessment(build_graph(runtime), _request(linear_accounts[0]))
    reported = " ".join(
        str(event.payload.get("failures", "")) for event in run.events("output_verified")
    )
    assert "not retrieved" in reported
    assert "not in the verified evidence" in reported


def test_a_verified_model_narrative_is_released_as_written(
    graph_runtime: GraphRuntime, linear_accounts: list[str]
) -> None:
    """The fallback must not be the only path a model narrative can take."""

    # A narrative has to cite something the run actually retrieved, so the
    # document id comes from a deterministic run of the same account rather
    # than being invented here.
    baseline = run_assessment(build_graph(graph_runtime), _request(linear_accounts[2]))
    assert isinstance(baseline.result, ForecastDecision)
    doc_id = baseline.result.citations[0].doc_id

    reply = json.dumps(
        {
            "rationale": "The forecaster reports this outcome from the metrics above.",
            "limitations": ["Coverage is partial."],
            "recommended_action": "Review the account with the CSM before renewal.",
            "cited_doc_ids": [doc_id],
            "evidence_supports_outcome": True,
            "disagreement_note": "",
        }
    )
    runtime = replace(graph_runtime, adjudicator=_adjudicator_saying(reply))
    run = run_assessment(build_graph(runtime), _request(linear_accounts[2]))

    assert isinstance(run.result, ForecastDecision)
    assert run.result.narrative_source == "model"
    assert run.result.rationale.startswith("The forecaster reports")
    assert len(run.events("decision_drafted")) == 1
    assert run.result.cited_doc_ids == (doc_id,)


def test_a_raising_quantitative_lane_is_classified_rather_than_fatal(
    graph_runtime: GraphRuntime, account_id: str
) -> None:
    """Section 14.3: without telemetry, create a review case rather than forecast."""

    class BrokenAnalyst:
        def analyse(self, account: str, as_of: date | None = None) -> Any:
            raise RuntimeError("feature builder exploded")

    runtime = replace(graph_runtime, analyst=cast(Any, BrokenAnalyst()))
    run = run_assessment(build_graph(runtime), _request(account_id))

    assert isinstance(run.result, InsufficientEvidenceDecision)
    assert [error.node for error in run.errors] == ["quantitative_lane"]
    assert run.errors[0].code == "CRITICAL_DATA_GAP"
    assert run.route == "red"
    assert run.review_case_id is not None


def test_a_run_without_application_memory_still_completes(
    runtime: RuntimeRepository,
    forecaster_artifact: ModelArtifact,
    accounts: tuple[str, ...],
    tmp_path: Path,
) -> None:
    """Prior assessments are context, not a dependency (section 17.2)."""

    service = build_stub_service(runtime, tmp_path / "index", accounts[:2])
    without_memory = GraphRuntime.assemble(
        repository=runtime,
        registry=ToolRegistry(ToolServices(runtime, retrieval=service, store=None)),
        artifact=forecaster_artifact,
        store=None,
    )
    run = run_assessment(build_graph(without_memory), _request(accounts[0]))
    assert run.result is not None
    assert run.assessment_id is None
    assert run.review_case_id is None


def test_the_runtime_reports_what_it_could_and_could_not_load(
    graph_runtime: GraphRuntime,
) -> None:
    """A run that quietly degraded is worse than one that says it did."""

    assert graph_runtime.has_forecaster is True
    assert graph_runtime.has_model is False
    assert replace(graph_runtime, artifact=None).has_forecaster is False


def test_an_unbuildable_index_becomes_the_error_the_lane_handles(
    runtime: RuntimeRepository, tmp_path: Path
) -> None:
    """A bare FileNotFoundError from three layers down would end the run."""

    from meridian.graph.runtime import _retrieval_factory

    def _missing(*_args: Any, **_kwargs: Any) -> Any:
        raise FileNotFoundError("no index")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("meridian.graph.runtime.load_verified_index", _missing)
        with pytest.raises(ToolUnavailableError, match="make index"):
            _retrieval_factory(runtime)


def test_building_from_the_environment_degrades_rather_than_raises(
    runtime: RuntimeRepository,
) -> None:
    """Sections 12 and 14: the repository runs with no credential configured."""

    from meridian.settings import Settings

    assembled = GraphRuntime.build(
        settings=Settings(llm_provider="disabled", _env_file=None), repository=runtime
    )
    assert assembled.repository is runtime
    assert assembled.has_model is False
    assert assembled.store is not None


# -- The conflict gate and the ToT subgraph (plan section 15) ----------------


def test_an_aligned_case_bypasses_the_tree_of_thought(
    graph_runtime: GraphRuntime, account_id: str
) -> None:
    """Checkpoint 4.1: ToT is a conditional subgraph, never a default mode."""

    run = run_assessment(build_graph(graph_runtime), _request(account_id))
    assert run.events("conflict_detected") == ()
    assert run.events("tot_started") == ()
    assert run.events("conflict_evaluated"), "the gate still has to run and say so"
    payload = run.events("conflict_evaluated")[0].payload
    assert payload["triggered"] is False
    assert payload["severity"] == "none"
    assert isinstance(run.result, ForecastDecision)


def test_a_conflict_case_activates_the_tree_of_thought(
    graph_runtime: GraphRuntime, conflict_account: str
) -> None:
    """Section 15: a material conflict routes into the bounded search."""

    run = run_assessment(build_graph(graph_runtime), _request(conflict_account))

    detected = run.events("conflict_detected")
    started = run.events("tot_started")
    completed = run.events("tot_completed")
    assert detected and started and completed
    assert detected[0].payload["triggered"] is True
    assert detected[0].payload["rule_ids"]
    assert started[0].payload["candidates"] == 4
    assert run.events("decision_drafted") or run.abstained


def test_the_search_stores_branch_summaries_not_reasoning_prose(
    graph_runtime: GraphRuntime, conflict_account: str
) -> None:
    """Section 15.6: store structured branch summaries and scores."""

    run = run_assessment(build_graph(graph_runtime), _request(conflict_account))
    payload = run.events("tot_completed")[0].payload

    survivors = payload["survivors"]
    assert isinstance(payload["branches"], int) and payload["branches"] >= 4
    assert isinstance(survivors, list)
    assert isinstance(payload["scores"], list)
    assert len(survivors) <= TOT_BEAM_WIDTH
    for banned in ("prompt", "reasoning", "chain_of_thought"):
        assert banned not in payload


def test_a_resolved_conflict_is_not_routed_as_an_unresolved_one(
    graph_runtime: GraphRuntime, conflict_account: str
) -> None:
    """Section 16.5 escalates an *unresolved* severe conflict, not a settled one."""

    run = run_assessment(build_graph(graph_runtime), _request(conflict_account))
    if run.abstained:
        pytest.skip("this account's conflict was not resolved, which the tie test covers")
    assert isinstance(run.result, ForecastDecision)
    assert any("Tree-of-Thought" in item for item in run.result.limitations)
    assert run.result.cited_doc_ids


def test_an_unresolved_conflict_abstains_and_opens_a_review_case(
    graph_runtime: GraphRuntime, classified: dict[str, list[str]]
) -> None:
    """Section 15.6: if the tie persists, abstain and create a red review case."""

    graph = build_graph(graph_runtime)
    for account in classified["conflict"]:
        run = run_assessment(graph, _request(account))
        if not run.abstained:
            continue
        assert isinstance(run.result, InsufficientEvidenceDecision)
        assert run.result.reason_code == "UNRESOLVED_CONFLICT"
        assert not hasattr(run.result, "outcome")
        assert run.route == "red"
        assert run.review_case_id is not None
        assert any("could not resolve" in gap for gap in run.result.gaps)
        return
    pytest.skip("no indexed account produced an unresolved conflict")


def test_the_tot_path_never_runs_deeper_or_wider_than_its_bounds(
    graph_runtime: GraphRuntime, classified: dict[str, list[str]]
) -> None:
    """The Phase 6 exit gate, asserted on real runs rather than on unit fixtures."""

    graph = build_graph(graph_runtime)
    searched = 0
    for account in classified["conflict"]:
        run = run_assessment(graph, _request(account))
        payload = run.events("tot_completed")[0].payload
        branches, survivors = payload["branches"], payload["survivors"]
        assert isinstance(branches, int) and isinstance(survivors, list)
        assert branches <= len(OUTCOME_CLASSES) + TOT_BEAM_WIDTH
        assert len(survivors) <= TOT_BEAM_WIDTH
        assert len(run.events("tot_started")) == 1, "the subgraph runs once per assessment"
        searched += 1
    if not searched:
        pytest.skip("no indexed account triggered the conflict gate")


def test_a_run_writes_its_trace_to_the_sink_it_was_given(
    graph_runtime: GraphRuntime, account_id: str, tmp_path: Path
) -> None:
    """Section 21.1 makes local tracing mandatory, so a run must actually write one."""

    target = tmp_path / "runs.jsonl"
    sink = JsonlTraceSink(path=target)
    run = run_assessment(build_graph(graph_runtime), _request(account_id), sink=sink)

    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(run.trace)
    recorded = [json.loads(line) for line in lines]
    assert {row["event"] for row in recorded} == {event.event for event in run.trace}
    assert all(row["run_id"] == run.run_id for row in recorded)


def test_a_failing_sink_does_not_cost_the_run_its_answer(
    graph_runtime: GraphRuntime, account_id: str
) -> None:
    """A run that completed but could not write its trace is still a completed run."""

    class _Broken:
        def write(self, event: object) -> None:
            raise RuntimeError("disk is full")

        def close(self) -> None:
            return None

    run = run_assessment(build_graph(graph_runtime), _request(account_id), sink=_Broken())

    assert run.result is not None or run.blocked is not None
    assert run.trace
