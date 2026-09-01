"""The graph's nodes (plan section 14).

One function per box in section 14's flowchart, in the order they appear there.
Each returns a partial state update and nothing else: nodes never mutate the
state they were given, so a resumed run replays cleanly from a checkpoint.

Two conventions run through the file.

**Failure is data, not an exception.** Section 14.3 asks for classified failures
and defined recovery. The two evidence lanes therefore catch broadly and return
an unavailable result with the reason attached, because a lane that raises ends
the run while a lane that reports lets the coverage gate degrade the answer,
which is what the plan requires.

**Every node traces.** Section 21.1 makes local tracing mandatory, and the trace
is the only place a reviewer can see that the two lanes really ran in parallel
or that a retry really happened.
"""

import time
from collections.abc import Callable
from datetime import date
from typing import Any, TypeVar

from meridian.agents.evidence_retriever import SUB_GOAL_SOURCES, merge_evidence
from meridian.agents.forecast_adjudicator import (
    CandidateGeneration,
    deterministic_draft,
    split_evidence,
    verify_output,
)
from meridian.contracts import (
    BlockedDecision,
    Citation,
    ConflictAssessment,
    CoverageReport,
    ErrorCode,
    EvidenceBundle,
    ForecastDecision,
    GuardrailDecision,
    InsufficientEvidenceDecision,
    NodeError,
    QuantitativeEvidence,
    RequestedData,
    RetrievalEvidence,
    SubGoal,
    TraceEvent,
)
from meridian.data.repository import AccountProfile
from meridian.features.baselines import PortfolioBaseline
from meridian.graph.confidence import apply_verification_cap, compute_confidence
from meridian.graph.conflict import detect_conflict
from meridian.graph.routing import abstention_route, coverage_verdict, human_route
from meridian.graph.runtime import GraphRuntime
from meridian.graph.state import ForecasterState
from meridian.graph.tot import ToTResult, search
from meridian.graph.tracing import GraphEvent, TraceRecorder
from meridian.guardrails.intake import evaluate_intake

#: Retrieved evidence older than this at the cutoff is reported as stale. Two
#: quarters is the support and event feature window, so evidence older than that
#: describes a period the metrics no longer cover.
STALE_EVIDENCE_DAYS = 180

_REQUESTED_DATA = {
    "adoption": RequestedData(
        source="usage_weekly",
        detail="weekly product telemetry for this account",
        window="the 13 weeks before the cutoff",
    ),
    "support": RequestedData(
        source="support_tickets",
        detail="support tickets with priority, status, and sentiment",
        window="the 26 weeks before the cutoff",
    ),
    "external": RequestedData(
        source="external_events",
        detail="verified external company events",
        window="the 26 weeks before the cutoff",
    ),
}

ResultT = TypeVar("ResultT")


def _timed(work: Callable[[], ResultT]) -> tuple[ResultT, float]:
    """Run `work` and return its result with the milliseconds it took."""

    started = time.perf_counter()
    result = work()
    return result, (time.perf_counter() - started) * 1000


def _recorder(state: ForecasterState) -> TraceRecorder:
    """Return a recorder bound to this run's identifiers."""

    return TraceRecorder(state.get("run_id", "unknown"), state.get("thread_id", "unknown"))


def _trace(
    state: ForecasterState,
    node: str,
    event: GraphEvent,
    payload: dict[str, Any] | None = None,
    latency_ms: float = 0.0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> list[TraceEvent]:
    """Return a one-event trace update."""

    return [
        _recorder(state).event(
            node, event, payload or {}, latency_ms, prompt_tokens, completion_tokens
        )
    ]


def _expected_families(plan: list[SubGoal]) -> frozenset[str]:
    """Return the source families this plan actually asked for.

    A family nothing asked about is not a gap. Reporting one would make every
    focused assessment look under-evidenced.
    """

    return frozenset(
        family for sub_goal in plan for family in SUB_GOAL_SOURCES.get(sub_goal.kind, ())
    )


def combined_coverage(
    quantitative: QuantitativeEvidence,
    retrieval: RetrievalEvidence,
    plan: list[SubGoal],
    cutoff: date,
) -> CoverageReport:
    """Merge what each lane observed into one report (plan section 9.1)."""

    base = quantitative.coverage
    citations = retrieval.citations
    present = {citation.source_type for citation in citations}
    expected = _expected_families(plan)

    missing = [*base.missing_sources]
    missing.extend(f"evidence:{family}" for family in sorted(expected - present))

    stale = [*base.stale_sources]
    for family in sorted(present):
        dates = [
            citation.doc_date
            for citation in citations
            if citation.source_type == family and citation.doc_date is not None
        ]
        if dates and (cutoff - max(dates)).days > STALE_EVIDENCE_DAYS:
            stale.append(f"evidence:{family}")

    critical = [*base.critical_gaps]
    if not retrieval.available:
        critical.append(f"retrieval unavailable: {retrieval.unavailable_reason}")

    return CoverageReport(
        expected_weeks=base.expected_weeks,
        observed_weeks=base.observed_weeks,
        source_counts={
            **base.source_counts,
            "retrieved_documents": len(citations),
            "guidance_documents": len(retrieval.guidance),
        },
        missing_sources=tuple(dict.fromkeys(missing)),
        stale_sources=tuple(dict.fromkeys(stale)),
        critical_gaps=tuple(dict.fromkeys(critical)),
    )


class GraphNodes:
    """The callables the graph is built from."""

    def __init__(self, runtime: GraphRuntime) -> None:
        self._runtime = runtime

    # -- Intake -------------------------------------------------------------

    def intake(self, state: ForecasterState) -> dict[str, Any]:
        """Validate the request against the intake guardrails (section 16.2)."""

        request = state["request"]
        decision, latency = _timed(lambda: evaluate_intake(request, self._runtime.repository))
        started = _trace(
            state,
            "validate_request",
            "run_started",
            {
                "account_id": request.account_id,
                "mode": request.mode,
                "requester_role": request.requester_role,
                "question": request.question,
                "requested_as_of": (
                    request.requested_as_of.isoformat() if request.requested_as_of else None
                ),
            },
        )
        event: GraphEvent = "request_validated" if decision.allowed else "request_blocked"
        return {
            "intake": decision,
            "trace_summary": [
                *started,
                *_trace(
                    state,
                    "validate_request",
                    event,
                    {
                        "outcome": decision.outcome,
                        "rule_ids": list(decision.rule_ids),
                        "reason_codes": list(decision.reason_codes),
                    },
                    latency,
                ),
            ],
        }

    def blocked(self, state: ForecasterState) -> dict[str, Any]:
        """Return a safe refusal (section 16.5, the blocked band)."""

        request = state["request"]
        decision = state.get("intake") or GuardrailDecision(
            stage="intake", outcome="block", message="This request cannot be answered."
        )
        return {
            "blocked": BlockedDecision(
                account_id=request.account_id,
                message=decision.message or "This request cannot be answered.",
                rule_ids=decision.rule_ids,
                reason_codes=decision.reason_codes,
            ),
            "route": "blocked",
            "trace_summary": _trace(
                state,
                "safe_refusal",
                "run_completed",
                {"route": "blocked", "reason_codes": list(decision.reason_codes)},
            ),
        }

    # -- Context and planning ------------------------------------------------

    def load_context(self, state: ForecasterState) -> dict[str, Any]:
        """Load the sanitized profile and this system's own prior decisions."""

        request = state["request"]
        (profile, priors), latency = _timed(
            lambda: self._runtime.orchestrator.load_context(request.account_id)
        )
        return {
            "account": profile,
            "prior_assessments": list(priors),
            "trace_summary": _trace(
                state,
                "load_context",
                "context_loaded",
                {
                    "account_id": profile.account_id,
                    "segment": profile.segment,
                    "effective_cutoff": profile.effective_cutoff.isoformat(),
                    "prior_assessments": len(priors),
                    "high_value": self._runtime.high_value.is_high_value(profile),
                },
                latency,
            ),
        }

    def plan(self, state: ForecasterState) -> dict[str, Any]:
        """Choose two to four typed sub-goals (section 13.1)."""

        account = state["account"]
        assert account is not None
        result, latency = _timed(
            lambda: self._runtime.orchestrator.plan(
                state["request"], account, tuple(state.get("prior_assessments", []))
            )
        )
        return {
            "plan": list(result.plan),
            "evidence_round": 0,
            "retrieval_retries": 0,
            "trace_summary": _trace(
                state,
                "plan_sub_goals",
                "plan_created",
                {
                    "sub_goals": [sub_goal.kind for sub_goal in result.plan],
                    "source": result.source,
                    "fallback_reason": result.fallback_reason,
                    "model": result.model_name,
                },
                latency,
                result.usage.prompt_tokens,
                result.usage.completion_tokens,
            ),
        }

    # -- Parallel lanes ------------------------------------------------------

    def quantitative(self, state: ForecasterState) -> dict[str, Any]:
        """Run the deterministic lane (section 13.2).

        Writes only `quantitative`, plus the two accumulating keys. Section 9.2
        requires that of a parallel node, and writing anything else here would
        race the retrieval lane.
        """

        request = state["request"]
        account = state["account"]
        assert account is not None
        errors: list[NodeError] = []
        try:
            evidence, latency = _timed(
                lambda: self._runtime.analyst.analyse(request.account_id, request.requested_as_of)
            )
        except Exception as error:  # a broad catch: section 14.3 classifies, it does not raise
            latency = 0.0
            evidence = QuantitativeEvidence(
                account_id=request.account_id,
                cutoff=account.effective_cutoff,
                coverage=CoverageReport(
                    expected_weeks=0,
                    observed_weeks=0,
                    critical_gaps=(f"{type(error).__name__}: {error}",),
                ),
                available=False,
            )
            errors.append(
                NodeError(
                    node="quantitative_lane",
                    category="permanent_tool",
                    code="CRITICAL_DATA_GAP",
                    message=f"{type(error).__name__}: {error}"[:500],
                )
            )

        return {
            "quantitative": evidence,
            "errors": errors,
            "trace_summary": _trace(
                state,
                "quantitative_lane",
                "quantitative_completed",
                {
                    "available": evidence.available,
                    "predicted_outcome": evidence.predicted_outcome,
                    "model_probability": evidence.model_probability,
                    "metrics": len(evidence.metrics),
                    "observed_weeks": evidence.coverage.observed_weeks,
                    "critical_gaps": list(evidence.coverage.critical_gaps),
                },
                latency,
            ),
        }

    def retrieval(self, state: ForecasterState) -> dict[str, Any]:
        """Run the retrieval lane (section 13.3). Writes only `retrieval`."""

        request = state["request"]
        account = state["account"]
        assert account is not None
        cutoff = account.effective_cutoff
        plan = state.get("plan", [])
        errors: list[NodeError] = []
        try:
            evidence, latency = _timed(
                lambda: self._runtime.retriever.gather(
                    request.account_id, cutoff, plan, request.requested_as_of
                )
            )
        except Exception as error:  # a broad catch: section 14.3 classifies, it does not raise
            latency = 0.0
            evidence = RetrievalEvidence(
                account_id=request.account_id,
                cutoff=cutoff,
                available=False,
                unavailable_reason=f"{type(error).__name__}: {error}",
            )
            errors.append(
                NodeError(
                    node="retrieval_lane",
                    category="permanent_tool",
                    code="RETRIEVAL_EXHAUSTED",
                    message=f"{type(error).__name__}: {error}"[:500],
                )
            )

        return {
            "retrieval": evidence,
            "errors": errors,
            "trace_summary": _trace(
                state,
                "retrieval_lane",
                "retrieval_attempted",
                {
                    "available": evidence.available,
                    "sub_goals": [item.sub_goal for item in evidence.observations],
                    "covered": list(evidence.covered_sub_goals),
                    "uncovered": list(evidence.uncovered_sub_goals),
                    "citations": len(evidence.citations),
                    "guidance": len(evidence.guidance),
                    "retries": sum(item.retry_count for item in evidence.observations),
                    "unavailable_reason": evidence.unavailable_reason,
                },
                latency,
            ),
        }

    # -- Fan-in and coverage -------------------------------------------------

    def merge(self, state: ForecasterState) -> dict[str, Any]:
        """Build the evidence bundle from both lanes (section 9.2's fan-in)."""

        quantitative = state.get("quantitative")
        retrieval = state.get("retrieval")
        account = state["account"]
        assert account is not None
        assert quantitative is not None and retrieval is not None

        plan = state.get("plan", [])
        coverage = combined_coverage(quantitative, retrieval, plan, account.effective_cutoff)
        outcome = quantitative.predicted_outcome or ""
        supporting, counterevidence, context = split_evidence(retrieval.citations, outcome)

        bundle = EvidenceBundle(
            account_id=account.account_id,
            cutoff=quantitative.cutoff,
            quantitative=quantitative,
            retrieval=retrieval,
            coverage=coverage,
            supporting=supporting,
            counterevidence=counterevidence,
            context=context,
            guidance=retrieval.guidance,
        )
        evidence_round = state.get("evidence_round", 0) + 1
        verdict, reason = coverage_verdict(quantitative, retrieval, evidence_round)

        return {
            "evidence_bundle": bundle,
            "evidence_round": evidence_round,
            "trace_summary": [
                *_trace(
                    state,
                    "merge_evidence",
                    "evidence_merged",
                    {
                        "round": evidence_round,
                        "supporting": len(supporting),
                        "counterevidence": len(counterevidence),
                        "context": len(context),
                        "guidance": len(bundle.guidance),
                        "missing_sources": list(coverage.missing_sources),
                        "stale_sources": list(coverage.stale_sources),
                    },
                ),
                *_trace(
                    state,
                    "merge_evidence",
                    "coverage_evaluated",
                    {"verdict": verdict, "reason": reason, "round": evidence_round},
                ),
            ],
        }

    def targeted_retry(self, state: ForecasterState) -> dict[str, Any]:
        """Retrieve once more, only for the sub-goals that came back empty.

        Section 13.1 allows "at most one additional evidence round when a
        specific noncritical gap is recoverable". Repeating the whole sweep
        would spend the budget re-fetching evidence the run already holds.
        """

        request = state["request"]
        account = state["account"]
        previous = state.get("retrieval")
        assert account is not None and previous is not None

        plan = state.get("plan", [])
        targets = previous.uncovered_sub_goals or tuple(
            sub_goal.kind for sub_goal in plan if sub_goal.kind != "playbook_guidance"
        )
        retry, latency = _timed(
            lambda: self._runtime.retriever.gather(
                request.account_id,
                account.effective_cutoff,
                plan,
                request.requested_as_of,
                only=targets,
            )
        )
        merged = merge_evidence(previous, retry)
        return {
            "retrieval": merged,
            "retrieval_retries": state.get("retrieval_retries", 0) + 1,
            "trace_summary": _trace(
                state,
                "targeted_retry",
                "retrieval_retried",
                {
                    "targets": list(targets),
                    "citations_before": len(previous.citations),
                    "citations_after": len(merged.citations),
                    "still_uncovered": list(merged.uncovered_sub_goals),
                },
                latency,
            ),
        }

    # -- Conflict gate -------------------------------------------------------

    def conflict_gate(self, state: ForecasterState) -> dict[str, Any]:
        """Decide whether the evidence materially disagrees (section 15.1).

        Eight deterministic triggers, none of which asks a model anything.
        Whether a run spends four extra generations and a critic pass is a
        structural transition, and section 14.1 keeps those away from an LLM.
        """

        bundle = state.get("evidence_bundle")
        assert bundle is not None

        baseline: PortfolioBaseline | None = None
        if self._runtime.baselines is not None:
            baseline = self._runtime.baselines.get()

        assessment, latency = _timed(lambda: detect_conflict(bundle, baseline))
        event: GraphEvent = "conflict_detected" if assessment.triggered else "conflict_evaluated"
        return {
            "conflict": assessment,
            "trace_summary": _trace(
                state,
                "conflict_gate",
                event,
                {
                    "triggered": assessment.triggered,
                    "severity": assessment.severity,
                    "rule_ids": list(assessment.rule_ids),
                    "conflict_types": list(assessment.conflict_types),
                    "reasons": list(assessment.reasons),
                    "baseline_accounts": baseline.accounts_measured if baseline else 0,
                },
                latency,
            ),
        }

    def tot_adjudication(self, state: ForecasterState) -> dict[str, Any]:
        """Run the bounded Tree-of-Thought search (sections 15.2 to 15.6).

        Four candidates, hard pruning, a frozen rubric, a beam of two, one
        stress test each, and at most one consistency vote. The search either
        selects a winner -- which becomes a draft decision verified like any
        other -- or abstains, which is a red review case rather than a guess.

        The outcome a winner carries is chosen from the four canonical classes
        by a deterministic score. A model may argue each case; it cannot invent
        an outcome, change a prior, or award itself a point.
        """

        bundle = state.get("evidence_bundle")
        account = state["account"]
        conflict = state.get("conflict")
        assert bundle is not None and account is not None

        generation, generation_ms = _timed(
            lambda: self._runtime.adjudicator.generate_candidates(bundle)
        )
        result, search_ms = _timed(lambda: search(generation.candidates, bundle))

        events = _trace(
            state,
            "tot_adjudication",
            "tot_started",
            {
                "candidates": len(generation.candidates),
                "source": generation.source,
                "fallback_reason": generation.fallback_reason,
                "severity": conflict.severity if conflict else "none",
            },
            generation_ms,
            generation.usage.prompt_tokens,
            generation.usage.completion_tokens,
        )
        events.extend(
            _trace(
                state,
                "tot_adjudication",
                "tot_completed",
                {
                    "branches": len(result.branches),
                    "pruned": len(result.pruned),
                    "survivors": [branch.outcome for branch in result.survivors],
                    "scores": [round(branch.score, 4) for branch in result.survivors],
                    "winner": result.winner.outcome if result.winner else None,
                    "margin": round(result.margin, 4),
                    "tie_broken_by_vote": result.tie_broken_by_vote,
                    "abstained": result.abstained,
                    "abstain_reason": result.abstain_reason,
                },
                search_ms,
            )
        )

        branches = list(result.branches)
        if result.winner is None:
            return {
                "candidates": branches,
                "conflict": (conflict or ConflictAssessment()).model_copy(
                    update={"resolved": False}
                ),
                **self._conflict_abstention(state, bundle, account, result),
                "trace_summary": events,
            }

        resolved = (conflict or ConflictAssessment()).model_copy(update={"resolved": True})
        decision, decision_ms = _timed(
            lambda: self._decision_from_candidate(state, bundle, result, generation)
        )
        events.extend(
            _trace(
                state,
                "tot_adjudication",
                "decision_drafted",
                {
                    "outcome": decision.outcome,
                    "narrative_source": decision.narrative_source,
                    "confidence": decision.confidence,
                    "applied_caps": list(decision.confidence_breakdown.applied_caps),
                    "selected_by": "tree_of_thought",
                    "agrees_with_model": decision.outcome == bundle.quantitative.predicted_outcome,
                },
                decision_ms,
            )
        )
        return {
            "candidates": branches,
            "conflict": resolved,
            "draft_decision": decision,
            "trace_summary": events,
        }

    def _decision_from_candidate(
        self,
        state: ForecasterState,
        bundle: EvidenceBundle,
        result: ToTResult,
        generation: CandidateGeneration,
    ) -> ForecastDecision:
        """Turn the winning branch into a decision the verifier can check."""

        winner = result.winner
        assert winner is not None
        quantitative = bundle.quantitative

        breakdown = compute_confidence(
            bundle,
            planned_sub_goals=len(state.get("plan", [])),
            # The search reached a verdict that survived its own stress test,
            # so the adjudication agrees with the label it selected. What the
            # evidence says is already priced in through the citation split.
            adjudicator_agrees=True,
            conflict=state.get("conflict"),
            retrieval_gap=bool(bundle.retrieval.uncovered_sub_goals),
        )

        limitations = [
            "Selected by a bounded Tree-of-Thought search because the evidence "
            "materially disagreed; the branch summaries and scores are in the trace.",
            *self._intake_limitations(state.get("intake")),
        ]
        if winner.outcome != quantitative.predicted_outcome:
            limitations.append(
                f"The search selected {winner.outcome}, which is not the calibrated "
                f"model's most likely outcome ({quantitative.predicted_outcome})."
            )
        if result.tie_broken_by_vote:
            limitations.append("The two leading branches were separated by a consistency vote.")
        if bundle.coverage.missing_sources:
            limitations.append(
                "Evidence was not available for: " + ", ".join(bundle.coverage.missing_sources)
            )

        cited = tuple(
            dict.fromkeys((*winner.supporting_citation_ids, *winner.counterevidence_citation_ids))
        )
        return ForecastDecision(
            account_id=bundle.account_id,
            cutoff=bundle.cutoff,
            outcome=winner.outcome,
            distribution=quantitative.distribution,
            confidence=breakdown.confidence,
            confidence_breakdown=breakdown,
            rationale=winner.rationale,
            drivers=quantitative.drivers,
            citations=bundle.supporting + bundle.context + bundle.guidance,
            counterevidence=bundle.counterevidence,
            cited_doc_ids=cited,
            limitations=tuple(dict.fromkeys(limitations)),
            recommended_action=(
                "Review the branch summaries with the account team before acting: the "
                "evidence disagreed and this outcome was selected over the alternatives."
            ),
            route="amber",
            narrative_source=winner.source,
            selected_by="tree_of_thought",
            model_name=generation.model_name,
        )

    def _conflict_abstention(
        self,
        state: ForecasterState,
        bundle: EvidenceBundle,
        account: AccountProfile,
        result: ToTResult,
    ) -> dict[str, Any]:
        """Return the state update for a search that could not choose.

        Section 15.6: "If the tie persists, abstain and create a red review
        case." The abstention reuses `InsufficientEvidenceDecision` because that
        type has no outcome field, so a tie cannot leak a label the search
        explicitly declined to pick.
        """

        high_value = self._runtime.high_value.is_high_value(account)
        route, reason = abstention_route(
            bundle.coverage, high_value, unresolved_conflict=result.abstain_reason
        )
        decision = InsufficientEvidenceDecision(
            account_id=bundle.account_id,
            cutoff=bundle.cutoff,
            verified_metrics=bundle.quantitative.metrics,
            gaps=(
                f"The evidence disagrees and the search could not resolve it: "
                f"{result.abstain_reason}.",
                *(
                    f"Branch {branch.outcome} scored {branch.score:.2f}"
                    for branch in result.survivors
                ),
            ),
            requested_data=(
                RequestedData(
                    source="human_review",
                    detail=(
                        "a reviewer's judgement on which of the contradicting signals "
                        "should carry more weight"
                    ),
                    window="at this cutoff",
                ),
            ),
            citations=bundle.supporting + bundle.counterevidence + bundle.context,
            limitations=(
                "No outcome label is reported: the verified evidence supports more than "
                "one outcome and the bounded search declined to choose between them.",
                *self._intake_limitations(state.get("intake")),
            ),
            recommended_action=(
                "Escalate to a human reviewer with the branch summaries; the telemetry "
                "above is verified and is the only position the system will assert."
            ),
            route=route,
            route_reason=reason,
            reason_code="UNRESOLVED_CONFLICT",
        )
        return {"final_result": decision, "route": route}

    # -- Adjudication and verification --------------------------------------

    def fast_adjudication(self, state: ForecasterState) -> dict[str, Any]:
        """Draft a grounded decision from the evidence bundle (section 13.4)."""

        bundle = state.get("evidence_bundle")
        assert bundle is not None
        quantitative = bundle.quantitative
        assert quantitative.predicted_outcome is not None

        previous = state.get("output_verification")
        repair_note = "; ".join(previous.failures) if previous is not None else None
        result, latency = _timed(lambda: self._runtime.adjudicator.draft(bundle, repair_note))
        draft = result.draft

        retrieval_gap = bool(bundle.retrieval.uncovered_sub_goals)
        breakdown = compute_confidence(
            bundle,
            planned_sub_goals=len(state.get("plan", [])),
            adjudicator_agrees=draft.evidence_supports_outcome,
            conflict=state.get("conflict"),
            retrieval_gap=retrieval_gap,
        )

        limitations = [*draft.limitations]
        if draft.disagreement_note:
            limitations.append(draft.disagreement_note)
        limitations.extend(self._intake_limitations(state.get("intake")))
        if bundle.coverage.missing_sources:
            limitations.append(
                "Evidence was not available for: " + ", ".join(bundle.coverage.missing_sources)
            )

        decision = ForecastDecision(
            account_id=bundle.account_id,
            cutoff=bundle.cutoff,
            outcome=quantitative.predicted_outcome,
            distribution=quantitative.distribution,
            confidence=breakdown.confidence,
            confidence_breakdown=breakdown,
            rationale=draft.rationale or "No rationale was produced.",
            drivers=quantitative.drivers,
            citations=bundle.supporting + bundle.context + bundle.guidance,
            counterevidence=bundle.counterevidence,
            cited_doc_ids=tuple(dict.fromkeys(draft.cited_doc_ids)),
            limitations=tuple(dict.fromkeys(limitations)),
            recommended_action=draft.recommended_action or "Review this account with the team.",
            route="amber",
            narrative_source=result.source,
            model_name=result.model_name,
        )

        return {
            "draft_decision": decision,
            "trace_summary": _trace(
                state,
                "fast_adjudication",
                "decision_drafted",
                {
                    "outcome": decision.outcome,
                    "narrative_source": result.source,
                    "confidence": breakdown.confidence,
                    "applied_caps": list(breakdown.applied_caps),
                    "citations": len(decision.citations),
                    "counterevidence": len(decision.counterevidence),
                    "regenerated": previous is not None,
                    "fallback_reason": result.fallback_reason,
                },
                latency,
                result.usage.prompt_tokens,
                result.usage.completion_tokens,
            ),
        }

    @staticmethod
    def _intake_limitations(intake: GuardrailDecision | None) -> list[str]:
        """Turn advisory intake findings into stated limitations."""

        if intake is None or not intake.reason_codes:
            return []
        notes = {
            "flag_unverified": (
                "The request supplied an unverified claim. It was recorded as "
                "unverified and excluded from the evidence."
            ),
            "express_uncertainty": (
                "The request asked for more certainty than the evidence supports; "
                "the calibrated distribution is reported instead of a single call."
            ),
            "escalate_to_human": (
                "The request asked for an action to be taken. This result is advisory "
                "and is routed for human decision."
            ),
        }
        return [notes[code] for code in intake.reason_codes if code in notes]

    def verify_output(self, state: ForecasterState) -> dict[str, Any]:
        """Replay the draft against the evidence it rests on (section 16.4)."""

        decision = state.get("draft_decision")
        bundle = state.get("evidence_bundle")
        assert decision is not None and bundle is not None

        previous = state.get("output_verification")
        attempts = (previous.attempts + 1) if previous is not None else 1
        verification, latency = _timed(
            lambda: verify_output(
                decision.rationale,
                decision.recommended_action,
                decision.limitations,
                decision.cited_doc_ids,
                bundle,
                attempts,
            )
        )
        return {
            "output_verification": verification,
            "trace_summary": _trace(
                state,
                "verify_output",
                "output_verified",
                {
                    "passed": verification.passed,
                    "attempts": verification.attempts,
                    "numeric_claims": verification.checked_numeric_claims,
                    "citations": verification.checked_citations,
                    "failures": list(verification.failures),
                },
                latency,
            ),
        }

    def fallback(self, state: ForecasterState) -> dict[str, Any]:
        """Replace an unverifiable narrative with a deterministic one.

        Section 14.3 asks for a safe fallback and a review case when
        verification fails after its one regeneration. The outcome label is kept
        because it was never the language model's to produce: it comes from the
        calibrated forecaster, and what failed was the explanation. So the
        explanation is rewritten from verified values and the run is routed red.
        """

        decision = state.get("draft_decision")
        bundle = state.get("evidence_bundle")
        verification = state.get("output_verification")
        assert decision is not None and bundle is not None

        safe = deterministic_draft(
            bundle,
            "The generated explanation failed output verification and was replaced "
            "with one composed from verified values.",
            outcome=decision.outcome,
        )
        replaced = decision.model_copy(
            update={
                "rationale": safe.rationale,
                "recommended_action": safe.recommended_action,
                "cited_doc_ids": tuple(dict.fromkeys(safe.cited_doc_ids)),
                "limitations": tuple(
                    dict.fromkeys(
                        [
                            *decision.limitations,
                            *safe.limitations,
                            *(
                                f"Verification failure: {failure}"
                                for failure in (verification.failures if verification else ())
                            ),
                        ]
                    )
                ),
                "narrative_source": "deterministic",
            }
        )
        return {
            "draft_decision": replaced,
            "trace_summary": _trace(
                state,
                "safe_fallback",
                "output_verified",
                {
                    "passed": False,
                    "replaced_with_deterministic_narrative": True,
                    "failures": list(verification.failures) if verification else [],
                },
            ),
        }

    # -- Degraded mode -------------------------------------------------------

    def degraded(self, state: ForecasterState) -> dict[str, Any]:
        """Return verified telemetry and an evidence-gap notice, with no label.

        This is the behaviour the instructor feedback recorded in section 2 asks
        for: a verified-telemetry response, an evidence-gap notice, a targeted
        data request, and impact-aware escalation. `InsufficientEvidenceDecision`
        has no outcome field, so this path cannot emit a categorical forecast
        even by mistake.
        """

        account = state["account"]
        quantitative = state.get("quantitative")
        retrieval = state.get("retrieval")
        assert account is not None

        cutoff = quantitative.cutoff if quantitative is not None else account.effective_cutoff
        bundle = state.get("evidence_bundle")
        if bundle is not None:
            coverage = bundle.coverage
        elif quantitative is not None:
            coverage = quantitative.coverage
        else:
            coverage = CoverageReport(expected_weeks=0, observed_weeks=0)

        gaps: list[str] = [*coverage.critical_gaps]
        requested: list[RequestedData] = []
        reason_code: ErrorCode = "CRITICAL_DATA_GAP"

        if quantitative is None or not quantitative.available:
            for family in quantitative.coverage.missing_sources if quantitative else ():
                if family in _REQUESTED_DATA:
                    requested.append(_REQUESTED_DATA[family])
        if retrieval is not None and not retrieval.available:
            gaps.append(f"Retrieval is unavailable: {retrieval.unavailable_reason}")
            requested.append(
                RequestedData(
                    source="retrieval_index",
                    detail="a built document index for this account's notes and tickets",
                    window="up to the cutoff",
                )
            )
        elif retrieval is not None and retrieval.exhausted:
            reason_code = "RETRIEVAL_EXHAUSTED"
            gaps.append(
                "No qualitative evidence could be retrieved for this account at the cutoff, "
                "so no categorical forecast is issued."
            )
            requested.append(
                RequestedData(
                    source="csm_notes and support_tickets",
                    detail="documented account activity to corroborate the telemetry",
                    window="the 26 weeks before the cutoff",
                )
            )
        if quantitative is not None and not quantitative.available and not requested:
            requested.append(_REQUESTED_DATA["adoption"])
        if not gaps:
            gaps.append("Evidence coverage was insufficient for a categorical forecast.")

        high_value = self._runtime.high_value.is_high_value(account)
        route, route_reason = abstention_route(coverage, high_value)
        citations: tuple[Citation, ...] = (
            retrieval.citations + retrieval.guidance if retrieval is not None else ()
        )

        result = InsufficientEvidenceDecision(
            account_id=account.account_id,
            cutoff=cutoff,
            verified_metrics=quantitative.metrics if quantitative is not None else (),
            gaps=tuple(dict.fromkeys(gaps)),
            requested_data=tuple(dict.fromkeys(requested)),
            citations=citations,
            limitations=(
                "No outcome label is reported: the evidence required to support one "
                "was not available at this cutoff.",
                *self._intake_limitations(state.get("intake")),
            ),
            recommended_action=(
                "Supply the requested sources and re-run the assessment. Until then, "
                "treat the telemetry above as the only verified position."
            ),
            route=route,
            route_reason=route_reason,
            reason_code=reason_code,
        )
        return {
            "final_result": result,
            "route": route,
            "trace_summary": _trace(
                state,
                "degraded_result",
                "degraded_result",
                {
                    "route": route,
                    "reason_code": reason_code,
                    "gaps": list(result.gaps),
                    "requested_sources": [item.source for item in result.requested_data],
                    "verified_metrics": len(result.verified_metrics),
                    "high_value": high_value,
                },
            ),
        }

    # -- Routing and persistence --------------------------------------------

    def route(self, state: ForecasterState) -> dict[str, Any]:
        """Assign the human-review band (section 16.5)."""

        decision = state.get("draft_decision")
        account = state["account"]
        bundle = state.get("evidence_bundle")
        assert decision is not None and account is not None and bundle is not None

        verification = state.get("output_verification")
        breakdown = apply_verification_cap(decision.confidence_breakdown, verification)
        high_value = self._runtime.high_value.is_high_value(account)
        band, reason = human_route(
            confidence=breakdown.confidence,
            coverage=bundle.coverage,
            verification=verification,
            conflict=state.get("conflict"),
            distribution=decision.distribution,
            outcome=decision.outcome,
            high_value=high_value,
            retrieval_gap=bool(bundle.retrieval.uncovered_sub_goals),
            intake=state.get("intake"),
        )
        final = decision.model_copy(
            update={
                "confidence": breakdown.confidence,
                "confidence_breakdown": breakdown,
                "route": band,
                "route_reason": reason,
            }
        )
        events = _trace(
            state,
            "assign_route",
            "decision_routed",
            {
                "route": band,
                "reason": reason,
                "confidence": breakdown.confidence,
                "high_value": high_value,
                "outcome": final.outcome,
            },
        )
        if band == "red":
            events.extend(_trace(state, "assign_route", "review_required", {"reason": reason}))
        return {"final_result": final, "route": band, "trace_summary": events}

    def persist(self, state: ForecasterState) -> dict[str, Any]:
        """Record the decision and open a review case when one is required.

        Section 17.2 persists assessment snapshots; section 14.3 requires a
        review case when a run ends red. Application memory is optional, so a
        deployment without it still completes -- it simply has nothing to
        compare a later run against.
        """

        result = state.get("final_result")
        route = state.get("route")
        store = self._runtime.store
        assessment_id: str | None = None
        case_id: str | None = None

        if store is not None and result is not None:
            if isinstance(result, InsufficientEvidenceDecision):
                outcome = "insufficient_evidence"
                confidence = 0.0
                summary = "; ".join(result.gaps)[:500]
            else:
                outcome = result.outcome
                confidence = result.confidence
                summary = result.rationale[:500]
            record = store.record_assessment(
                account_id=result.account_id,
                cutoff=result.cutoff,
                predicted_outcome=outcome,
                confidence=confidence,
                decision=str(route),
                summary=summary,
            )
            assessment_id = record.assessment_id
            if route == "red":
                case_id = store.open_review_case(
                    record.assessment_id, result.route_reason or "human review required"
                ).case_id

        return {
            "assessment_id": assessment_id,
            "review_case_id": case_id,
            "trace_summary": [
                *_trace(
                    state,
                    "persist",
                    "decision_persisted",
                    {
                        "assessment_id": assessment_id,
                        "review_case_id": case_id,
                        "persisted": assessment_id is not None,
                    },
                ),
                *_trace(
                    state,
                    "persist",
                    "run_completed",
                    {
                        "route": route,
                        "abstained": result.is_abstention if result is not None else None,
                    },
                ),
            ],
        }


__all__ = ["STALE_EVIDENCE_DAYS", "GraphNodes", "combined_coverage"]
