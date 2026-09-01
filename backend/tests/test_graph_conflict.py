"""The deterministic conflict gate (plan section 15.1).

Eight triggers, one test each, plus the rule the plan states last and that
matters most: "Missing evidence alone is not a ToT trigger." A gate that fired
on silence would send every thinly-evidenced account into a search that costs
four generations and has nothing to weigh.

Everything here builds its own evidence bundle, so each rule is exercised on the
exact combination it is meant to catch rather than on whichever account happened
to have that shape.
"""

from datetime import date

import pytest

from meridian.contracts import (
    Citation,
    ConflictAssessment,
    CoverageReport,
    Driver,
    EvidenceBundle,
    MetricObservation,
    QuantitativeEvidence,
    RetrievalEvidence,
    RetrievalObservation,
)
from meridian.data.repository import RuntimeRepository
from meridian.features.baselines import BaselineProvider, PortfolioBaseline
from meridian.graph.conflict import (
    CONFLICT_RULES,
    HIGH_RELEVANCE_SCORE,
    detect_conflict,
    severity_for,
)

CUTOFF = date(2026, 3, 1)
CLEAR = {"Churned": 0.70, "Contracted": 0.12, "Renewed": 0.13, "Expanded": 0.05}
TIED = {"Churned": 0.38, "Contracted": 0.34, "Renewed": 0.18, "Expanded": 0.10}
BASELINE = PortfolioBaseline(
    medians={"adoption_level_last_q": 50.0, "adoption_trend_13w": 0.0}, accounts_measured=260
)

METRIC_DEFAULTS: dict[str, float] = {
    "adoption_trend_13w": -0.5,
    "adoption_level_last_q": 40.0,
    "sponsor_lost": 0.0,
    "onboarding_incomplete": 0.0,
    "favorable_events_2q": 0.0,
    "adverse_events_2q": 0.0,
    "avg_ticket_sentiment_26w": -0.2,
}


def _citation(doc_id: str, signal: str, score: float = 0.8) -> Citation:
    return Citation(
        doc_id=doc_id,
        parent_id=doc_id,
        source_type="support_ticket",
        subtype="Escalation",
        account_id="ACC-1042",
        doc_date=date(2026, 1, 1),
        excerpt="text",
        retrieval_score=score,
        signal=signal,
    )


def _bundle(
    metrics: dict[str, float] | None = None,
    distribution: dict[str, float] | None = None,
    outcome: str = "Churned",
    citations: tuple[Citation, ...] = (),
) -> EvidenceBundle:
    """Return a bundle with the metrics and evidence a rule needs."""

    values = {**METRIC_DEFAULTS, **(metrics or {})}
    quantitative = QuantitativeEvidence(
        account_id="ACC-1042",
        cutoff=CUTOFF,
        metrics=tuple(
            MetricObservation(
                name=name,
                value=value,
                window="window",
                source="source",
                coverage=13,
                calculation_version="features-1.0.0",
            )
            for name, value in values.items()
        ),
        distribution=distribution or dict(CLEAR),
        predicted_outcome=outcome,
        model_probability=max((distribution or CLEAR).values()),
        drivers=(
            Driver(
                feature="adoption_trend_13w",
                value=values["adoption_trend_13w"],
                contribution=-0.4,
                direction="supports",
            ),
        ),
        coverage=CoverageReport(expected_weeks=13, observed_weeks=13),
    )
    retrieval = RetrievalEvidence(
        account_id="ACC-1042",
        cutoff=CUTOFF,
        observations=(
            RetrievalObservation(sub_goal="support", query="support", citations=citations),
        ),
    )
    adverse_outcome = outcome in {"Churned", "Contracted"}
    supporting = tuple(
        item
        for item in citations
        if item.signal != "neutral" and (item.signal == "adverse") == adverse_outcome
    )
    against = tuple(
        item
        for item in citations
        if item.signal != "neutral" and (item.signal == "adverse") != adverse_outcome
    )
    return EvidenceBundle(
        account_id="ACC-1042",
        cutoff=CUTOFF,
        quantitative=quantitative,
        retrieval=retrieval,
        coverage=quantitative.coverage,
        supporting=supporting,
        counterevidence=against,
        context=tuple(item for item in citations if item.signal == "neutral"),
    )


def _fired(assessment: ConflictAssessment) -> set[str]:
    """Return the rule ids that fired."""

    return set(assessment.rule_ids)


def test_aligned_evidence_produces_no_conflict() -> None:
    """The gate must not fire on a run where everything points one way."""

    bundle = _bundle(citations=(_citation("A", "adverse"), _citation("B", "adverse")))
    assessment = detect_conflict(bundle, BASELINE)
    assert assessment.triggered is False
    assert assessment.evaluated is True
    assert assessment.severity == "none"
    assert assessment.rule_ids == ()


def test_missing_evidence_alone_is_not_a_trigger() -> None:
    """Section 15.1's closing rule, and the one most easily broken by accident.

    A run with no qualitative evidence has nothing to disagree about. It should
    reach the coverage gate's degraded path, not a four-branch search over
    silence.
    """

    bundle = _bundle(citations=())
    assessment = detect_conflict(bundle, BASELINE)
    assert assessment.triggered is False
    assert assessment.rule_ids == ()


def test_the_model_and_the_evidence_disagreeing_is_a_conflict() -> None:
    """Section 15.1: the risk band and the qualitative stance differ materially."""

    bundle = _bundle(
        outcome="Churned",
        citations=(_citation("A", "favorable"), _citation("B", "favorable")),
    )
    assessment = detect_conflict(bundle, BASELINE)
    assert "CONFLICT-BAND-STANCE" in _fired(assessment)
    assert any("reads adverse" in reason for reason in assessment.reasons)


def test_one_dissenting_document_is_not_a_stance() -> None:
    """A single note pointing the other way is a data point, not a disagreement."""

    bundle = _bundle(outcome="Churned", citations=(_citation("A", "favorable"),))
    assert "CONFLICT-BAND-STANCE" not in _fired(detect_conflict(bundle, BASELINE))


def test_rising_usage_with_a_lost_sponsor_is_a_conflict() -> None:
    """Section 15.1: improving usage coexists with a lost sponsor."""

    bundle = _bundle({"adoption_trend_13w": 1.4, "sponsor_lost": 1.0})
    assessment = detect_conflict(bundle, BASELINE)
    assert "CONFLICT-USAGE-SPONSOR" in _fired(assessment)
    assert any("sponsor is lost" in reason for reason in assessment.reasons)


def test_weak_adoption_with_good_news_is_a_conflict() -> None:
    """Section 15.1: weak adoption coexists with favourable external news."""

    bundle = _bundle({"adoption_level_last_q": 20.0, "favorable_events_2q": 2.0})
    assert "CONFLICT-ADOPTION-NEWS" in _fired(detect_conflict(bundle, BASELINE))


def test_strong_usage_and_sentiment_with_bad_news_is_a_conflict() -> None:
    """Section 15.1: strong usage and sentiment coexist with adverse events."""

    bundle = _bundle(
        {
            "adoption_trend_13w": 0.6,
            "avg_ticket_sentiment_26w": 0.4,
            "adverse_events_2q": 1.0,
        }
    )
    assert "CONFLICT-STRENGTH-BAD-NEWS" in _fired(detect_conflict(bundle, BASELINE))


def test_unfinished_onboarding_with_high_adoption_is_a_conflict() -> None:
    """Section 15.1: incomplete onboarding coexists with above-median adoption."""

    bundle = _bundle({"onboarding_incomplete": 1.0, "adoption_level_last_q": 80.0})
    assessment = detect_conflict(bundle, BASELINE)
    assert "CONFLICT-ONBOARDING-ADOPTION" in _fired(assessment)
    assert any("portfolio median 50.0" in reason for reason in assessment.reasons)


def test_a_near_tie_in_the_distribution_is_a_conflict() -> None:
    """Section 15.1: the top two model outcome probabilities are within 0.10."""

    bundle = _bundle(distribution=dict(TIED))
    assert "CONFLICT-NEAR-TIE" in _fired(detect_conflict(bundle, BASELINE))


def test_high_relevance_passages_pointing_both_ways_is_a_conflict() -> None:
    """Section 15.1: high-relevance passages support different outcomes."""

    bundle = _bundle(
        citations=(
            _citation("A", "adverse", HIGH_RELEVANCE_SCORE + 0.1),
            _citation("B", "favorable", HIGH_RELEVANCE_SCORE + 0.1),
        )
    )
    assert "CONFLICT-PASSAGE-SPLIT" in _fired(detect_conflict(bundle, BASELINE))


def test_low_relevance_passages_pointing_both_ways_are_not_a_conflict() -> None:
    """Weakly matched passages disagreeing is noise, not a material conflict."""

    bundle = _bundle(
        citations=(
            _citation("A", "adverse", HIGH_RELEVANCE_SCORE - 0.2),
            _citation("B", "favorable", HIGH_RELEVANCE_SCORE - 0.2),
        )
    )
    assert "CONFLICT-PASSAGE-SPLIT" not in _fired(detect_conflict(bundle, BASELINE))


def test_material_evidence_on_both_sides_is_a_conflict() -> None:
    """Section 15.1: supporting and counterevidence each hold a material item."""

    bundle = _bundle(citations=(_citation("A", "adverse", 0.9), _citation("B", "favorable", 0.9)))
    assert "CONFLICT-BOTH-SIDES" in _fired(detect_conflict(bundle, BASELINE))


def test_a_relative_rule_is_skipped_rather_than_guessed_without_a_baseline() -> None:
    """Comparing against a default zero would call every account above median."""

    bundle = _bundle({"onboarding_incomplete": 1.0, "adoption_level_last_q": 80.0})
    assessment = detect_conflict(bundle, None)
    assert "CONFLICT-ONBOARDING-ADOPTION" not in _fired(assessment)
    assert any("skipped" in reason for reason in assessment.reasons)


def test_a_missing_metric_skips_its_rule_rather_than_firing() -> None:
    """A rule that needs a metric the run never computed must not decide."""

    bundle = _bundle()
    stripped = bundle.model_copy(
        update={
            "quantitative": bundle.quantitative.model_copy(
                update={
                    "metrics": tuple(
                        item for item in bundle.quantitative.metrics if item.name != "sponsor_lost"
                    )
                }
            )
        }
    )
    assessment = detect_conflict(stripped, BASELINE)
    assert "CONFLICT-USAGE-SPONSOR" not in _fired(assessment)
    assert any("CONFLICT-USAGE-SPONSOR skipped" in reason for reason in assessment.reasons)


@pytest.mark.parametrize(
    ("rule_ids", "expected"),
    [
        ((), "none"),
        (("CONFLICT-BAND-STANCE",), "low"),
        (("CONFLICT-BAND-STANCE", "CONFLICT-BOTH-SIDES"), "moderate"),
        (("CONFLICT-BAND-STANCE", "CONFLICT-BOTH-SIDES", "CONFLICT-PASSAGE-SPLIT"), "severe"),
        (("CONFLICT-NEAR-TIE", "CONFLICT-BAND-STANCE"), "severe"),
        (("CONFLICT-NEAR-TIE",), "low"),
    ],
)
def test_severity_escalates_with_the_triggers_that_fired(
    rule_ids: tuple[str, ...], expected: str
) -> None:
    """A near tie escalates: nothing left in the run separates the top two."""

    assert severity_for(rule_ids) == expected


def test_a_resolved_severe_conflict_is_not_an_unresolved_one() -> None:
    """Section 16.5 routes an *unresolved* severe conflict to red."""

    bundle = _bundle(
        distribution=dict(TIED),
        citations=(_citation("A", "adverse", 0.9), _citation("B", "favorable", 0.9)),
    )
    assessment = detect_conflict(bundle, BASELINE)
    assert assessment.severity == "severe"
    assert assessment.unresolved_severe is True
    assert assessment.model_copy(update={"resolved": True}).unresolved_severe is False


def test_every_rule_reports_a_reason_when_it_fires() -> None:
    """A trigger with no explanation cannot be reviewed or regression-tested."""

    bundle = _bundle(
        {
            "adoption_trend_13w": 1.0,
            "sponsor_lost": 1.0,
            "onboarding_incomplete": 1.0,
            "adoption_level_last_q": 80.0,
            "favorable_events_2q": 1.0,
            "adverse_events_2q": 1.0,
            "avg_ticket_sentiment_26w": 0.5,
        },
        distribution=dict(TIED),
        citations=(_citation("A", "adverse", 0.9), _citation("B", "favorable", 0.9)),
    )
    assessment = detect_conflict(bundle, BASELINE)
    assert len(assessment.rule_ids) >= 5
    for rule_id in assessment.rule_ids:
        assert any(reason.startswith(f"{rule_id}: ") for reason in assessment.reasons)
    assert assessment.conflict_types


def test_the_rule_table_has_no_duplicates() -> None:
    """Eight bullets in section 15.1, eight rules, each with its own identifier."""

    bundle = _bundle()
    ids = [rule(bundle, BASELINE).rule_id for rule in CONFLICT_RULES]
    assert len(ids) == len(set(ids)) == len(CONFLICT_RULES) == 8


def test_the_baseline_provider_measures_once() -> None:
    """The sweep costs seconds, so it must not run per assessment."""

    calls: list[int] = []

    def _factory() -> PortfolioBaseline:
        calls.append(1)
        return BASELINE

    provider = BaselineProvider(_factory)
    assert provider.measured is False
    assert provider.get() is BASELINE
    assert provider.get() is BASELINE
    assert provider.measured is True
    assert len(calls) == 1


def test_a_baseline_returns_none_for_a_feature_it_never_measured() -> None:
    """A rule must skip rather than compare against a default."""

    assert BASELINE.median("adoption_level_last_q") == 50.0
    assert BASELINE.median("never_measured") is None


@pytest.mark.requires_dataset
def test_the_portfolio_baseline_is_measured_from_observable_features(
    runtime: RuntimeRepository,
) -> None:
    """The medians come from the runtime repository, which holds no labels."""

    from meridian.features.baselines import BASELINE_FEATURES

    baseline = PortfolioBaseline.from_repository(runtime)
    assert baseline.accounts_measured == len(runtime.account_ids())
    assert set(baseline.medians) == set(BASELINE_FEATURES)
    assert baseline.dataset_version and baseline.calculation_version
