"""Deterministic edges, confidence, and review bands (plan sections 14.1, 16.1, 16.5).

Every transition in this graph is a pure function of typed state, which is what
section 14.1 demands: "the LLM ... must not choose structural transitions by
free-form instruction". These tests exercise those functions directly, without a
graph, because that is the level at which the rule either holds or does not.

The budgets are tested from the same angle. "No unbounded cycle" is Phase 5's
exit gate, and the reason it holds is that `coverage_verdict` stops offering the
recoverable branch once the evidence budget is spent -- so that is what is
asserted, rather than counting laps around a running graph.
"""

from datetime import date

import pytest

from meridian.contracts import (
    Citation,
    ConfidenceBreakdown,
    ConflictAssessment,
    CoverageReport,
    EvidenceBundle,
    ForecastDecision,
    GuardrailDecision,
    OutputVerification,
    QuantitativeEvidence,
    RetrievalEvidence,
    RetrievalObservation,
)
from meridian.graph.confidence import (
    AGREEMENT_WEIGHT,
    CALIBRATED_WEIGHT,
    CAP_CRITICAL_SOURCE_MISSING,
    CAP_EXHAUSTED_RETRIEVAL_GAP,
    CAP_REPAIRED_VERIFICATION,
    COVERAGE_WEIGHT,
    agreement_score,
    apply_verification_cap,
    compute_confidence,
    coverage_score,
    top_two_margin,
)
from meridian.graph.routing import (
    abstention_route,
    coverage_verdict,
    human_route,
    route_conflict,
    route_coverage,
    route_intake,
    route_verification,
)
from meridian.graph.state import MAX_EVIDENCE_ROUNDS, ForecasterState

CUTOFF = date(2026, 3, 1)
CLEAR = {"Churned": 0.70, "Contracted": 0.10, "Renewed": 0.15, "Expanded": 0.05}
TIED = {"Churned": 0.40, "Contracted": 0.38, "Renewed": 0.12, "Expanded": 0.10}


def _coverage(**overrides: object) -> CoverageReport:
    defaults: dict[str, object] = {"expected_weeks": 13, "observed_weeks": 13}
    return CoverageReport(**{**defaults, **overrides})


def _citation(doc_id: str, signal: str = "adverse") -> Citation:
    return Citation(
        doc_id=doc_id,
        parent_id=doc_id,
        source_type="support_ticket",
        subtype="Escalation",
        account_id="ACC-1042",
        doc_date=date(2026, 1, 1),
        excerpt="text",
        retrieval_score=0.8,
        signal=signal,
    )


def _quantitative(available: bool = True, **overrides: object) -> QuantitativeEvidence:
    defaults: dict[str, object] = {
        "account_id": "ACC-1042",
        "cutoff": CUTOFF,
        "coverage": _coverage(),
    }
    if available:
        defaults |= {
            "distribution": dict(CLEAR),
            "predicted_outcome": "Churned",
            "model_probability": 0.70,
        }
    return QuantitativeEvidence(**{**defaults, **overrides, "available": available})


def _retrieval(
    covered: tuple[str, ...] = ("adoption",), uncovered: tuple[str, ...] = ()
) -> RetrievalEvidence:
    observations = [
        RetrievalObservation(sub_goal=kind, query=kind, citations=(_citation(f"D-{kind}"),))
        for kind in covered
    ] + [
        RetrievalObservation(sub_goal=kind, query=kind, insufficient_evidence=True)
        for kind in uncovered
    ]
    return RetrievalEvidence(account_id="ACC-1042", cutoff=CUTOFF, observations=tuple(observations))


def _bundle(**overrides: object) -> EvidenceBundle:
    defaults: dict[str, object] = {
        "account_id": "ACC-1042",
        "cutoff": CUTOFF,
        "quantitative": _quantitative(),
        "retrieval": _retrieval(),
        "coverage": _coverage(),
        "supporting": (_citation("A"),),
        "counterevidence": (),
    }
    return EvidenceBundle(**{**defaults, **overrides})


def _decision(**overrides: object) -> ForecastDecision:
    """Return a minimal released decision."""

    defaults: dict[str, object] = {
        "account_id": "ACC-1042",
        "cutoff": CUTOFF,
        "outcome": "Churned",
        "distribution": dict(CLEAR),
        "confidence": 0.8,
        "confidence_breakdown": ConfidenceBreakdown(
            calibrated_probability=0.7,
            coverage_score=0.8,
            agreement_score=1.0,
            raw_confidence=0.8,
            confidence=0.8,
        ),
        "rationale": "text",
        "recommended_action": "review",
    }
    return ForecastDecision(**{**defaults, **overrides})


def _state(**values: object) -> ForecasterState:
    return dict(values)  # type: ignore[return-value]


# -- Coverage gate -----------------------------------------------------------


def test_complete_evidence_is_sufficient() -> None:
    """Both lanes answered and every sub-goal produced evidence."""

    verdict, reason = coverage_verdict(_quantitative(), _retrieval(), evidence_round=1)
    assert verdict == "sufficient"
    assert "every planned sub-goal" in reason


def test_a_failed_quantitative_lane_is_always_critical() -> None:
    """Section 14.3: without telemetry there is no forecast, only a review case."""

    lane = _quantitative(available=False, coverage=_coverage(critical_gaps=("no telemetry",)))
    verdict, reason = coverage_verdict(lane, _retrieval(), evidence_round=1)
    assert verdict == "critical"
    assert "no telemetry" in reason


def test_unavailable_retrieval_is_critical_not_recoverable() -> None:
    """An unbuilt index is not a gap another search round could close."""

    lane = RetrievalEvidence(
        account_id="ACC-1042", cutoff=CUTOFF, available=False, unavailable_reason="no index"
    )
    verdict, reason = coverage_verdict(_quantitative(), lane, evidence_round=1)
    assert verdict == "critical"
    assert "no index" in reason


def test_a_missing_sub_goal_is_recoverable_once_and_then_is_not() -> None:
    """The one extra evidence round of section 13.1, and its end.

    This is where "no unbounded cycle" is decided: once the budget is spent the
    recoverable verdict is no longer available, so the router cannot send the
    run back to the retry node however many times it is asked.
    """

    partial = _retrieval(covered=("adoption",), uncovered=("support",))
    assert coverage_verdict(_quantitative(), partial, evidence_round=1)[0] == "recoverable"
    assert coverage_verdict(_quantitative(), partial, MAX_EVIDENCE_ROUNDS)[0] == "sufficient"


def test_exhausted_retrieval_becomes_critical_once_the_budget_is_spent() -> None:
    """Section 4 item 10: qualitative silence must degrade, never forecast."""

    empty = RetrievalEvidence(account_id="ACC-1042", cutoff=CUTOFF)
    assert coverage_verdict(_quantitative(), empty, evidence_round=1)[0] == "recoverable"
    verdict, reason = coverage_verdict(_quantitative(), empty, MAX_EVIDENCE_ROUNDS)
    assert verdict == "critical"
    assert "exhausted" in reason


# -- Edge functions ----------------------------------------------------------


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [("pass", "load_context"), ("block", "safe_refusal"), ("clarify", "safe_refusal")],
)
def test_the_intake_edge_maps_every_verdict(outcome: str, expected: str) -> None:
    """Section 14.1: intake allow, block, clarify."""

    decision = GuardrailDecision(stage="intake", outcome=outcome)
    assert route_intake(_state(intake=decision)) == expected


def test_a_missing_intake_verdict_refuses_rather_than_proceeds() -> None:
    """Failing open on a guardrail would make the guardrail optional."""

    assert route_intake(_state()) == "safe_refusal"


def test_the_coverage_edge_maps_every_verdict() -> None:
    """Section 14.1: sufficient, recoverable, critical."""

    assert (
        route_coverage(
            _state(quantitative=_quantitative(), retrieval=_retrieval(), evidence_round=1)
        )
        == "conflict_gate"
    )
    assert (
        route_coverage(
            _state(
                quantitative=_quantitative(),
                retrieval=_retrieval(covered=(), uncovered=("support",)),
                evidence_round=1,
            )
        )
        == "targeted_retry"
    )
    assert (
        route_coverage(
            _state(
                quantitative=_quantitative(
                    available=False, coverage=_coverage(critical_gaps=("x",))
                ),
                retrieval=_retrieval(),
                evidence_round=1,
            )
        )
        == "degraded_result"
    )


def test_the_conflict_edge_defaults_to_the_linear_path() -> None:
    """Phase 5 has no ToT subgraph, and the gate is written never to claim one."""

    assert route_conflict(_state()) == "fast_adjudication"
    assert (
        route_conflict(_state(conflict=ConflictAssessment(triggered=False, evaluated=False)))
        == "fast_adjudication"
    )
    assert (
        route_conflict(_state(conflict=ConflictAssessment(triggered=True, severity="severe")))
        == "tot_adjudication"
    )


def test_the_verification_edge_regenerates_once_and_then_falls_back() -> None:
    """Section 14.2 allows exactly one output regeneration."""

    failed = OutputVerification(passed=False, attempts=1, failures=("bad number",))
    again = OutputVerification(passed=False, attempts=2, failures=("bad number",))
    assert route_verification(_state(output_verification=failed)) == "fast_adjudication"
    assert route_verification(_state(output_verification=again)) == "safe_fallback"
    assert (
        route_verification(_state(output_verification=OutputVerification(passed=True)))
        == "assign_route"
    )
    assert route_verification(_state()) == "safe_fallback"


# -- Confidence --------------------------------------------------------------


def test_confidence_is_the_documented_weighted_sum() -> None:
    """Section 16.1's recommended structure, unchanged and recomputable."""

    bundle = _bundle()
    breakdown = compute_confidence(bundle, planned_sub_goals=1, adjudicator_agrees=True)
    expected = (
        CALIBRATED_WEIGHT * breakdown.calibrated_probability
        + COVERAGE_WEIGHT * breakdown.coverage_score
        + AGREEMENT_WEIGHT * breakdown.agreement_score
    )
    assert breakdown.raw_confidence == pytest.approx(expected, abs=1e-6)
    assert breakdown.confidence == pytest.approx(breakdown.raw_confidence, abs=1e-6)


def test_no_directional_evidence_is_neutral_rather_than_good() -> None:
    """Silence must not be scored as agreement."""

    bundle = _bundle(supporting=(), counterevidence=())
    assert agreement_score(bundle, adjudicator_agrees=True) == pytest.approx(0.6 * 0.5 + 0.4)
    assert agreement_score(bundle, adjudicator_agrees=False) == pytest.approx(0.3)


def test_counterevidence_lowers_agreement() -> None:
    """Evidence pointing the other way is the signal this score exists to carry."""

    against = _bundle(
        supporting=(_citation("A"),), counterevidence=(_citation("B"), _citation("C"))
    )
    assert agreement_score(against, True) < agreement_score(_bundle(), True)


def test_coverage_rewards_weeks_sub_goals_and_breadth() -> None:
    """A run short on any of the three is not fully evidenced."""

    complete = coverage_score(_coverage(), planned=2, covered=2, families=3)
    thin = coverage_score(_coverage(observed_weeks=3), planned=2, covered=1, families=1)
    assert complete == pytest.approx(1.0)
    assert 0.0 < thin < complete


def test_a_critical_gap_caps_confidence_below_the_amber_floor() -> None:
    """Section 16.1: critical source missing, maximum 0.69."""

    bundle = _bundle(coverage=_coverage(critical_gaps=("no telemetry",)))
    breakdown = compute_confidence(bundle, planned_sub_goals=1, adjudicator_agrees=True)
    assert breakdown.confidence <= CAP_CRITICAL_SOURCE_MISSING
    assert "critical_source_missing" in breakdown.applied_caps


def test_a_near_tie_caps_confidence() -> None:
    """Two outcomes within 0.10 are not distinguishable on this evidence."""

    bundle = _bundle(quantitative=_quantitative(distribution=dict(TIED), model_probability=0.40))
    breakdown = compute_confidence(bundle, planned_sub_goals=1, adjudicator_agrees=True)
    assert "persistent_tie" in breakdown.applied_caps
    assert top_two_margin(TIED) < top_two_margin(CLEAR)
    assert top_two_margin({"only": 1.0}) == 1.0


def test_an_unfilled_retrieval_gap_caps_confidence_at_the_amber_ceiling() -> None:
    """Section 16.1: exhausted noncritical retrieval gap, maximum 0.84."""

    breakdown = compute_confidence(
        _bundle(), planned_sub_goals=1, adjudicator_agrees=True, retrieval_gap=True
    )
    assert breakdown.confidence <= CAP_EXHAUSTED_RETRIEVAL_GAP
    assert "exhausted_noncritical_retrieval_gap" in breakdown.applied_caps


def test_a_repaired_output_caps_the_score_the_adjudicator_already_published() -> None:
    """The cap is applied after verification without recomputing the score."""

    confident = _bundle(
        quantitative=_quantitative(
            distribution={"Churned": 0.95, "Contracted": 0.03, "Renewed": 0.01, "Expanded": 0.01},
            model_probability=0.95,
        ),
        retrieval=_retrieval(covered=("adoption", "support", "relationship")),
    )
    breakdown = compute_confidence(confident, planned_sub_goals=3, adjudicator_agrees=True)
    assert breakdown.confidence > CAP_REPAIRED_VERIFICATION

    repaired = apply_verification_cap(breakdown, OutputVerification(passed=True, attempts=2))
    assert repaired.confidence == pytest.approx(CAP_REPAIRED_VERIFICATION)
    assert "repaired_output_verification" in repaired.applied_caps
    # The raw score is preserved, so a reviewer can see both what the evidence
    # supported and what the cap allowed to be released.
    assert repaired.raw_confidence == breakdown.raw_confidence


def test_a_cap_that_does_not_bind_is_not_recorded_as_applied() -> None:
    """Listing every cap considered would make `applied_caps` meaningless.

    A repaired output is still visible: `OutputVerification.attempts` carries it
    and the amber band names it as the reason.
    """

    modest = compute_confidence(_bundle(), planned_sub_goals=1, adjudicator_agrees=True)
    assert modest.confidence < CAP_REPAIRED_VERIFICATION
    assert apply_verification_cap(modest, OutputVerification(passed=True, attempts=2)) is modest
    assert apply_verification_cap(modest, OutputVerification(passed=True, attempts=1)) is modest
    assert apply_verification_cap(modest, None) is modest


# -- Human-review bands ------------------------------------------------------


def _route(**overrides: object) -> tuple[str, str]:
    defaults: dict[str, object] = {
        "confidence": 0.90,
        "coverage": _coverage(),
        "verification": OutputVerification(passed=True),
        "conflict": None,
        "distribution": dict(CLEAR),
        "outcome": "Renewed",
        "high_value": False,
        "retrieval_gap": False,
    }
    verdict = human_route(**{**defaults, **overrides})  # type: ignore[arg-type]
    return verdict.route, verdict.reason


def test_a_clean_confident_run_releases_green() -> None:
    """Section 16.5's green band."""

    band, reason = _route()
    assert band == "green"
    assert "release bar" in reason


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"confidence": 0.55}, "below 0.70"),
        ({"distribution": dict(TIED), "outcome": "Churned"}, "within"),
        ({"coverage": _coverage(critical_gaps=("no history",))}, "critical coverage"),
        (
            {"verification": OutputVerification(passed=False, failures=("bad number",))},
            "verification failed",
        ),
        ({"high_value": True, "outcome": "Churned"}, "high-value"),
        (
            {"conflict": ConflictAssessment(triggered=True, severity="severe")},
            "severe conflict",
        ),
    ],
)
def test_every_red_condition_routes_red(overrides: dict[str, object], fragment: str) -> None:
    """Section 16.5's red band, condition by condition."""

    band, reason = _route(**overrides)
    assert band == "red"
    assert fragment in reason


def test_a_request_to_act_routes_red_even_on_a_confident_run() -> None:
    """An action is a person's decision whatever the model thinks."""

    intake = GuardrailDecision(
        stage="intake", outcome="review", reason_codes=("escalate_to_human",)
    )
    band, reason = _route(intake=intake)
    assert band == "red"
    assert "a person must decide" in reason


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"confidence": 0.80}, "below 0.85"),
        ({"retrieval_gap": True}, "noncritical retrieval gap"),
        ({"verification": OutputVerification(passed=True, attempts=2)}, "one regeneration"),
        ({"coverage": _coverage(stale_sources=("usage_weekly",))}, "stale sources"),
    ],
)
def test_every_amber_condition_routes_amber(overrides: dict[str, object], fragment: str) -> None:
    """Section 16.5's amber band: provisional, and reviewed asynchronously."""

    band, reason = _route(**overrides)
    assert band == "amber"
    assert fragment in reason


def test_an_adverse_call_on_an_ordinary_account_is_not_automatically_red() -> None:
    """The high-value rule must not quietly become "every bad news is red"."""

    assert _route(outcome="Churned", high_value=False)[0] == "green"


def test_an_abstention_escalates_on_impact_as_well_as_on_gaps() -> None:
    """Escalation is impact-aware, not a count of how many gaps there are."""

    assert abstention_route(_coverage(), high_value=False).route == "amber"
    assert abstention_route(_coverage(), high_value=True).route == "red"
    verdict = abstention_route(_coverage(critical_gaps=("no history",)), high_value=False)
    band, reason = verdict.route, verdict.reason
    assert band == "red"
    assert "critical coverage is missing" in reason


def test_a_severe_conflict_caps_confidence_even_before_the_tot_subgraph() -> None:
    """Section 16.1: severe unresolved conflict, maximum 0.69.

    Phase 6 decides when a conflict is severe; the cap that follows from one is
    implemented and tested here so the two arrive already agreeing.
    """

    breakdown = compute_confidence(
        _bundle(),
        planned_sub_goals=1,
        adjudicator_agrees=True,
        conflict=ConflictAssessment(triggered=True, severity="severe"),
    )
    assert breakdown.confidence <= CAP_CRITICAL_SOURCE_MISSING
    assert "severe_unresolved_conflict" in breakdown.applied_caps


def test_a_repaired_output_is_capped_inside_the_calculation_too() -> None:
    """The cap applies wherever the verification is already known."""

    breakdown = compute_confidence(
        _bundle(
            quantitative=_quantitative(
                distribution={
                    "Churned": 0.95,
                    "Contracted": 0.03,
                    "Renewed": 0.01,
                    "Expanded": 0.01,
                },
                model_probability=0.95,
            )
        ),
        planned_sub_goals=1,
        adjudicator_agrees=True,
        verification=OutputVerification(passed=True, attempts=2),
    )
    assert breakdown.confidence <= CAP_REPAIRED_VERIFICATION
    assert "repaired_output_verification" in breakdown.applied_caps


def test_a_failed_tree_of_thought_draft_is_not_regenerated_linearly() -> None:
    """Regenerating one linearly would swap the search's choice for the argmax.

    `fast_adjudication` builds its decision around the calibrated model's most
    likely outcome. Sending a failed Tree-of-Thought draft there would hand back
    a different outcome under the same run id and report it as the search's.
    """

    failed = OutputVerification(passed=False, attempts=1, failures=("bad number",))
    linear_draft = _decision(selected_by="linear")
    tot_draft = _decision(selected_by="tree_of_thought")

    assert (
        route_verification(_state(output_verification=failed, draft_decision=linear_draft))
        == "fast_adjudication"
    )
    assert (
        route_verification(_state(output_verification=failed, draft_decision=tot_draft))
        == "safe_fallback"
    )


def test_a_passing_tree_of_thought_draft_routes_normally() -> None:
    """The special case is failure only; a verified search result is released."""

    passed = OutputVerification(passed=True)
    draft = _decision(selected_by="tree_of_thought")
    assert route_verification(_state(output_verification=passed, draft_decision=draft)) == (
        "assign_route"
    )


def test_an_unresolved_conflict_abstention_routes_red() -> None:
    """Section 15.6: a persistent tie is a red review case, not an amber note."""

    verdict = abstention_route(
        _coverage(), high_value=False, unresolved_conflict="the branches stayed tied"
    )
    assert verdict.route == "red"
    assert "not resolved" in verdict.reason
    assert "unresolved_conflict" in verdict.codes


def test_an_abstention_carries_rule_codes_like_any_other_route() -> None:
    """The runs that abstain were the only runs carrying no codes.

    Section 22.6 measures "exhausted-retrieval safe fallback" over exactly those
    runs, so a bare band and a sentence meant the metric counted nothing at all
    and reported "not measured" on every evaluation.
    """

    exhausted = abstention_route(
        _coverage(critical_gaps=("retrieval was exhausted",)), high_value=False
    )
    assert exhausted.route == "red"
    assert "critical_coverage_missing" in exhausted.codes

    ordinary = abstention_route(_coverage(), high_value=False)
    assert ordinary.route == "amber"
    assert ordinary.codes == ("insufficient_evidence",)

    high_value = abstention_route(_coverage(), high_value=True)
    assert "high_value_account" in high_value.codes
