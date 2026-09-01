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
from meridian.graph.confidence import TIE_MARGIN, top_two_margin
from meridian.graph.state import (
    MAX_EVIDENCE_ROUNDS,
    MAX_OUTPUT_REGENERATIONS,
    ForecasterState,
)

GREEN_MINIMUM_CONFIDENCE = 0.85
AMBER_MINIMUM_CONFIDENCE = 0.70


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
    # the run the same way a block does but with a different message. Phase 8's
    # API turns it into a prompt for the user rather than an error.
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
) -> tuple[Route, str]:
    """Return the human-review band for a released forecast (section 16.5)."""

    adverse = outcome in ADVERSE_OUTCOMES
    margin = top_two_margin(distribution)

    red_reasons: list[str] = []
    if confidence < AMBER_MINIMUM_CONFIDENCE:
        red_reasons.append(f"confidence {confidence:.2f} is below {AMBER_MINIMUM_CONFIDENCE:.2f}")
    if margin < TIE_MARGIN:
        red_reasons.append(f"the top two outcomes are within {margin:.2f}")
    if coverage.has_critical_gap:
        red_reasons.append("critical coverage is missing")
    if conflict is not None and conflict.unresolved_severe:
        red_reasons.append("an unresolved severe conflict")
    if verification is not None and not verification.passed:
        red_reasons.append("output verification failed")
    if high_value and adverse:
        red_reasons.append("an adverse call on a high-value account")
    if intake is not None and "escalate_to_human" in intake.reason_codes:
        red_reasons.append("the request asked for an action a person must decide")
    if red_reasons:
        return "red", "; ".join(red_reasons)

    amber_reasons: list[str] = []
    if confidence < GREEN_MINIMUM_CONFIDENCE:
        amber_reasons.append(f"confidence {confidence:.2f} is below {GREEN_MINIMUM_CONFIDENCE:.2f}")
    if retrieval_gap:
        amber_reasons.append("a noncritical retrieval gap was left unfilled")
    if verification is not None and verification.attempts > 1:
        amber_reasons.append("the output needed one regeneration")
    if coverage.stale_sources:
        amber_reasons.append(f"stale sources: {', '.join(coverage.stale_sources)}")
    if amber_reasons:
        return "amber", "; ".join(amber_reasons)

    return "green", "confidence, coverage, and verification all met the release bar"


def abstention_route(
    coverage: CoverageReport, high_value: bool, unresolved_conflict: str | None = None
) -> tuple[Route, str]:
    """Return the band for a degraded or abstained, no-label result.

    The instructor feedback recorded in section 2 asks for "impact-aware
    escalation": the same missing evidence matters more on an account the
    business cannot afford to be wrong about, so a high-value account escalates
    even when the gap itself is ordinary.

    Section 15.6 adds one more red condition. A Tree-of-Thought search whose top
    two branches stay tied after the consistency vote has not failed to find
    evidence -- it has found evidence that genuinely points both ways, which is
    precisely the case a person should look at.
    """

    reasons: list[str] = []
    if unresolved_conflict:
        reasons.append(f"the conflict was not resolved: {unresolved_conflict}")
    if coverage.has_critical_gap:
        reasons.append(f"critical coverage is missing: {'; '.join(coverage.critical_gaps)}")
    if high_value:
        reasons.append("this is a high-value account")
    if reasons:
        return "red", "; ".join(reasons)
    return "amber", "evidence was insufficient for a categorical forecast"


__all__ = [
    "AMBER_MINIMUM_CONFIDENCE",
    "GREEN_MINIMUM_CONFIDENCE",
    "abstention_route",
    "coverage_verdict",
    "human_route",
    "route_conflict",
    "route_coverage",
    "route_intake",
    "route_tot",
    "route_verification",
]
