"""Typed contracts shared by the agents, the guardrails, and the graph (plan section 9.1).

They live at the package root rather than inside `meridian.graph` because all
three layers depend on them and none of them owns them: an agent that had to
import the graph package to name its own return type would make the graph a
dependency of the agents it is built from.

Section 9 is blunt about this: "Create Pydantic models for every boundary. Do
not pass unstructured dictionaries between graph nodes." Every model the plan
names lives here, so a node signature says exactly what it consumes and what it
is allowed to produce.

Three properties are enforced by the models rather than left to the nodes:

* **An abstention cannot carry a label.** `InsufficientEvidenceDecision` has no
  outcome field at all, so the retrieval-exhaustion path is structurally unable
  to emit a categorical forecast (plan section 4, item 10).
* **A decision cannot be undated.** Every result carries the cutoff it was
  computed at, matching the tool layer's rule.
* **Confidence is a number the system computed, not one a model reported.**
  `ForecastDecision.confidence` arrives from `meridian.graph.confidence`, and
  its inputs travel with it so a reviewer can recompute it.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from meridian.tools.contracts import (
    ACCOUNT_ID_PATTERN,
    AccountId,
    EvidenceSignal,
    assert_safe_text,
)

#: Stable error codes for the API and the trace (plan section 19.3). They are
#: part of the contract: a caller may branch on them, so they do not change
#: wording when a message does.
ErrorCode = Literal[
    "ACCOUNT_NOT_FOUND",
    "REQUEST_BLOCKED",
    "CRITICAL_DATA_GAP",
    "MODEL_UNAVAILABLE",
    "INDEX_VERSION_MISMATCH",
    "RETRIEVAL_EXHAUSTED",
    "VERIFICATION_FAILED",
    "INTERNAL_ERROR",
]

#: Failure classes from plan section 14.3. The class decides the recovery, so
#: it is recorded rather than inferred from a message.
FailureCategory = Literal["validation", "transient_tool", "permanent_tool", "model", "policy"]

#: The six sub-goals an Orchestrator may choose from (plan section 13.1).
SubGoalKind = Literal[
    "adoption",
    "support",
    "relationship",
    "external_context",
    "renewal_history",
    "playbook_guidance",
]
SUB_GOAL_KINDS: tuple[SubGoalKind, ...] = (
    "adoption",
    "support",
    "relationship",
    "external_context",
    "renewal_history",
    "playbook_guidance",
)

MIN_SUB_GOALS = 2
MAX_SUB_GOALS = 4

#: Human-review bands (plan section 16.5). `blocked` is not a review queue item.
Route = Literal["green", "amber", "red", "blocked"]

#: The account-health outcomes the calibrated model distinguishes. Ordered so a
#: decision card can show them consistently.
OUTCOME_CLASSES: tuple[str, ...] = ("Churned", "Contracted", "Renewed", "Expanded")

#: Outcomes whose direction is adverse. Used to decide which citations support
#: a prediction and which contradict it.
ADVERSE_OUTCOMES: frozenset[str] = frozenset({"Churned", "Contracted"})

MAX_QUESTION_CHARACTERS = 500


class AssessmentRequest(BaseModel):
    """One request to assess an account (plan section 9.1).

    `requested_as_of` may only tighten the cutoff, exactly as in the tool layer.
    The question is free text and is therefore the one field an attacker
    controls, so it is checked for injection shapes here and again by the
    intake guardrail, which decides *meaning* rather than *shape*.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: AccountId
    question: str = Field(min_length=3, max_length=MAX_QUESTION_CHARACTERS)
    requested_as_of: date | None = None
    requester_role: Literal["csm", "cs_leader", "analyst", "system"] = "csm"
    mode: Literal["interactive", "portfolio_scan", "backtest"] = "interactive"

    @model_validator(mode="after")
    def question_must_be_plain_language(self) -> "AssessmentRequest":
        """Reject a question carrying a path, URL, shell, or SQL shape."""

        assert_safe_text(" ".join(self.question.split()), "question")
        return self


class SubGoal(BaseModel):
    """One typed evidence goal chosen by the Orchestrator (plan section 13.1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: SubGoalKind
    query: str = Field(min_length=3, max_length=200)
    rationale: str = Field(min_length=3, max_length=400)

    @model_validator(mode="after")
    def query_must_be_plain_language(self) -> "SubGoal":
        """A sub-goal becomes a retrieval argument, so it is checked like one."""

        assert_safe_text(" ".join(self.query.split()), "query")
        return self


class GuardrailDecision(BaseModel):
    """One guardrail verdict (plan section 9.1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["intake", "execution", "evidence", "output", "routing"]
    outcome: Literal["pass", "block", "review", "clarify"]
    rule_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    message: str = ""

    @property
    def allowed(self) -> bool:
        """Return whether the run may continue past this stage."""

        return self.outcome == "pass"


class CoverageReport(BaseModel):
    """How much evidence a run actually had (plan section 9.1).

    `critical_gaps` is the field the coverage gate branches on, so it is
    computed once and carried rather than re-derived at each decision.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    expected_weeks: int = Field(ge=0)
    observed_weeks: int = Field(ge=0)
    source_counts: dict[str, int] = Field(default_factory=dict)
    missing_sources: tuple[str, ...] = ()
    stale_sources: tuple[str, ...] = ()
    critical_gaps: tuple[str, ...] = ()

    @property
    def week_completeness(self) -> float:
        """Return observed weeks over expected weeks, capped at one."""

        if self.expected_weeks <= 0:
            return 0.0
        return min(1.0, self.observed_weeks / self.expected_weeks)

    @property
    def has_critical_gap(self) -> bool:
        """Return whether any gap is severe enough to forbid a forecast."""

        return bool(self.critical_gaps)


class MetricObservation(BaseModel):
    """One exact metric with its provenance (plan section 9.1).

    The calculation version is here so a stored assessment can be replayed
    against the code that produced it; a metric whose definition changed is a
    different metric.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    value: float
    window: str = Field(min_length=1)
    source: str = Field(min_length=1)
    coverage: int = Field(ge=0)
    calculation_version: str = Field(min_length=1)


class Driver(BaseModel):
    """One observable feature contribution behind a prediction.

    Contributions are associations the model relies on, not causal claims, and
    every surface that shows them must say so (plan section 10.5).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    feature: str = Field(min_length=1)
    value: float
    contribution: float
    direction: Literal["supports", "opposes"]
    description: str = ""


class Citation(BaseModel):
    """One verified evidence excerpt (plan section 9.1).

    `doc_id` and `parent_id` are the same identifier in this system: retrieval
    returns child chunks but cites the parent document, so the two names are
    kept for the plan's vocabulary rather than describing two different things.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: str = Field(min_length=1)
    parent_id: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    subtype: str = Field(min_length=1)
    account_id: str | None = Field(default=None, pattern=ACCOUNT_ID_PATTERN)
    doc_date: date | None = None
    excerpt: str = Field(min_length=1)
    retrieval_score: float
    signal: EvidenceSignal = "neutral"
    sub_goal: SubGoalKind | None = None

    @property
    def is_guidance(self) -> bool:
        """Return whether this is general knowledge rather than account evidence."""

        return self.account_id is None


class RetrievalObservation(BaseModel):
    """One sub-goal's retrieval attempt and what it produced (plan section 9.1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sub_goal: SubGoalKind
    query: str = Field(min_length=1)
    attempted_queries: tuple[str, ...] = ()
    citations: tuple[Citation, ...] = ()
    retry_count: int = Field(default=0, ge=0, le=1)
    source_coverage: dict[str, int] = Field(default_factory=dict)
    insufficient_evidence: bool = False
    insufficiency_reason: str | None = None
    rejected: tuple[str, ...] = ()

    @property
    def covered(self) -> bool:
        """Return whether this sub-goal produced usable evidence."""

        return bool(self.citations) and not self.insufficient_evidence


class QuantitativeEvidence(BaseModel):
    """The deterministic lane's output (plan section 13.2).

    There is no language model anywhere in its construction. If telemetry
    cannot be computed the lane reports a critical gap; it never substitutes an
    estimate.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: AccountId
    cutoff: date
    metrics: tuple[MetricObservation, ...] = ()
    distribution: dict[str, float] = Field(default_factory=dict)
    predicted_outcome: str | None = None
    model_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    model_name: str = ""
    drivers: tuple[Driver, ...] = ()
    coverage: CoverageReport
    available: bool = True

    @model_validator(mode="after")
    def an_unavailable_lane_carries_no_prediction(self) -> "QuantitativeEvidence":
        """A failed lane must not leave a stale label for the adjudicator to use."""

        if not self.available and (self.predicted_outcome is not None or self.distribution):
            raise ValueError("an unavailable quantitative lane must not carry a prediction")
        return self

    def metric(self, name: str) -> MetricObservation | None:
        """Return one metric observation by name, or None."""

        for observation in self.metrics:
            if observation.name == name:
                return observation
        return None


class RetrievalEvidence(BaseModel):
    """The retrieval lane's output (plan section 13.3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: AccountId
    cutoff: date
    observations: tuple[RetrievalObservation, ...] = ()
    guidance: tuple[Citation, ...] = ()
    rejected: tuple[str, ...] = ()
    available: bool = True
    unavailable_reason: str | None = None

    @property
    def citations(self) -> tuple[Citation, ...]:
        """Return every account citation across sub-goals, de-duplicated by document."""

        seen: dict[str, Citation] = {}
        for observation in self.observations:
            for citation in observation.citations:
                seen.setdefault(citation.doc_id, citation)
        return tuple(seen.values())

    @property
    def covered_sub_goals(self) -> tuple[SubGoalKind, ...]:
        """Return sub-goals that produced usable evidence."""

        return tuple(item.sub_goal for item in self.observations if item.covered)

    @property
    def uncovered_sub_goals(self) -> tuple[SubGoalKind, ...]:
        """Return sub-goals the retriever could not satisfy."""

        return tuple(item.sub_goal for item in self.observations if not item.covered)

    @property
    def exhausted(self) -> bool:
        """Return whether retrieval produced no account evidence at all.

        This is the condition the plan's instructor feedback addresses: the run
        must degrade to verified telemetry rather than forecasting blindly.
        """

        return not self.citations


class EvidenceBundle(BaseModel):
    """Everything the adjudicator is allowed to reason over (plan section 9.1).

    Supporting and counterevidence are split deterministically by comparing each
    citation's structured signal with the direction of the model's prediction.
    Nothing here reads free text to decide which side a citation is on.

    `context` holds the retrieved evidence that points neither way -- a routine
    how-to ticket, a monthly touchpoint note. It is not filler: it is most of
    what retrieval returns, and dropping it would hide the majority of the
    evidence from the adjudicator and from the reader of a decision card.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: AccountId
    cutoff: date
    quantitative: QuantitativeEvidence
    retrieval: RetrievalEvidence
    coverage: CoverageReport
    supporting: tuple[Citation, ...] = ()
    counterevidence: tuple[Citation, ...] = ()
    context: tuple[Citation, ...] = ()
    guidance: tuple[Citation, ...] = ()

    @property
    def cited_document_ids(self) -> frozenset[str]:
        """Return every document id the adjudicator may cite."""

        return frozenset(
            citation.doc_id
            for group in (self.supporting, self.counterevidence, self.context, self.guidance)
            for citation in group
        )


class ConflictAssessment(BaseModel):
    """Whether evidence materially disagrees (plan section 9.1).

    Phase 5 records that the gate ran and did not fire; the deterministic
    triggers of section 15.1 arrive in Phase 6. `evaluated` exists so a trace
    distinguishes "checked, no conflict" from "not checked", which a bare
    `triggered=False` cannot.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    triggered: bool = False
    evaluated: bool = True
    conflict_types: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    severity: Literal["none", "low", "moderate", "severe"] = "none"


class CandidateHypothesis(BaseModel):
    """One branch of the bounded Tree-of-Thought search (plan section 9.1).

    Defined here with the rest of section 9.1 so the shared state can name it,
    and because the state's `candidates` field would otherwise be untyped. The
    conflict subgraph that produces these arrives in Phase 6; nothing in the
    fast path writes one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: str = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=800)
    supporting_citation_ids: tuple[str, ...] = ()
    counterevidence_citation_ids: tuple[str, ...] = ()
    hard_check_passed: bool = True
    hard_check_failures: tuple[str, ...] = ()
    soft_scores: dict[str, float] = Field(default_factory=dict)


class ConfidenceBreakdown(BaseModel):
    """The inputs to a confidence score, so it can be recomputed (section 16.1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    calibrated_probability: float = Field(ge=0.0, le=1.0)
    coverage_score: float = Field(ge=0.0, le=1.0)
    agreement_score: float = Field(ge=0.0, le=1.0)
    raw_confidence: float = Field(ge=0.0, le=1.0)
    applied_caps: tuple[str, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)


class OutputVerification(BaseModel):
    """The result of replaying a draft decision against verified evidence.

    Section 16.4 requires numeric claims to be replayed against tool output and
    citation ownership and dates to be checked. `attempts` bounds regeneration
    at the one the plan allows (section 14.2).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    passed: bool
    attempts: int = Field(default=1, ge=1)
    checked_numeric_claims: int = Field(default=0, ge=0)
    checked_citations: int = Field(default=0, ge=0)
    failures: tuple[str, ...] = ()

    @model_validator(mode="after")
    def a_pass_has_no_failures(self) -> "OutputVerification":
        """A verification that passed while listing failures would be unreadable."""

        if self.passed and self.failures:
            raise ValueError("a passing verification must not list failures")
        if not self.passed and not self.failures:
            raise ValueError("a failing verification must say what failed")
        return self


class ForecastDecision(BaseModel):
    """A grounded advisory forecast (plan sections 9.1 and 16.4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: AccountId
    cutoff: date
    outcome: str = Field(min_length=1)
    distribution: dict[str, float]
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_breakdown: ConfidenceBreakdown
    rationale: str = Field(min_length=1, max_length=2_000)
    drivers: tuple[Driver, ...] = ()
    citations: tuple[Citation, ...] = ()
    counterevidence: tuple[Citation, ...] = ()
    #: The documents the rationale actually references, as the narrative claimed
    #: them. Kept separate from `citations`, which is the whole evidence set the
    #: decision card shows: output verification has to check what was *claimed*
    #: against what was retrieved, and checking the retrieved set against itself
    #: would always pass.
    cited_doc_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    recommended_action: str = Field(min_length=1, max_length=600)
    route: Route = "amber"
    route_reason: str = ""
    narrative_source: Literal["model", "deterministic"] = "deterministic"
    model_name: str = ""

    @model_validator(mode="after")
    def the_outcome_must_be_in_the_distribution(self) -> "ForecastDecision":
        """A label the distribution does not score is not a forecast."""

        if self.outcome not in self.distribution:
            raise ValueError(f"outcome {self.outcome!r} is absent from the distribution")
        total = sum(self.distribution.values())
        if not 0.98 <= total <= 1.02:
            raise ValueError(f"distribution sums to {total:.4f}, not 1")
        return self

    @property
    def is_abstention(self) -> bool:
        """Return whether this result withholds a categorical label."""

        return False


class RequestedData(BaseModel):
    """One specific thing a human could supply to unblock a run.

    The instructor feedback asks for a *targeted* data request rather than a
    general complaint, so each item names the source and the window.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(min_length=1)
    detail: str = Field(min_length=1, max_length=300)
    window: str = ""


class InsufficientEvidenceDecision(BaseModel):
    """A degraded, verified-telemetry-only result (plan sections 9.1 and 16.5).

    There is deliberately no outcome, distribution, or confidence field. The
    plan's definition of done requires that an exhausted-retrieval run "does not
    invent a categorical forecast", and the way to guarantee that is to make the
    label unrepresentable rather than to remember not to fill it in.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: AccountId
    cutoff: date
    verified_metrics: tuple[MetricObservation, ...] = ()
    gaps: tuple[str, ...] = ()
    requested_data: tuple[RequestedData, ...] = ()
    citations: tuple[Citation, ...] = ()
    limitations: tuple[str, ...] = ()
    recommended_action: str = Field(min_length=1, max_length=600)
    route: Route = "amber"
    route_reason: str = ""
    reason_code: ErrorCode = "CRITICAL_DATA_GAP"

    @property
    def is_abstention(self) -> bool:
        """Return whether this result withholds a categorical label."""

        return True


class NodeError(BaseModel):
    """One classified failure inside the graph (plan section 14.3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    node: str = Field(min_length=1)
    category: FailureCategory
    code: ErrorCode
    message: str = Field(max_length=500)
    recoverable: bool = False


#: Payload keys a trace may never carry (plan section 21.3). Prompts and raw
#: model replies are excluded because a trace is shown to users and stored; the
#: system's own reasoning is not evidence and publishing it teaches readers to
#: trust narration over verified numbers.
FORBIDDEN_TRACE_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "authorization",
        "chain_of_thought",
        "completion",
        "credentials",
        "instructions",
        "messages",
        "password",
        "prompt",
        "raw_response",
        "reasoning",
        "secret",
        "system_prompt",
        "token",
    }
)


class TraceEvent(BaseModel):
    """One safe, structured trace record (plan sections 9.1, 19.2, and 21.1).

    The payload is deliberately typed as scalars and small collections. Nothing
    here may carry a prompt, a raw model reply, or private reasoning; section
    21.3 forbids it and `meridian.graph.tracing` enforces it on the way in.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    timestamp: str = Field(min_length=1)
    node: str = Field(min_length=1)
    event: str = Field(min_length=1)
    payload: dict[str, object] = Field(default_factory=dict)
    latency_ms: float = Field(default=0.0, ge=0.0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def the_payload_must_be_safe_to_publish(self) -> "TraceEvent":
        """Refuse a payload carrying a prompt, a model reply, or a nested object.

        `meridian.graph.tracing` redacts on the way in, but a node could build a
        `TraceEvent` directly. Section 21.3 is a safety rule, not a convention,
        so it is checked where the object is constructed rather than only where
        it is usually constructed.
        """

        banned = sorted(set(self.payload) & FORBIDDEN_TRACE_KEYS)
        if banned:
            raise ValueError(f"trace payload may not carry {banned}")
        for key, value in self.payload.items():
            if isinstance(value, str | int | float | bool | type(None)):
                continue
            if isinstance(value, list | tuple) and all(
                isinstance(item, str | int | float | bool) for item in value
            ):
                continue
            raise ValueError(f"trace payload field {key!r} is not a safe scalar or list")
        return self

    @property
    def total_tokens(self) -> int:
        """Return the tokens billed for this event."""

        return self.prompt_tokens + self.completion_tokens


#: Every result type the graph may finish with.
FinalResult = ForecastDecision | InsufficientEvidenceDecision


class BlockedDecision(BaseModel):
    """A safe refusal (plan section 16.5, the `blocked` band).

    A block is not a review-queue item and carries no telemetry: answering a
    blocked request with partial data would defeat the block.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: AccountId
    message: str = Field(min_length=1, max_length=600)
    rule_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    route: Literal["blocked"] = "blocked"
    reason_code: ErrorCode = "REQUEST_BLOCKED"


__all__ = [
    "ADVERSE_OUTCOMES",
    "FORBIDDEN_TRACE_KEYS",
    "MAX_SUB_GOALS",
    "MIN_SUB_GOALS",
    "OUTCOME_CLASSES",
    "SUB_GOAL_KINDS",
    "AssessmentRequest",
    "BlockedDecision",
    "CandidateHypothesis",
    "Citation",
    "ConfidenceBreakdown",
    "ConflictAssessment",
    "CoverageReport",
    "Driver",
    "ErrorCode",
    "EvidenceBundle",
    "EvidenceSignal",
    "FailureCategory",
    "FinalResult",
    "ForecastDecision",
    "GuardrailDecision",
    "InsufficientEvidenceDecision",
    "MetricObservation",
    "NodeError",
    "OutputVerification",
    "QuantitativeEvidence",
    "RequestedData",
    "RetrievalEvidence",
    "RetrievalObservation",
    "Route",
    "SubGoal",
    "SubGoalKind",
    "TraceEvent",
]
