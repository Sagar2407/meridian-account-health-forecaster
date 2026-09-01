"""The shared LangGraph state and its reducers (plan section 9.2).

Section 9.2 requires that "all list and merge fields must have explicit
reducers", so every collection here is annotated even where LangGraph's default
would have done the same thing. The default is last-write-wins, which is correct
for the plan and wrong for the trace, and a reader should not have to know which
is which.

The parallel lanes obey a second rule from the same section: "Parallel nodes may
only write their own state keys until the fan-in node constructs the evidence
bundle." The quantitative node writes `quantitative`; the retrieval node writes
`retrieval`; both append to `errors` and `trace_summary`, which is safe because
those two accumulate rather than overwrite. `test_graph_state.py` asserts the
rule rather than trusting it.
"""

import operator
from typing import Annotated, Literal, TypedDict, TypeVar

from meridian.contracts import (
    AssessmentRequest,
    BlockedDecision,
    CandidateHypothesis,
    ConflictAssessment,
    EvidenceBundle,
    FinalResult,
    ForecastDecision,
    GuardrailDecision,
    NodeError,
    OutputVerification,
    QuantitativeEvidence,
    RetrievalEvidence,
    ReviewerDecision,
    Route,
    SubGoal,
    TraceEvent,
)
from meridian.data.repository import AccountProfile
from meridian.tools.contracts import PriorAssessment

#: Bounded execution budgets (plan section 14.2). They are constants rather than
#: settings because the exit gate is "no unbounded cycle": a budget an operator
#: can raise at runtime is not a bound.
MAX_EVIDENCE_ROUNDS = 2
MAX_RETRIEVAL_REWRITES = 1
MAX_OUTPUT_REGENERATIONS = 1

#: LangGraph's own safety net. Every path through this graph is far shorter, so
#: hitting it means a cycle escaped the budgets above.
GRAPH_RECURSION_LIMIT = 40

#: Where a red run stands with its reviewer (plan section 16.6). `not_required`
#: is every green and amber run; `awaiting_review` is a run paused on a
#: LangGraph interrupt; `reviewed` is one a typed reviewer decision resumed.
ReviewState = Literal["not_required", "awaiting_review", "reviewed"]

ItemT = TypeVar("ItemT")


def keep_last(current: list[ItemT], incoming: list[ItemT]) -> list[ItemT]:
    """Replace the value instead of merging it.

    Used for fields a single node owns end to end -- the plan, for instance. It
    is spelled out rather than left implicit so that "this list is replaced" and
    "this list accumulates" look different in the type, which is the point of
    section 9.2's requirement.
    """

    return incoming


class ForecasterState(TypedDict, total=False):
    """Working memory for one assessment run (plan sections 9.2 and 17.1).

    `total=False` because the graph fills the state progressively: a node that
    has not run yet has not written its key, and a reader that assumes otherwise
    would silently read a stale value from a resumed checkpoint.
    """

    run_id: str
    thread_id: str
    request: AssessmentRequest
    intake: GuardrailDecision | None
    account: AccountProfile | None
    # Not in the plan's section 9.2 field list. The planner needs the
    # Orchestrator's own prior decisions as context (section 17.2), and the
    # alternative is for the plan node to re-read them from application
    # memory a moment after the context node already did.
    prior_assessments: Annotated[list[PriorAssessment], keep_last]
    plan: Annotated[list[SubGoal], keep_last]
    quantitative: QuantitativeEvidence | None
    retrieval: RetrievalEvidence | None
    evidence_bundle: EvidenceBundle | None
    evidence_round: int
    retrieval_retries: int
    conflict: ConflictAssessment | None
    candidates: Annotated[list[CandidateHypothesis], keep_last]
    draft_decision: ForecastDecision | None
    output_verification: OutputVerification | None
    final_result: FinalResult | None
    blocked: BlockedDecision | None
    route: Route | None
    review_case_id: str | None
    assessment_id: str | None
    errors: Annotated[list[NodeError], operator.add]
    trace_summary: Annotated[list[TraceEvent], operator.add]
    # -- Phase 7 additions (plan sections 16.3 and 16.6) ---------------------
    #: Every stage's guardrail verdict, in the order the stages ran. This is
    #: what the per-run safety report is assembled from, so it accumulates
    #: rather than replaces: a run that passed intake and then quarantined a
    #: citation has two verdicts to show, not one.
    guardrails: Annotated[list[GuardrailDecision], operator.add]
    #: The runtime budget of section 16.3, tracked as plain counters so it
    #: survives a checkpoint. `started_at` is epoch seconds; a paused run's
    #: wall clock therefore includes the reviewer's own time, which is harmless
    #: because every model call happens before the pause.
    model_calls: Annotated[int, operator.add]
    spent_tokens: Annotated[int, operator.add]
    started_at: float
    #: Whether a red result should pause on a LangGraph interrupt rather than
    #: complete and leave an open case. A portfolio scan must never block on a
    #: person, so this is off unless a caller asks for it.
    pause_on_red: bool
    review_state: ReviewState | None
    reviewer_decision: ReviewerDecision | None


#: State keys each parallel lane is permitted to write, plus the two accumulating
#: keys every node may append to. Section 9.2 makes this a rule; the graph tests
#: make it an assertion.
PARALLEL_LANE_KEYS: dict[str, frozenset[str]] = {
    "quantitative": frozenset({"quantitative"}),
    "retrieval": frozenset({"retrieval"}),
}
ACCUMULATING_KEYS: frozenset[str] = frozenset(
    {"errors", "trace_summary", "guardrails", "model_calls", "spent_tokens"}
)


__all__ = [
    "ACCUMULATING_KEYS",
    "GRAPH_RECURSION_LIMIT",
    "MAX_EVIDENCE_ROUNDS",
    "MAX_OUTPUT_REGENERATIONS",
    "MAX_RETRIEVAL_REWRITES",
    "PARALLEL_LANE_KEYS",
    "ForecasterState",
    "ReviewState",
    "keep_last",
]
