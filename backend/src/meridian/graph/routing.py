"""Deterministic edges and human-review bands (plan sections 14.1 and 16.5).

Section 14.1 lists five transitions that must be deterministic and adds the rule
that makes them worth listing: "The LLM may suggest sub-goals or produce
structured rationale, but it must not choose structural transitions by free-form
instruction." Every function here is a pure function of typed state. None of
them can be reached by a model, and none of them reads free text.

The budgets that stop the graph cycling live in `meridian.graph.state` and are
checked here, so "no unbounded cycle" is a property of the routing rather than a
property of how carefully the nodes were written.
"""

from dataclasses import dataclass

from meridian.contracts import (
    ADVERSE_OUTCOMES,
    ConflictAssessment,
    CoverageReport,
    GuardrailDecision,
    OutputVerification,
    QuantitativeEvidence,
    RetrievalEvidence,
    Route,
)
from meridian.graph.confidence import top_two_margin
from meridian.graph.state import (
    MAX_EVIDENCE_ROUNDS,
    MAX_OUTPUT_REGENERATIONS,
    ForecasterState,
)
from meridian.graph.thresholds import THRESHOLDS, DecisionThresholds

# Frozen in `meridian.graph.thresholds`, not here (plan section 22.7).
GREEN_MINIMUM_CONFIDENCE = THRESHOLDS.green_minimum_confidence
AMBER_MINIMUM_CONFIDENCE = THRESHOLDS.amber_minimum_confidence


def coverage_verdict(
    quantitative: QuantitativeEvidence | None,
    retrieval: RetrievalEvidence | None,
    evidence_round: int,
) -> tuple[str, str]:
    """Classify evidence coverage as sufficient, recoverable, or critical.

    Args:
        quantitative: The deterministic lane's result, if it ran.
        retrieval: The retrieval lane's result, if it ran.
        evidence_round: How many evidence rounds have completed.

    Returns:
        The verdict and a one-line reason for the trace.
    """

    if quantitative is None or not quantitative.available:
        reason = (
            "; ".join(quantitative.coverage.critical_gaps)
            if quantitative is not None
            else "the quantitative lane did not run"
        )
        return "critical", reason or "telemetry could not be computed"

    if retrieval is None or not retrieval.available:
        detail = retrieval.unavailable_reason if retrieval is not None else "the lane did not run"
        return "critical", f"retrieval is unavailable: {detail}"

    if retrieval.exhausted:
        # Qualitative silence is not a signal. Section 4 item 10 requires a
        # degraded, verified-telemetry answer rather than a forecast made on the
        # numbers alone and presented as though evidence had been checked.
        if evidence_round < MAX_EVIDENCE_ROUNDS:
            return "recoverable", "no account evidence was retrieved on the first round"
        return "critical", "retrieval was exhausted without producing any account evidence"

    uncovered = retrieval.uncovered_sub_goals
    if uncovered and evidence_round < MAX_EVIDENCE_ROUNDS:
        return "recoverable", f"sub-goals without evidence: {', '.join(uncovered)}"
    if uncovered:
        return "sufficient", f"proceeding with a noncritical gap: {', '.join(uncovered)}"
    return "sufficient", "every planned sub-goal produced evidence"


def route_intake(state: ForecasterState) -> str:
    """Route on the intake verdict (section 14.1: allow, block, clarify)."""

    decision = state.get("intake")
    if decision is None or decision.outcome == "block":
        return "safe_refusal"
    # A clarification is a refusal to guess, not a refusal to answer, so it ends
    # the run the same way a block does but with a different message. The API
    # turns it into a prompt for the user rather than an error.
    if decision.outcome == "clarify":
        return "safe_refusal"
    return "load_context"


def route_coverage(state: ForecasterState) -> str:
    """Route on evidence coverage (section 14.1: sufficient, recoverable, critical)."""

    verdict, _ = coverage_verdict(
        state.get("quantitative"),
        state.get("retrieval"),
        state.get("evidence_round", 0),
    )
    if verdict == "recoverable":
        return "targeted_retry"
    if verdict == "critical":
        return "degraded_result"
    return "conflict_gate"


def route_conflict(state: ForecasterState) -> str:
    """Route on the conflict gate (section 14.1: conflict yes or no)."""

    conflict = state.get("conflict")
    if conflict is not None and conflict.triggered:
        return "tot_adjudication"
    return "fast_adjudication"


def route_tot(state: ForecasterState) -> str:
    """Route out of the Tree-of-Thought subgraph (section 15.6).

    A search that selected a winner produces a draft, which is verified like any
    other. One that abstained has already written its own final result and goes
    straight to persistence: there is no narrative left to verify, and running
    the verifier over an abstention would check claims nobody made.
    """

    return "verify_output" if state.get("draft_decision") is not None else "persist"


def route_verification(state: ForecasterState) -> str:
    """Route on output verification (section 14.1: pass, regenerate, fallback)."""

    verification = state.get("output_verification")
    if verification is None:
        return "safe_fallback"
    if verification.passed:
        return "assign_route"

    draft = state.get("draft_decision")
    if draft is not None and draft.selected_by == "tree_of_thought":
        # There is no linear regeneration that preserves the search's choice:
        # `fast_adjudication` would rebuild the decision around the model's
        # argmax and hand back a different outcome under the same run id. The
        # safe fallback keeps the selected outcome and rewrites only the prose.
        return "safe_fallback"
    if verification.attempts <= MAX_OUTPUT_REGENERATIONS:
        return "fast_adjudication"
    return "safe_fallback"


def route_human_review(state: ForecasterState) -> str:
    """Decide whether a red run pauses for a person (section 16.6).

    Section 16.5 allows a red case to "pause or complete with abstention and
    require immediate human review", and section 16.6 asks for a LangGraph
    interrupt "for cases that must pause". Which of the two applies is a
    property of the caller, not of the account: an interactive user can wait for
    a reviewer, and a portfolio scan must never block on one. So the caller sets
    `pause_on_red`, and everything else -- what counts as red, what the reviewer
    is shown, what is persisted -- is identical on both paths.
    """

    if not state.get("pause_on_red", False):
        return "end"
    if state.get("route") != "red":
        return "end"
    # There is nothing to pause for without a case to resolve: application
    # memory is optional, and a run that could not open one would strand the
    # graph waiting for a decision no reviewer could ever be shown.
    if not state.get("review_case_id"):
        return "end"
    return "await_review"


@dataclass(frozen=True)
class RouteVerdict:
    """A review band, why it was assigned, and which rules fired.

    `codes` exists so the decision is auditable and replayable. A decision card
    can show which rule sent an answer to a person rather than only the prose,
    and the threshold study can re-derive a band under a different set of
    thresholds without re-running the graph -- which is what makes a
    development-split sweep affordable at all.
    """

    route: Route
    reason: str
    codes: tuple[str, ...] = ()


def human_route(
    confidence: float,
    coverage: CoverageReport,
    verification: OutputVerification | None,
    conflict: ConflictAssessment | None,
    distribution: dict[str, float],
    outcome: str,
    high_value: bool,
    retrieval_gap: bool,
    intake: GuardrailDecision | None = None,
    evidence_screen: GuardrailDecision | None = None,
    budget: GuardrailDecision | None = None,
    thresholds: DecisionThresholds = THRESHOLDS,
) -> RouteVerdict:
    """Return the human-review band for a released forecast (section 16.5).

    Args:
        confidence: The deterministic evidence-aware confidence.
        coverage: What the run was able to observe.
        verification: The output verification, when one ran.
        conflict: The conflict gate's verdict, when one ran.
        distribution: The calibrated four-class distribution.
        outcome: The label being released.
        high_value: Whether an adverse call here needs extra care (section 16.5).
        retrieval_gap: Whether a noncritical retrieval gap was left unfilled.
        intake: The intake guardrail's verdict.
        evidence_screen: The evidence guardrail's verdict. Anything other than a
            pass means a citation reached the bundle that could not be shown to
            belong to this account at this cutoff, which is an upstream control
            failing rather than an ordinary gap -- so it is red, not amber.
        budget: The runtime budget's verdict. A run that finished on the
            deterministic narrative because its model budget ran out is
            provisional, not unsafe.
        thresholds: The frozen decision thresholds. A caller other than the
            graph passes a candidate set only to *measure* what it would do
            (plan section 22.7); the graph itself always uses the frozen set.

    Returns:
        The band, a human-readable reason, and the rule codes that fired.
    """

    adverse = outcome in ADVERSE_OUTCOMES
    margin = top_two_margin(distribution)

    red: list[tuple[str, str]] = []
    if confidence < thresholds.amber_minimum_confidence:
        red.append(
            (
                "confidence_below_amber",
                f"confidence {confidence:.2f} is below {thresholds.amber_minimum_confidence:.2f}",
            )
        )
    if margin < thresholds.tie_margin:
        red.append(("outcomes_tied", f"the top two outcomes are within {margin:.2f}"))
    if coverage.has_critical_gap:
        red.append(("critical_coverage_missing", "critical coverage is missing"))
    if conflict is not None and conflict.unresolved_severe:
        red.append(("unresolved_severe_conflict", "an unresolved severe conflict"))
    if verification is not None and not verification.passed:
        red.append(("verification_failed", "output verification failed"))
    if high_value and adverse:
        red.append(("high_value_adverse", "an adverse call on a high-value account"))
    if intake is not None and "escalate_to_human" in intake.reason_codes:
        red.append(
            (
                "intake_escalation",
                "the request asked for an action a person must decide",
            )
        )
    if evidence_screen is not None and evidence_screen.outcome != "pass":
        red.append(
            (
                "evidence_quarantined",
                "evidence was quarantined before it reached the decision",
            )
        )
    if red:
        return RouteVerdict(
            "red",
            "; ".join(message for _, message in red),
            tuple(code for code, _ in red),
        )

    amber: list[tuple[str, str]] = []
    if confidence < thresholds.green_minimum_confidence:
        amber.append(
            (
                "confidence_below_green",
                f"confidence {confidence:.2f} is below {thresholds.green_minimum_confidence:.2f}",
            )
        )
    if retrieval_gap:
        amber.append(("retrieval_gap", "a noncritical retrieval gap was left unfilled"))
    if verification is not None and verification.attempts > 1:
        amber.append(("output_regenerated", "the output needed one regeneration"))
    if coverage.stale_sources:
        amber.append(("stale_sources", f"stale sources: {', '.join(coverage.stale_sources)}"))
    if budget is not None and budget.outcome != "pass":
        amber.append(
            (
                "budget_exhausted",
                "the run reached its model budget and finished deterministically",
            )
        )
    if amber:
        return RouteVerdict(
            "amber",
            "; ".join(message for _, message in amber),
            tuple(code for code, _ in amber),
        )

    return RouteVerdict("green", "confidence, coverage, and verification all met the release bar")


def abstention_route(
    coverage: CoverageReport, high_value: bool, unresolved_conflict: str | None = None
) -> RouteVerdict:
    """Return the band for a degraded or abstained, no-label result.

    The instructor feedback recorded in section 2 asks for "impact-aware
    escalation": the same missing evidence matters more on an account the
    business cannot afford to be wrong about, so a high-value account escalates
    even when the gap itself is ordinary.

    Section 15.6 adds one more red condition. A Tree-of-Thought search whose top
    two branches stay tied after the consistency vote has not failed to find
    evidence -- it has found evidence that genuinely points both ways, which is
    precisely the case a person should look at.

    Returns the same `RouteVerdict` as `human_route`, codes included. An
    abstention used to return a bare band and a sentence, which meant the runs
    that abstained were the only runs carrying no rule codes -- and section
    22.6's "exhausted-retrieval safe fallback" measures exactly those runs, so
    the metric silently counted nothing at all.
    """

    reasons: list[tuple[str, str]] = []
    if unresolved_conflict:
        reasons.append(
            ("unresolved_conflict", f"the conflict was not resolved: {unresolved_conflict}")
        )
    if coverage.has_critical_gap:
        reasons.append(
            (
                "critical_coverage_missing",
                f"critical coverage is missing: {'; '.join(coverage.critical_gaps)}",
            )
        )
    if high_value:
        reasons.append(("high_value_account", "this is a high-value account"))
    if reasons:
        return RouteVerdict(
            "red",
            "; ".join(message for _, message in reasons),
            tuple(code for code, _ in reasons),
        )
    return RouteVerdict(
        "amber",
        "evidence was insufficient for a categorical forecast",
        ("insufficient_evidence",),
    )


__all__ = [
    "AMBER_MINIMUM_CONFIDENCE",
    "GREEN_MINIMUM_CONFIDENCE",
    "RouteVerdict",
    "abstention_route",
    "coverage_verdict",
    "human_route",
    "route_conflict",
    "route_coverage",
    "route_human_review",
    "route_intake",
    "route_tot",
    "route_verification",
]
