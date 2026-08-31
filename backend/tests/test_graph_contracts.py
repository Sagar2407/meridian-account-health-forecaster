"""The shared contracts hold their invariants (plan section 9.1).

These models are where several of the system's safety properties are actually
enforced, so the tests are about what the models *refuse* rather than what they
store. The most important one is the first: an abstention has no outcome field
at all, which is what makes "never invents a categorical forecast" a property of
the type rather than a promise about the code.
"""

from datetime import date

import pytest
from pydantic import ValidationError

from meridian.contracts import (
    AssessmentRequest,
    Citation,
    ConfidenceBreakdown,
    CoverageReport,
    Driver,
    EvidenceBundle,
    ForecastDecision,
    InsufficientEvidenceDecision,
    MetricObservation,
    OutputVerification,
    QuantitativeEvidence,
    RequestedData,
    RetrievalEvidence,
    RetrievalObservation,
    SubGoal,
    TraceEvent,
)
from meridian.graph.state import keep_last
from meridian.graph.tracing import (
    MAX_TRACE_TEXT_CHARACTERS,
    TraceRecorder,
    ordered,
    redact,
    text_fingerprint,
)

CUTOFF = date(2026, 3, 1)


def _coverage(**overrides: object) -> CoverageReport:
    """Return a coverage report with sensible defaults."""

    defaults: dict[str, object] = {"expected_weeks": 13, "observed_weeks": 13}
    return CoverageReport(**{**defaults, **overrides})


def _quantitative(**overrides: object) -> QuantitativeEvidence:
    """Return a complete quantitative lane result."""

    defaults: dict[str, object] = {
        "account_id": "ACC-1042",
        "cutoff": CUTOFF,
        "distribution": {"Churned": 0.6, "Contracted": 0.2, "Renewed": 0.15, "Expanded": 0.05},
        "predicted_outcome": "Churned",
        "model_probability": 0.6,
        "coverage": _coverage(),
    }
    return QuantitativeEvidence(**{**defaults, **overrides})


def test_an_abstention_cannot_carry_an_outcome() -> None:
    """Plan section 4 item 10: a degraded run must not invent a label.

    The guarantee is structural. `InsufficientEvidenceDecision` has no outcome,
    distribution, or confidence field, so no code path can set one by accident.
    """

    decision = InsufficientEvidenceDecision(
        account_id="ACC-1042",
        cutoff=CUTOFF,
        gaps=("no telemetry",),
        recommended_action="Supply telemetry and re-run.",
    )
    assert decision.is_abstention is True
    for forbidden in ("outcome", "distribution", "confidence", "predicted_outcome"):
        assert forbidden not in InsufficientEvidenceDecision.model_fields
    with pytest.raises(ValidationError):
        InsufficientEvidenceDecision(
            account_id="ACC-1042",
            cutoff=CUTOFF,
            recommended_action="x",
            outcome="Churned",  # type: ignore[call-arg]
        )


def test_a_forecast_must_score_the_outcome_it_names() -> None:
    """A label the distribution does not contain is not a forecast."""

    with pytest.raises(ValidationError, match="absent from the distribution"):
        ForecastDecision(
            account_id="ACC-1042",
            cutoff=CUTOFF,
            outcome="Expanded",
            distribution={"Churned": 1.0},
            confidence=0.5,
            confidence_breakdown=ConfidenceBreakdown(
                calibrated_probability=0.5,
                coverage_score=0.5,
                agreement_score=0.5,
                raw_confidence=0.5,
                confidence=0.5,
            ),
            rationale="x",
            recommended_action="y",
        )


def test_a_distribution_that_does_not_sum_to_one_is_refused() -> None:
    """A four-class distribution is a probability distribution or it is nothing."""

    with pytest.raises(ValidationError, match="distribution sums to"):
        ForecastDecision(
            account_id="ACC-1042",
            cutoff=CUTOFF,
            outcome="Churned",
            distribution={"Churned": 0.6, "Renewed": 0.1},
            confidence=0.5,
            confidence_breakdown=ConfidenceBreakdown(
                calibrated_probability=0.5,
                coverage_score=0.5,
                agreement_score=0.5,
                raw_confidence=0.5,
                confidence=0.5,
            ),
            rationale="x",
            recommended_action="y",
        )


def test_an_unavailable_quantitative_lane_cannot_carry_a_prediction() -> None:
    """Section 13.2 forbids substituting an estimate for telemetry that failed."""

    with pytest.raises(ValidationError, match="must not carry a prediction"):
        _quantitative(available=False)

    degraded = QuantitativeEvidence(
        account_id="ACC-1042",
        cutoff=CUTOFF,
        coverage=_coverage(critical_gaps=("no usage telemetry",)),
        available=False,
    )
    assert degraded.predicted_outcome is None
    assert degraded.coverage.has_critical_gap


def test_a_request_with_an_injection_shape_is_refused_at_the_type() -> None:
    """The one free-text field a caller controls is checked before anything runs."""

    for hostile in (
        "renewal risk; rm -rf /",
        "read file:///etc/passwd",
        "risk $(cat /etc/passwd)",
        "SELECT * FROM renewal_outcomes",
    ):
        with pytest.raises(ValidationError):
            AssessmentRequest(account_id="ACC-1042", question=hostile)

    ordinary = AssessmentRequest(
        account_id="ACC-1042", question="Is adoption < 50% a renewal risk here?"
    )
    assert ordinary.mode == "interactive"


def test_a_sub_goal_query_is_checked_like_the_tool_argument_it_becomes() -> None:
    """A sub-goal is passed straight to retrieval, so it is validated as one."""

    with pytest.raises(ValidationError):
        SubGoal(kind="adoption", query="usage `whoami`", rationale="probe")
    plain = SubGoal(kind="adoption", query="usage decline", rationale="standard adoption evidence")
    assert plain.kind == "adoption"


def test_a_verification_says_what_failed_or_says_nothing() -> None:
    """A pass listing failures, or a failure listing none, would be unreadable."""

    with pytest.raises(ValidationError, match="must not list failures"):
        OutputVerification(passed=True, failures=("bad number",))
    with pytest.raises(ValidationError, match="must say what failed"):
        OutputVerification(passed=False)


def test_coverage_completeness_is_bounded_and_defined_at_zero() -> None:
    """A report with no expectation must not divide by it."""

    assert _coverage(expected_weeks=0, observed_weeks=0).week_completeness == 0.0
    assert _coverage(expected_weeks=13, observed_weeks=26).week_completeness == 1.0
    assert _coverage(expected_weeks=13, observed_weeks=6).week_completeness == pytest.approx(6 / 13)


def test_the_bundle_offers_every_group_of_evidence_for_citation() -> None:
    """Neutral evidence is citable too; dropping it would hide most of the corpus."""

    def _citation(doc_id: str, signal: str = "neutral") -> Citation:
        return Citation(
            doc_id=doc_id,
            parent_id=doc_id,
            source_type="csm_note",
            subtype="Monthly Touchpoint",
            account_id="ACC-1042",
            doc_date=date(2026, 1, 5),
            excerpt="text",
            retrieval_score=0.7,
            signal=signal,
        )

    bundle = EvidenceBundle(
        account_id="ACC-1042",
        cutoff=CUTOFF,
        quantitative=_quantitative(),
        retrieval=RetrievalEvidence(account_id="ACC-1042", cutoff=CUTOFF),
        coverage=_coverage(),
        supporting=(_citation("A", "adverse"),),
        counterevidence=(_citation("B", "favorable"),),
        context=(_citation("C"),),
        guidance=(_citation("KB-1"),),
    )
    assert bundle.cited_document_ids == {"A", "B", "C", "KB-1"}


def test_retrieval_evidence_reports_coverage_and_exhaustion() -> None:
    """The coverage gate branches on these, so they must not be derived twice."""

    covered = RetrievalObservation(
        sub_goal="adoption",
        query="adoption",
        citations=(
            Citation(
                doc_id="N-1",
                parent_id="N-1",
                source_type="csm_note",
                subtype="QBR",
                account_id="ACC-1042",
                doc_date=date(2026, 1, 1),
                excerpt="x",
                retrieval_score=0.8,
            ),
        ),
    )
    empty = RetrievalObservation(sub_goal="support", query="support", insufficient_evidence=True)
    evidence = RetrievalEvidence(
        account_id="ACC-1042", cutoff=CUTOFF, observations=(covered, empty)
    )
    assert evidence.covered_sub_goals == ("adoption",)
    assert evidence.uncovered_sub_goals == ("support",)
    assert evidence.exhausted is False
    assert RetrievalEvidence(account_id="ACC-1042", cutoff=CUTOFF).exhausted is True


def test_duplicate_documents_are_counted_once_across_sub_goals() -> None:
    """Two sub-goals that match the same note have not found two pieces of evidence."""

    citation = Citation(
        doc_id="N-1",
        parent_id="N-1",
        source_type="csm_note",
        subtype="QBR",
        account_id="ACC-1042",
        doc_date=date(2026, 1, 1),
        excerpt="x",
        retrieval_score=0.8,
    )
    evidence = RetrievalEvidence(
        account_id="ACC-1042",
        cutoff=CUTOFF,
        observations=(
            RetrievalObservation(sub_goal="adoption", query="a", citations=(citation,)),
            RetrievalObservation(sub_goal="support", query="b", citations=(citation,)),
        ),
    )
    assert len(evidence.citations) == 1


def test_a_trace_event_refuses_a_prompt_or_a_nested_object() -> None:
    """Section 21.3: a trace is published, so it cannot carry prompts or reasoning."""

    recorder = TraceRecorder("RUN-1", "T-1")
    for banned in ("prompt", "messages", "chain_of_thought", "api_key"):
        with pytest.raises(ValidationError, match="may not carry"):
            TraceEvent(
                run_id="RUN-1",
                thread_id="T-1",
                sequence=1,
                timestamp="now",
                node="n",
                event="e",
                payload={banned: "secret"},
            )
    with pytest.raises(ValidationError, match="not a safe scalar"):
        TraceEvent(
            run_id="RUN-1",
            thread_id="T-1",
            sequence=1,
            timestamp="now",
            node="n",
            event="e",
            payload={"nested": {"a": 1}},
        )
    # The recorder redacts first, so the same payload becomes safe rather than fatal.
    event = recorder.event("n", "run_started", {"prompt": "leak", "nested": {"a": 1}})
    assert "prompt" not in event.payload
    assert event.payload["redacted_keys"] == ["nested", "prompt"]


def test_arbitrary_user_text_is_truncated_and_fingerprinted() -> None:
    """Section 21.3 asks for hashing or truncation, so operators can correlate runs."""

    question = "why is this account at risk " * 40
    payload = redact({"question": question})
    assert len(str(payload["question"])) == MAX_TRACE_TEXT_CHARACTERS
    assert payload["question_digest"] == text_fingerprint(question)


def test_the_recorder_orders_events_and_counts_tokens() -> None:
    """A trace with no order is a bag of events."""

    recorder = TraceRecorder("RUN-1", "T-1")
    first = recorder.event("a", "run_started")
    second = recorder.event("b", "run_completed", prompt_tokens=10, completion_tokens=5)
    assert second.sequence > first.sequence
    assert ordered([second, first]) == (first, second)
    assert second.total_tokens == 15


def test_lists_that_replace_and_lists_that_accumulate_look_different() -> None:
    """Section 9.2 requires explicit reducers, including for replacement."""

    assert keep_last([1, 2], [3]) == [3]


def test_a_metric_observation_carries_the_code_version_that_made_it() -> None:
    """A metric whose definition moved is a different metric (section 9.1)."""

    observation = MetricObservation(
        name="adoption_trend_13w",
        value=-1.2,
        window="last 13 observed weeks",
        source="usage_weekly",
        coverage=13,
        calculation_version="features-1.0.0",
    )
    assert observation.calculation_version == "features-1.0.0"


def test_requested_data_and_drivers_are_hashable_records() -> None:
    """Both are de-duplicated by value while a decision is assembled."""

    request = RequestedData(source="usage_weekly", detail="telemetry", window="13 weeks")
    driver = Driver(
        feature="adoption_trend_13w", value=-1.0, contribution=-0.4, direction="opposes"
    )
    assert len({request, request}) == 1
    assert len({driver, driver}) == 1
