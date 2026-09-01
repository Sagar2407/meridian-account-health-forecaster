"""Evidence-aware confidence (plan section 16.1).

Section 16.1 opens with the rule that shapes this whole module: "Confidence must
not be a self-reported LLM number." Nothing here asks a model anything. Every
input is either a calibrated probability, a count of evidence the system
verified, or a boolean another deterministic check produced, and the breakdown
travels with the decision so a reviewer can recompute the score by hand.

The weights are the plan's recommended structure, unchanged. They are frozen
here rather than exposed as settings: section 16.1 requires them to be fixed
before held-out testing, and a weight an operator can move between two runs is
not a calibration, it is a dial.
"""

from meridian.contracts import (
    ConfidenceBreakdown,
    ConflictAssessment,
    CoverageReport,
    EvidenceBundle,
    OutputVerification,
)
from meridian.graph.thresholds import THRESHOLDS

# Every number below is re-exported from `meridian.graph.thresholds` rather
# than written here. One frozen, digested source means a held-out result can be
# tied to the exact thresholds that produced it (plan section 22.7); two copies
# would mean a change to one of them was undetectable.
CALIBRATED_WEIGHT = THRESHOLDS.calibrated_weight
COVERAGE_WEIGHT = THRESHOLDS.coverage_weight
AGREEMENT_WEIGHT = THRESHOLDS.agreement_weight

#: Coverage is three things a run can be short of, weighted by how much a
#: missing one distorts the answer: weeks of telemetry the model consumes
#: directly, sub-goals the plan asked for, and breadth across source families.
WEEK_COMPLETENESS_WEIGHT = 0.50
SUB_GOAL_COVERAGE_WEIGHT = 0.30
SOURCE_BREADTH_WEIGHT = 0.20

#: Agreement is what the evidence says against what the model predicted, and
#: whether the adjudicator was willing to release the label at all.
CITATION_AGREEMENT_WEIGHT = 0.60
ADJUDICATOR_AGREEMENT_WEIGHT = 0.40

#: With no directional evidence either way, agreement is unknown rather than
#: good. A neutral 0.5 says that; a 1.0 would reward silence.
NEUTRAL_AGREEMENT = 0.5

#: Hard caps from section 16.1.
CAP_CRITICAL_SOURCE_MISSING = THRESHOLDS.cap_critical_source_missing
CAP_UNRESOLVED_CONFLICT = THRESHOLDS.cap_unresolved_conflict
CAP_EXHAUSTED_RETRIEVAL_GAP = THRESHOLDS.cap_exhausted_retrieval_gap
CAP_REPAIRED_VERIFICATION = THRESHOLDS.cap_repaired_verification

#: Two outcomes this close are not distinguishable by this model on this
#: evidence, which section 16.5 treats as a red-route condition.
TIE_MARGIN = THRESHOLDS.tie_margin

#: The three account source families a broad answer draws on.
ACCOUNT_SOURCE_FAMILY_COUNT = 3


def top_two_margin(distribution: dict[str, float]) -> float:
    """Return the gap between the two most likely outcomes.

    Returns 1.0 for a distribution with fewer than two outcomes, since there is
    nothing for the top class to be confused with.
    """

    if len(distribution) < 2:
        return 1.0
    ranked = sorted(distribution.values(), reverse=True)
    return ranked[0] - ranked[1]


def coverage_score(coverage: CoverageReport, planned: int, covered: int, families: int) -> float:
    """Return how completely this run was evidenced, in [0, 1]."""

    sub_goal_ratio = (covered / planned) if planned > 0 else 0.0
    breadth = min(1.0, families / ACCOUNT_SOURCE_FAMILY_COUNT)
    score = (
        WEEK_COMPLETENESS_WEIGHT * coverage.week_completeness
        + SUB_GOAL_COVERAGE_WEIGHT * min(1.0, sub_goal_ratio)
        + SOURCE_BREADTH_WEIGHT * breadth
    )
    return max(0.0, min(1.0, score))


def agreement_score(bundle: EvidenceBundle, adjudicator_agrees: bool) -> float:
    """Return how far the evidence and the adjudicator back the model's call."""

    directional = len(bundle.supporting) + len(bundle.counterevidence)
    citations = len(bundle.supporting) / directional if directional > 0 else NEUTRAL_AGREEMENT
    return max(
        0.0,
        min(
            1.0,
            CITATION_AGREEMENT_WEIGHT * citations
            + ADJUDICATOR_AGREEMENT_WEIGHT * (1.0 if adjudicator_agrees else 0.0),
        ),
    )


def compute_confidence(
    bundle: EvidenceBundle,
    planned_sub_goals: int,
    adjudicator_agrees: bool,
    conflict: ConflictAssessment | None = None,
    verification: OutputVerification | None = None,
    retrieval_gap: bool = False,
) -> ConfidenceBreakdown:
    """Return the confidence for a decision, and the numbers behind it.

    Args:
        bundle: The evidence the decision was made from.
        planned_sub_goals: How many sub-goals the Orchestrator asked for.
        adjudicator_agrees: Whether the adjudicator judged the evidence to
            support releasing the model's label.
        conflict: The conflict gate's verdict, when one has run.
        verification: The output verification, when one has run. A verification
            that needed a regeneration caps confidence even after it passes.
        retrieval_gap: Whether a noncritical retrieval gap was left unfilled
            after the evidence budget was spent.

    Returns:
        The score and every input to it, so section 16.1's formula can be
        checked against the published decision.
    """

    quantitative = bundle.quantitative
    families = len({citation.source_type for citation in bundle.retrieval.citations})
    coverage = coverage_score(
        bundle.coverage,
        planned=planned_sub_goals,
        covered=len(bundle.retrieval.covered_sub_goals),
        families=families,
    )
    agreement = agreement_score(bundle, adjudicator_agrees)
    calibrated = quantitative.model_probability

    raw = CALIBRATED_WEIGHT * calibrated + COVERAGE_WEIGHT * coverage + AGREEMENT_WEIGHT * agreement
    raw = max(0.0, min(1.0, raw))

    confidence = raw
    caps: list[str] = []

    if bundle.coverage.has_critical_gap:
        confidence = min(confidence, CAP_CRITICAL_SOURCE_MISSING)
        caps.append("critical_source_missing")
    if conflict is not None and conflict.severity == "severe":
        confidence = min(confidence, CAP_UNRESOLVED_CONFLICT)
        caps.append("severe_unresolved_conflict")
    if top_two_margin(quantitative.distribution) < TIE_MARGIN:
        confidence = min(confidence, CAP_UNRESOLVED_CONFLICT)
        caps.append("persistent_tie")
    if retrieval_gap:
        confidence = min(confidence, CAP_EXHAUSTED_RETRIEVAL_GAP)
        caps.append("exhausted_noncritical_retrieval_gap")
    if verification is not None and verification.attempts > 1:
        confidence = min(confidence, CAP_REPAIRED_VERIFICATION)
        caps.append("repaired_output_verification")

    return ConfidenceBreakdown(
        calibrated_probability=round(calibrated, 6),
        coverage_score=round(coverage, 6),
        agreement_score=round(agreement, 6),
        raw_confidence=round(raw, 6),
        applied_caps=tuple(caps),
        confidence=round(confidence, 6),
    )


def apply_verification_cap(
    breakdown: ConfidenceBreakdown, verification: OutputVerification | None
) -> ConfidenceBreakdown:
    """Return the breakdown with the repaired-output cap applied.

    Output verification runs after the decision is drafted, so its cap cannot be
    applied when the score is first computed. Re-running the whole calculation
    at routing time would risk the two disagreeing; capping the score the
    adjudicator already published cannot.
    """

    if verification is None or verification.attempts <= 1:
        return breakdown
    capped = min(breakdown.confidence, CAP_REPAIRED_VERIFICATION)
    if capped == breakdown.confidence:
        return breakdown
    return breakdown.model_copy(
        update={
            "confidence": round(capped, 6),
            "applied_caps": (*breakdown.applied_caps, "repaired_output_verification"),
        }
    )


__all__ = [
    "AGREEMENT_WEIGHT",
    "CALIBRATED_WEIGHT",
    "CAP_CRITICAL_SOURCE_MISSING",
    "CAP_EXHAUSTED_RETRIEVAL_GAP",
    "CAP_REPAIRED_VERIFICATION",
    "CAP_UNRESOLVED_CONFLICT",
    "COVERAGE_WEIGHT",
    "TIE_MARGIN",
    "agreement_score",
    "apply_verification_cap",
    "compute_confidence",
    "coverage_score",
    "top_two_margin",
]
