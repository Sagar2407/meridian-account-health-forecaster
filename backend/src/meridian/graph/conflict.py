"""The deterministic conflict gate (plan section 15.1).

Eight triggers, each one a bullet from section 15.1, each a pure function of the
evidence bundle. None of them asks a model anything, which is the point: whether
a run costs four extra generations and a critic pass is a structural decision,
and section 14.1 forbids a model from making those.

Two rules in section 15.1 are relative -- "weak adoption", "above-median
adoption" -- so they need a portfolio baseline. When one is not available the
rule is skipped and says so, rather than comparing against zero and calling the
result a conflict.

The last line of section 15.1 is a rule in its own right: "Missing evidence
alone is not a ToT trigger." Every trigger here therefore requires evidence to
be *present* and to disagree. A run with nothing to disagree about degrades on
the coverage gate long before it reaches this module.
"""

from collections.abc import Callable
from dataclasses import dataclass

from meridian.contracts import (
    ADVERSE_OUTCOMES,
    Citation,
    ConflictAssessment,
    EvidenceBundle,
)
from meridian.features.baselines import PortfolioBaseline
from meridian.graph.confidence import TIE_MARGIN, top_two_margin

#: A citation must score at least this to count as high relevance, matching the
#: deterministic retrieval grader's floor so the two layers agree on what
#: "relevant" means.
HIGH_RELEVANCE_SCORE = 0.50

#: How many directional citations the qualitative side needs before its stance
#: can contradict the model's. One dissenting note is a data point; a stance is
#: what several of them make.
MIN_DIRECTIONAL_CITATIONS = 2

#: A positive adoption slope counts as improving usage. The slope is in adoption
#: index points per week, so zero is the honest threshold: anything above it is
#: growth the account did not have a quarter ago.
IMPROVING_TREND = 0.0

#: Sentiment runs from -1 to 1, so zero separates positive from negative.
POSITIVE_SENTIMENT = 0.0

#: Triggers that make a conflict severe on their own when combined with another.
_ESCALATING_RULE = "CONFLICT-NEAR-TIE"

SEVERE_TRIGGER_COUNT = 3
MODERATE_TRIGGER_COUNT = 2


@dataclass(frozen=True)
class ConflictSignal:
    """One trigger's verdict and the numbers behind it."""

    rule_id: str
    conflict_type: str
    fired: bool
    reason: str = ""
    skipped_reason: str = ""


def _metric(bundle: EvidenceBundle, name: str) -> float | None:
    """Return one verified metric value, or None when it was not computed."""

    observation = bundle.quantitative.metric(name)
    return observation.value if observation is not None else None


def _directional(citations: tuple[Citation, ...], signal: str) -> tuple[Citation, ...]:
    """Return citations carrying one structured signal."""

    return tuple(citation for citation in citations if citation.signal == signal)


def _qualitative_stance(bundle: EvidenceBundle) -> str:
    """Return what the retrieved evidence says, from its signals alone."""

    adverse = len(_directional(bundle.retrieval.citations, "adverse"))
    favorable = len(_directional(bundle.retrieval.citations, "favorable"))
    if adverse + favorable < MIN_DIRECTIONAL_CITATIONS:
        return "unclear"
    if adverse > favorable:
        return "adverse"
    if favorable > adverse:
        return "favorable"
    return "split"


def _band_versus_stance(bundle: EvidenceBundle, _: PortfolioBaseline | None) -> ConflictSignal:
    """Section 15.1: the risk band and the qualitative stance differ materially."""

    outcome = bundle.quantitative.predicted_outcome or ""
    model_stance = "adverse" if outcome in ADVERSE_OUTCOMES else "favorable"
    stance = _qualitative_stance(bundle)
    fired = stance in ("adverse", "favorable") and stance != model_stance
    return ConflictSignal(
        rule_id="CONFLICT-BAND-STANCE",
        conflict_type="model_versus_evidence",
        fired=fired,
        reason=(
            f"the model reads {model_stance} ({outcome}) while the retrieved evidence "
            f"reads {stance}"
            if fired
            else ""
        ),
    )


def _usage_versus_sponsor(bundle: EvidenceBundle, _: PortfolioBaseline | None) -> ConflictSignal:
    """Section 15.1: improving usage coexists with a lost sponsor."""

    trend = _metric(bundle, "adoption_trend_13w")
    lost = _metric(bundle, "sponsor_lost")
    if trend is None or lost is None:
        return ConflictSignal(
            rule_id="CONFLICT-USAGE-SPONSOR",
            conflict_type="usage_versus_relationship",
            fired=False,
            skipped_reason="adoption trend or sponsor status was not computed",
        )
    fired = trend > IMPROVING_TREND and lost >= 1.0
    return ConflictSignal(
        rule_id="CONFLICT-USAGE-SPONSOR",
        conflict_type="usage_versus_relationship",
        fired=fired,
        reason=f"adoption is rising ({trend:+.2f} per week) but the sponsor is lost"
        if fired
        else "",
    )


def _adoption_versus_good_news(
    bundle: EvidenceBundle, baseline: PortfolioBaseline | None
) -> ConflictSignal:
    """Section 15.1: weak adoption coexists with favourable external news."""

    level = _metric(bundle, "adoption_level_last_q")
    favorable = _metric(bundle, "favorable_events_2q")
    median = baseline.median("adoption_level_last_q") if baseline is not None else None
    if level is None or favorable is None or median is None:
        return ConflictSignal(
            rule_id="CONFLICT-ADOPTION-NEWS",
            conflict_type="adoption_versus_external",
            fired=False,
            skipped_reason="no portfolio adoption baseline was available",
        )
    fired = level < median and favorable >= 1.0
    return ConflictSignal(
        rule_id="CONFLICT-ADOPTION-NEWS",
        conflict_type="adoption_versus_external",
        fired=fired,
        reason=(
            f"adoption {level:.1f} is below the portfolio median {median:.1f} while "
            f"{favorable:.0f} favourable external event(s) landed"
            if fired
            else ""
        ),
    )


def _strength_versus_bad_news(
    bundle: EvidenceBundle, _: PortfolioBaseline | None
) -> ConflictSignal:
    """Section 15.1: strong usage and sentiment coexist with adverse events."""

    trend = _metric(bundle, "adoption_trend_13w")
    sentiment = _metric(bundle, "avg_ticket_sentiment_26w")
    adverse = _metric(bundle, "adverse_events_2q")
    if trend is None or sentiment is None or adverse is None:
        return ConflictSignal(
            rule_id="CONFLICT-STRENGTH-BAD-NEWS",
            conflict_type="strength_versus_external",
            fired=False,
            skipped_reason="adoption, sentiment, or external events were not computed",
        )
    fired = trend >= IMPROVING_TREND and sentiment > POSITIVE_SENTIMENT and adverse >= 1.0
    return ConflictSignal(
        rule_id="CONFLICT-STRENGTH-BAD-NEWS",
        conflict_type="strength_versus_external",
        fired=fired,
        reason=(
            f"usage is holding ({trend:+.2f} per week) with positive sentiment "
            f"({sentiment:+.2f}) against {adverse:.0f} adverse external event(s)"
            if fired
            else ""
        ),
    )


def _onboarding_versus_adoption(
    bundle: EvidenceBundle, baseline: PortfolioBaseline | None
) -> ConflictSignal:
    """Section 15.1: incomplete onboarding coexists with above-median adoption."""

    incomplete = _metric(bundle, "onboarding_incomplete")
    level = _metric(bundle, "adoption_level_last_q")
    median = baseline.median("adoption_level_last_q") if baseline is not None else None
    if incomplete is None or level is None or median is None:
        return ConflictSignal(
            rule_id="CONFLICT-ONBOARDING-ADOPTION",
            conflict_type="onboarding_versus_adoption",
            fired=False,
            skipped_reason="no portfolio adoption baseline was available",
        )
    fired = incomplete >= 1.0 and level > median
    return ConflictSignal(
        rule_id="CONFLICT-ONBOARDING-ADOPTION",
        conflict_type="onboarding_versus_adoption",
        fired=fired,
        reason=(
            f"onboarding never completed yet adoption {level:.1f} is above the "
            f"portfolio median {median:.1f}"
            if fired
            else ""
        ),
    )


def _near_tie(bundle: EvidenceBundle, _: PortfolioBaseline | None) -> ConflictSignal:
    """Section 15.1: the top two model outcome probabilities are within 0.10."""

    distribution = bundle.quantitative.distribution
    margin = top_two_margin(distribution)
    fired = bool(distribution) and margin < TIE_MARGIN
    return ConflictSignal(
        rule_id=_ESCALATING_RULE,
        conflict_type="model_uncertainty",
        fired=fired,
        reason=f"the top two outcomes are {margin:.3f} apart" if fired else "",
    )


def _passages_split(bundle: EvidenceBundle, _: PortfolioBaseline | None) -> ConflictSignal:
    """Section 15.1: high-relevance passages support different outcomes."""

    relevant = tuple(
        citation
        for citation in bundle.retrieval.citations
        if citation.retrieval_score >= HIGH_RELEVANCE_SCORE
    )
    adverse = _directional(relevant, "adverse")
    favorable = _directional(relevant, "favorable")
    fired = bool(adverse) and bool(favorable)
    return ConflictSignal(
        rule_id="CONFLICT-PASSAGE-SPLIT",
        conflict_type="evidence_versus_evidence",
        fired=fired,
        reason=(
            f"{len(adverse)} high-relevance passage(s) point adverse and "
            f"{len(favorable)} point favourable"
            if fired
            else ""
        ),
    )


def _both_sides_material(bundle: EvidenceBundle, _: PortfolioBaseline | None) -> ConflictSignal:
    """Section 15.1: supporting and counterevidence each hold a material item."""

    supporting = tuple(
        citation
        for citation in bundle.supporting
        if citation.retrieval_score >= HIGH_RELEVANCE_SCORE
    )
    against = tuple(
        citation
        for citation in bundle.counterevidence
        if citation.retrieval_score >= HIGH_RELEVANCE_SCORE
    )
    fired = bool(supporting) and bool(against)
    return ConflictSignal(
        rule_id="CONFLICT-BOTH-SIDES",
        conflict_type="evidence_versus_evidence",
        fired=fired,
        reason=(
            f"{len(supporting)} material supporting and {len(against)} material "
            "contradicting item(s) were verified"
            if fired
            else ""
        ),
    )


#: The eight triggers, in the order section 15.1 lists them.
CONFLICT_RULES: tuple[Callable[[EvidenceBundle, PortfolioBaseline | None], ConflictSignal], ...] = (
    _band_versus_stance,
    _usage_versus_sponsor,
    _adoption_versus_good_news,
    _strength_versus_bad_news,
    _onboarding_versus_adoption,
    _near_tie,
    _passages_split,
    _both_sides_material,
)


def severity_for(rule_ids: tuple[str, ...]) -> str:
    """Return how serious a set of fired triggers is.

    A near tie escalates: the model cannot separate the top two outcomes, so any
    second disagreement means nothing in the run distinguishes them either.
    """

    count = len(rule_ids)
    if count == 0:
        return "none"
    if count >= SEVERE_TRIGGER_COUNT or (_ESCALATING_RULE in rule_ids and count > 1):
        return "severe"
    if count == MODERATE_TRIGGER_COUNT:
        return "moderate"
    return "low"


def detect_conflict(
    bundle: EvidenceBundle, baseline: PortfolioBaseline | None = None
) -> ConflictAssessment:
    """Return whether the evidence materially disagrees (plan section 15.1).

    Args:
        bundle: The merged evidence for one run.
        baseline: Portfolio medians for the two relative rules. Without one
            those rules are skipped and recorded as skipped.

    Returns:
        An assessment naming every trigger that fired and why.
    """

    signals = [rule(bundle, baseline) for rule in CONFLICT_RULES]
    fired = [signal for signal in signals if signal.fired]
    skipped = [signal for signal in signals if signal.skipped_reason]

    rule_ids = tuple(signal.rule_id for signal in fired)
    reasons = [f"{signal.rule_id}: {signal.reason}" for signal in fired]
    reasons.extend(f"{signal.rule_id} skipped: {signal.skipped_reason}" for signal in skipped)

    return ConflictAssessment(
        triggered=bool(fired),
        evaluated=True,
        conflict_types=tuple(dict.fromkeys(signal.conflict_type for signal in fired)),
        rule_ids=rule_ids,
        reasons=tuple(reasons),
        severity=severity_for(rule_ids),
    )


__all__ = [
    "CONFLICT_RULES",
    "HIGH_RELEVANCE_SCORE",
    "MIN_DIRECTIONAL_CITATIONS",
    "ConflictSignal",
    "detect_conflict",
    "severity_for",
]
