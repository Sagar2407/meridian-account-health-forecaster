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

from langgraph.types import interrupt

from meridian.agents.evidence_retriever import SUB_GOAL_SOURCES, merge_evidence
from meridian.agents.forecast_adjudicator import (
    CandidateGeneration,
    deterministic_draft,
    split_evidence,
    verify_output,
)
from meridian.contracts import (
    AssessmentRequest,
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
    OutputVerification,
    QuantitativeEvidence,
    RequestedData,
    RetrievalEvidence,
    ReviewerDecision,
    ReviewInterrupt,
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
from meridian.guardrails.evidence import EvidenceScreening, screen_evidence
from meridian.guardrails.intake import evaluate_intake
from meridian.guardrails.runtime import RunBudget

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


def _budget(state: ForecasterState) -> RunBudget:
    """Return what this run has spent so far (plan section 16.3).

    Reconstructed from the state's counters on every read rather than carried
    as an object, because the state is checkpointed and a mutable budget would
    not survive a resume with the right value in it.
    """

    started = state.get("started_at", 0.0)
    return RunBudget(
        model_calls=state.get("model_calls", 0),
        tokens=state.get("spent_tokens", 0),
        elapsed_seconds=max(0.0, time.time() - started) if started else 0.0,
    )


def _budget_after(state: ForecasterState, attempts: int, tokens: int) -> RunBudget:
    """Return the runtime budget after one structured-generation operation."""

    current = _budget(state)
    return RunBudget(
        model_calls=current.model_calls + attempts,
        tokens=current.tokens + tokens,
        elapsed_seconds=current.elapsed_seconds,
    )


def _verdict(state: ForecasterState, stage: str) -> GuardrailDecision | None:
    """Return the most recent guardrail verdict for one stage, if it ran."""

    for decision in reversed(state.get("guardrails", [])):
        if decision.stage == stage:
            return decision
    return None


def _strict_verdict(state: ForecasterState, stage: str) -> GuardrailDecision | None:
    """Return a non-pass verdict if the stage ever failed, else its latest.

    Evidence is quarantined permanently within a run.  A targeted retrieval
    retry may later produce clean evidence, but it must not erase the fact that
    an account, cutoff, or provenance boundary was crossed on the first round.
    """

    decisions = [decision for decision in state.get("guardrails", []) if decision.stage == stage]
    return next((decision for decision in decisions if decision.outcome != "pass"), None) or (
        decisions[-1] if decisions else None
    )


def _generation_errors(
    node: str, provider_was_available: bool, fallback_reason: str | None
) -> list[NodeError]:
    """Turn a configured provider's fallback into explicit failure data."""

    if not provider_was_available or not fallback_reason:
        return []
    if fallback_reason in {
        "no language-model provider is configured",
        "the run's model-call budget is spent",
    }:
        return []
    return [
        NodeError(
            node=node,
            category="model",
            code="MODEL_UNAVAILABLE",
            message=fallback_reason,
            recoverable=True,
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

    # -- Guardrail seams ----------------------------------------------------
    #
    # Section 22.4's second ablation asks what each guardrail layer is worth,
    # which cannot be answered without running the graph with a layer removed.
    # These three methods are the only places a subclass can do that. They are
    # seams, not switches: each calls the real check, there is no configuration
    # that changes them, and the only subclass that overrides any of them lives
    # in `meridian_eval`, which no served module may import (section 8.4).

    def screen(
        self,
        quantitative: QuantitativeEvidence,
        retrieval: RetrievalEvidence,
        account_id: str,
        cutoff: date,
    ) -> EvidenceScreening:
        """Screen merged evidence for leakage and provenance (section 16.3)."""

        return screen_evidence(quantitative, retrieval, account_id, cutoff)

    def validate_intake(self, request: AssessmentRequest) -> GuardrailDecision:
        """Return the intake verdict for one request (section 16.2)."""

        return evaluate_intake(request, self._runtime.repository)

    def verify(
        self,
        decision: ForecastDecision,
        bundle: EvidenceBundle,
        attempts: int,
    ) -> OutputVerification:
        """Replay a draft against the evidence it rests on (section 16.4)."""

        return verify_output(
            decision.rationale,
            decision.recommended_action,
            decision.limitations,
            decision.cited_doc_ids,
            bundle,
            attempts,
        )

    # -- Intake -------------------------------------------------------------

    def intake(self, state: ForecasterState) -> dict[str, Any]:
        """Validate the request against the intake guardrails (section 16.2)."""

        request = state["request"]
        decision, latency = _timed(lambda: self.validate_intake(request))
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
            "guardrails": [decision],
            "started_at": time.time(),
            "review_state": "not_required",
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
        budget = _budget(state)
        result, latency = _timed(
            lambda: self._runtime.orchestrator.plan(
                state["request"],
                account,
                tuple(state.get("prior_assessments", [])),
                use_model=budget.may_spend,
            )
        )
        tokens = result.usage.prompt_tokens + result.usage.completion_tokens
        updated_budget = _budget_after(state, result.attempts, tokens)
        errors = _generation_errors(
            "plan_sub_goals",
            self._runtime.generator is not None and budget.may_spend,
            result.fallback_reason,
        )
        events = _trace(
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
        )
        if not updated_budget.may_spend:
            events.extend(
                _trace(
                    state,
                    "plan_sub_goals",
                    "budget_exhausted",
                    {
                        "exceeded": list(updated_budget.exceeded),
                        "model_calls": updated_budget.model_calls,
                    },
                )
            )
        return {
            "plan": list(result.plan),
            "evidence_round": 0,
            "retrieval_retries": 0,
            "model_calls": result.attempts,
            "spent_tokens": tokens,
            "guardrails": [updated_budget.verdict()],
            "errors": errors,
            "trace_summary": events,
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
        """Screen both lanes' evidence, then build the bundle (sections 9.2 and 16.3).

        The fan-in is the last place every piece of evidence is visible at once
        and the last place before it becomes an argument, so the evidence
        guardrail runs here. Anything that cannot be shown to belong to this
        account at this cutoff is quarantined rather than raised: the run
        continues on what survived, the drop is recorded, and `human_route`
        turns a non-empty quarantine into a red band.
        """

        quantitative = state.get("quantitative")
        retrieval = state.get("retrieval")
        account = state["account"]
        assert account is not None
        assert quantitative is not None and retrieval is not None

        requested_cutoff = state["request"].requested_as_of
        expected_cutoff = min(
            account.effective_cutoff, requested_cutoff or account.effective_cutoff
        )
        screening = self.screen(quantitative, retrieval, account.account_id, expected_cutoff)

        if not screening.quantitative_valid:
            quantitative = quantitative.model_copy(
                update={
                    "metrics": screening.metrics,
                    "distribution": {},
                    "predicted_outcome": None,
                    "model_probability": 0.0,
                    "drivers": (),
                    "available": False,
                    "coverage": quantitative.coverage.model_copy(
                        update={
                            "critical_gaps": tuple(
                                dict.fromkeys(
                                    (
                                        *quantitative.coverage.critical_gaps,
                                        "quantitative evidence failed its provenance screen",
                                    )
                                )
                            )
                        }
                    ),
                }
            )

        if not screening.clean:
            # Rebuild the lane result from what survived, so the coverage
            # verdict and the bundle agree about what evidence exists. Leaving
            # the original in place would let a run whose every citation was
            # quarantined still look retrieved-and-covered.
            kept = {citation.doc_id for citation in screening.citations}
            retrieval = retrieval.model_copy(
                update={
                    "observations": tuple(
                        observation.model_copy(
                            update={
                                "citations": tuple(
                                    citation
                                    for citation in observation.citations
                                    if citation.doc_id in kept
                                )
                            }
                        )
                        for observation in retrieval.observations
                    ),
                    "guidance": screening.guidance,
                    "rejected": retrieval.rejected + screening.rejected,
                }
            )

        plan = state.get("plan", [])
        coverage = combined_coverage(quantitative, retrieval, plan, account.effective_cutoff)
        outcome = quantitative.predicted_outcome or ""
        supporting, counterevidence, context = split_evidence(screening.citations, outcome)

        bundle = EvidenceBundle(
            account_id=account.account_id,
            cutoff=quantitative.cutoff,
            quantitative=quantitative,
            retrieval=retrieval,
            coverage=coverage,
            supporting=supporting,
            counterevidence=counterevidence,
            context=context,
            guidance=screening.guidance,
        )
        evidence_round = state.get("evidence_round", 0) + 1
        verdict, reason = coverage_verdict(quantitative, retrieval, evidence_round)

        update: dict[str, Any] = {
            "evidence_bundle": bundle,
            "evidence_round": evidence_round,
            "guardrails": [screening.decision],
            "trace_summary": [
                *_trace(
                    state,
                    "merge_evidence",
                    "evidence_screened",
                    {
                        "outcome": screening.decision.outcome,
                        "rule_ids": list(screening.rule_ids),
                        "quarantined": len(screening.rejected),
                        "reasons": list(screening.rejected),
                    },
                ),
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
        if quantitative is not state.get("quantitative"):
            update["quantitative"] = quantitative
        if not screening.clean:
            update["retrieval"] = retrieval
        return update

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

        budget = _budget(state)
        generation, generation_ms = _timed(
            lambda: self._runtime.adjudicator.generate_candidates(
                bundle, use_model=budget.may_spend
            )
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

        tokens = generation.usage.prompt_tokens + generation.usage.completion_tokens
        updated_budget = _budget_after(state, generation.attempts, tokens)
        generation_errors = _generation_errors(
            "tot_adjudication",
            self._runtime.generator is not None and budget.may_spend,
            generation.fallback_reason,
        )
        spend = {
            "model_calls": generation.attempts,
            "spent_tokens": tokens,
            "guardrails": [updated_budget.verdict()],
            "errors": generation_errors,
        }
        if not updated_budget.may_spend:
            events.extend(
                _trace(
                    state,
                    "tot_adjudication",
                    "budget_exhausted",
                    {
                        "exceeded": list(updated_budget.exceeded),
                        "model_calls": updated_budget.model_calls,
                    },
                )
            )
        branches = list(result.branches)
        if result.winner is None:
            return {
                "candidates": branches,
                "conflict": (conflict or ConflictAssessment()).model_copy(
                    update={"resolved": False}
                ),
                **spend,
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
            **spend,
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
        verdict = abstention_route(
            bundle.coverage, high_value, unresolved_conflict=result.abstain_reason
        )
        route, reason = verdict.route, verdict.reason
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
        return {
            "final_result": decision,
            "route": route,
            "guardrails": [
                GuardrailDecision(
                    stage="output",
                    outcome="pass",
                    message="The typed abstention contains no categorical outcome.",
                ),
                GuardrailDecision(
                    stage="routing",
                    outcome="review",
                    rule_ids=("ROUTE-RED", *verdict.codes),
                    reason_codes=("route_red",),
                    message=reason,
                ),
            ],
        }

    # -- Adjudication and verification --------------------------------------

    def fast_adjudication(self, state: ForecasterState) -> dict[str, Any]:
        """Draft a grounded decision from the evidence bundle (section 13.4)."""

        bundle = state.get("evidence_bundle")
        assert bundle is not None
        quantitative = bundle.quantitative
        assert quantitative.predicted_outcome is not None

        previous = state.get("output_verification")
        repair_note = "; ".join(previous.failures) if previous is not None else None
        budget = _budget(state)
        result, latency = _timed(
            lambda: self._runtime.adjudicator.draft(bundle, repair_note, use_model=budget.may_spend)
        )
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

        tokens = result.usage.prompt_tokens + result.usage.completion_tokens
        updated_budget = _budget_after(state, result.attempts, tokens)
        errors = _generation_errors(
            "fast_adjudication",
            self._runtime.generator is not None and budget.may_spend,
            result.fallback_reason,
        )
        events = _trace(
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
                "within_budget": budget.may_spend,
            },
            latency,
            result.usage.prompt_tokens,
            result.usage.completion_tokens,
        )
        update: dict[str, Any] = {
            "draft_decision": decision,
            "model_calls": result.attempts,
            "spent_tokens": tokens,
            "guardrails": [updated_budget.verdict()],
            "errors": errors,
            "trace_summary": events,
        }
        if not updated_budget.may_spend:
            events.extend(
                _trace(
                    state,
                    "fast_adjudication",
                    "budget_exhausted",
                    {
                        "exceeded": list(updated_budget.exceeded),
                        "model_calls": updated_budget.model_calls,
                    },
                )
            )
        return update

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
        verification, latency = _timed(lambda: self.verify(decision, bundle, attempts))
        guardrail = GuardrailDecision(
            stage="output",
            outcome="pass" if verification.passed else "review",
            rule_ids=() if verification.passed else ("OUTPUT-VERIFICATION",),
            reason_codes=() if verification.passed else ("output_verification_failed",),
            message=(
                "Every numeric claim and cited document matched the verified evidence."
                if verification.passed
                else "; ".join(verification.failures)
            ),
        )
        return {
            "output_verification": verification,
            "guardrails": [guardrail],
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
            # The merged coverage already records this gap when both lanes
            # reported, so appending unconditionally showed a reviewer the same
            # fact twice, differing only in capitalisation.
            reason = retrieval.unavailable_reason or ""
            if not reason or not any(reason in gap for gap in gaps):
                gaps.append(f"Retrieval is unavailable: {reason}")
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
        verdict = abstention_route(coverage, high_value)
        route, route_reason = verdict.route, verdict.reason
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
            "guardrails": [
                GuardrailDecision(
                    stage="output",
                    outcome="pass",
                    message="The typed degraded result contains no categorical outcome.",
                ),
                GuardrailDecision(
                    stage="routing",
                    outcome="review",
                    rule_ids=(f"ROUTE-{route.upper()}", *verdict.codes),
                    reason_codes=(f"route_{route}",),
                    message=route_reason,
                ),
            ],
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
        verdict = human_route(
            confidence=breakdown.confidence,
            coverage=bundle.coverage,
            verification=verification,
            conflict=state.get("conflict"),
            distribution=decision.distribution,
            outcome=decision.outcome,
            high_value=high_value,
            retrieval_gap=bool(bundle.retrieval.uncovered_sub_goals),
            intake=state.get("intake"),
            evidence_screen=_strict_verdict(state, "evidence"),
            budget=_verdict(state, "execution"),
        )
        band = verdict.route
        reason = verdict.reason
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
                "codes": list(verdict.codes),
                "confidence": breakdown.confidence,
                "high_value": high_value,
                "outcome": final.outcome,
            },
        )
        if band == "red":
            events.extend(_trace(state, "assign_route", "review_required", {"reason": reason}))
        routing_guardrail = GuardrailDecision(
            stage="routing",
            outcome="pass" if band == "green" else "review",
            # The rules that actually fired, not just the band they produced:
            # a reviewer asking "why is this red?" gets an answer they can look
            # up rather than a sentence they have to parse.
            rule_ids=(f"ROUTE-{band.upper()}", *verdict.codes),
            reason_codes=(f"route_{band}",),
            message=reason,
        )
        return {
            "final_result": final,
            "route": band,
            "guardrails": [routing_guardrail],
            "trace_summary": events,
        }

    def persist(self, state: ForecasterState) -> dict[str, Any]:
        """Record the decision, open a review case, and file any regression.

        Section 17.2 persists assessment snapshots; section 14.3 requires a
        review case when a run ends red; section 21.4 requires that an
        exhausted-retrieval failure or a failed verification becomes a versioned
        regression case. All three happen here, before any reviewer is asked
        anything, so a paused run has something concrete to show them.

        Application memory is optional, so a deployment without it still
        completes -- it simply has nothing to compare a later run against.
        """

        result = state.get("final_result")
        route = state.get("route")
        request = state["request"]
        store = self._runtime.store
        assessment_id: str | None = None
        case_id: str | None = None
        regression_ids: list[str] = []

        if store is not None and result is not None:
            if isinstance(result, InsufficientEvidenceDecision):
                outcome = "insufficient_evidence"
                confidence = 0.0
                summary = "; ".join(result.gaps)[:500]
                kind = "insufficient_evidence"
            else:
                outcome = result.outcome
                confidence = result.confidence
                summary = result.rationale[:500]
                kind = "forecast"
            record = store.record_assessment(
                account_id=result.account_id,
                cutoff=result.cutoff,
                predicted_outcome=outcome,
                confidence=confidence,
                decision=str(route),
                summary=summary,
                question=request.question,
                kind=kind,
                card=result.model_dump(mode="json"),
            )
            assessment_id = record.assessment_id
            if route == "red":
                intake = state.get("intake")
                routing = _verdict(state, "routing")
                reason_codes = tuple(
                    dict.fromkeys(
                        (
                            *(intake.reason_codes if intake is not None else ()),
                            *(routing.reason_codes if routing is not None else ()),
                        )
                    )
                )
                case_id = store.open_review_case(
                    record.assessment_id,
                    result.route_reason or "human review required",
                    route="red",
                    reason_codes=reason_codes,
                ).case_id
            for origin in self._regression_origins(state, result):
                if origin == "retrieval_exhausted":
                    reason_code = "coverage_insufficient"
                elif origin == "verification_failure":
                    reason_code = "evidence_contradicts_outcome"
                else:
                    reason_code = "policy_requires_human_action"
                regression_ids.append(
                    store.record_regression(
                        account_id=result.account_id,
                        origin=origin,
                        cutoff=result.cutoff,
                        question=request.question,
                        system_outcome=outcome,
                        reason_code=reason_code,
                        note=(
                            "; ".join(
                                error.message
                                for error in state.get("errors", [])
                                if error.category == "model"
                            )
                            if origin == "model_error"
                            else result.route_reason or origin
                        ),
                        confidence=confidence,
                        route=str(route),
                        case_id=case_id,
                        assessment_id=record.assessment_id,
                    ).regression_id
                )

        will_pause = bool(state.get("pause_on_red") and route == "red" and case_id)
        events = _trace(
            state,
            "persist",
            "decision_persisted",
            {
                "assessment_id": assessment_id,
                "review_case_id": case_id,
                "regression_ids": regression_ids,
                "persisted": assessment_id is not None,
            },
        )
        if not will_pause:
            events.extend(
                _trace(
                    state,
                    "persist",
                    "run_completed",
                    {
                        "route": route,
                        "abstained": result.is_abstention if result is not None else None,
                    },
                )
            )
        return {
            "assessment_id": assessment_id,
            "review_case_id": case_id,
            "review_state": "awaiting_review" if will_pause else state.get("review_state"),
            "trace_summary": events,
        }

    @staticmethod
    def _regression_origins(state: ForecasterState, result: Any) -> tuple[str, ...]:
        """Return why this run is worth keeping as a regression case (section 21.4).

        Section 21.4 names four sources, while Phase 7 also treats a configured
        model that fell back after an error as regression-worthy. Retrieval
        exhaustion, output verification failure, and model failure are visible
        inside a run. Reviewer overrides are filed when the reviewer acts, and
        guardrail false passes are filed by the offline safety evaluation.
        """

        origins: list[str] = []
        if (
            isinstance(result, InsufficientEvidenceDecision)
            and result.reason_code == "RETRIEVAL_EXHAUSTED"
        ):
            origins.append("retrieval_exhausted")
        verification = state.get("output_verification")
        if verification is not None and not verification.passed:
            origins.append("verification_failure")
        if any(error.category == "model" for error in state.get("errors", [])):
            origins.append("model_error")
        return tuple(origins)

    # -- Human review --------------------------------------------------------

    def await_review(self, state: ForecasterState) -> dict[str, Any]:
        """Pause the run and resume it with a typed reviewer decision (section 16.6).

        `interrupt` raises on the first pass and resumes inside this node with
        the review payload. Assessment and case persistence happen in the prior
        graph node and are checkpointed, so those writes are not replayed.

        The four actions of section 16.6 are applied here rather than in the
        API so that a resume and an asynchronous review converge on the same
        stored state: both end at `AssessmentStore.resolve_review_case`, which
        is the single place a regression record is written.
        """

        result = state.get("final_result")
        case_id = state.get("review_case_id")
        assert result is not None and case_id is not None

        forecast = result if isinstance(result, ForecastDecision) else None
        intake = state.get("intake")
        payload = ReviewInterrupt(
            case_id=case_id,
            run_id=state.get("run_id", "unknown"),
            thread_id=state.get("thread_id", "unknown"),
            account_id=result.account_id,
            cutoff=result.cutoff,
            route=state.get("route") or "red",
            route_reason=result.route_reason,
            proposed_outcome=forecast.outcome if forecast is not None else None,
            distribution=dict(forecast.distribution) if forecast is not None else {},
            confidence=forecast.confidence if forecast is not None else 0.0,
            gaps=result.gaps if isinstance(result, InsufficientEvidenceDecision) else (),
            reason_codes=intake.reason_codes if intake is not None else (),
        )

        answer = interrupt(payload.model_dump(mode="json"))
        decision = (
            answer
            if isinstance(answer, ReviewerDecision)
            else ReviewerDecision.model_validate(answer)
        )
        if decision.case_id != case_id:
            raise ValueError(
                f"reviewer decision names case {decision.case_id}, but this run paused on {case_id}"
            )

        store = self._runtime.store
        regression_id: str | None = None
        if store is not None:
            _, regression = store.resolve_review_case(decision)
            regression_id = regression.regression_id if regression is not None else None

        reviewed = self._apply_review(result, decision)
        return {
            "final_result": reviewed,
            "reviewer_decision": decision,
            "review_state": "reviewed",
            "trace_summary": [
                *_trace(
                    state,
                    "await_review",
                    "review_resumed",
                    {
                        "case_id": case_id,
                        "action": decision.action,
                        "reason_code": decision.reason_code,
                        "corrected_outcome": decision.corrected_outcome,
                        "regression_id": regression_id,
                    },
                ),
                *_trace(
                    state,
                    "await_review",
                    "run_completed",
                    {"route": reviewed.route, "abstained": reviewed.is_abstention},
                ),
            ],
        }

    @staticmethod
    def _apply_review(result: Any, decision: ReviewerDecision) -> Any:
        """Return the result as the reviewer left it (section 16.6).

        An approval and an escalation leave the answer alone and change only who
        owns it next, so both are recorded as limitations rather than as edits.
        An override and a data request do change what is released, and both are
        rewritten deterministically: the reviewer's outcome is *theirs*, so the
        model's rationale must not be left standing underneath it as though the
        system had reasoned its way there.
        """

        stamp = f"Reviewed by {decision.reviewer}: {decision.action} ({decision.reason_code})."
        note = f" Note: {decision.note}" if decision.note else ""
        limitation = f"{stamp}{note}"

        if decision.action in {"approve", "escalate"}:
            return result.model_copy(update={"limitations": (*result.limitations, limitation)})

        if decision.action == "request_data" or decision.corrected_outcome == (
            "insufficient_evidence"
        ):
            return InsufficientEvidenceDecision(
                account_id=result.account_id,
                cutoff=result.cutoff,
                verified_metrics=(
                    result.verified_metrics
                    if isinstance(result, InsufficientEvidenceDecision)
                    else ()
                ),
                gaps=(
                    *(result.gaps if isinstance(result, InsufficientEvidenceDecision) else ()),
                    f"A reviewer withdrew the released answer: {decision.reason_code}.",
                ),
                requested_data=decision.requested_data,
                citations=result.citations,
                limitations=(*result.limitations, limitation),
                recommended_action=(
                    "Supply the requested sources and re-run the assessment. "
                    "No categorical outcome is released."
                ),
                route="red",
                route_reason=f"withdrawn by {decision.reviewer}",
                reason_code="CRITICAL_DATA_GAP",
            )

        if isinstance(result, InsufficientEvidenceDecision):
            assert decision.corrected_outcome is not None
            return result.model_copy(
                update={
                    "limitations": (
                        *result.limitations,
                        limitation,
                        f"The reviewer recorded {decision.corrected_outcome} as a human "
                        "disposition; the system's evidence-based abstention is preserved.",
                    ),
                    "recommended_action": (
                        "Use the reviewer's disposition as human judgement. The system still "
                        "withholds its own categorical forecast on the available evidence."
                    ),
                    "route_reason": f"overridden by {decision.reviewer}",
                }
            )

        assert isinstance(result, ForecastDecision)
        assert decision.corrected_outcome is not None
        return result.model_copy(
            update={
                "outcome": decision.corrected_outcome,
                "rationale": (
                    f"A reviewer replaced the system's answer with "
                    f"{decision.corrected_outcome}. {decision.note}"
                )[:2_000],
                "recommended_action": (
                    "Act on the reviewer's outcome, not the system's. "
                    "The evidence and telemetry below are unchanged."
                ),
                "cited_doc_ids": (),
                "narrative_source": "deterministic",
                "limitations": (*result.limitations, limitation),
                "route": "red",
                "route_reason": f"overridden by {decision.reviewer}",
            }
        )


__all__ = ["STALE_EVIDENCE_DAYS", "GraphNodes", "combined_coverage"]
