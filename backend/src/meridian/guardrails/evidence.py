"""Evidence guardrails (plan section 16.3, applied where evidence enters a decision).

Section 16.3 lists five rules about evidence: account, as-of-date, recency, and
role filters; exact numeric provenance; and citation metadata preservation. The
retrieval layer already enforces the first of those at ranking time, and output
verification re-checks the two that survive into the narrative. This module is
the checkpoint between them -- the fan-in, where every lane's output becomes one
bundle the adjudicator will reason over.

That is not duplication. Retrieval enforces the rule *for the path it controls*;
this enforces it for the bundle whatever produced it, so a citation introduced
by a future path, a cached index, or a bug is caught by the same control. The
Phase 7 exit gate is about false passes, and a control that only guards one
producer cannot speak to that.

Violations are quarantined rather than raised. A run that drops one poisoned
citation and says so is more useful than a run that dies, and the dropped
citation still forces the answer to a human: `screen_evidence` returns a
`review` verdict, and `human_route` treats a failed evidence screen as red.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from meridian.agents.forecast_adjudicator import PROSE_SAFE_FIELD_NAMES
from meridian.contracts import (
    Citation,
    GuardrailDecision,
    MetricObservation,
    QuantitativeEvidence,
    RetrievalEvidence,
)
from meridian.retrieval.documents import forbidden_field_mentions

#: One rule id per section 16.3 clause this stage is responsible for.
EVIDENCE_RULE_IDS: tuple[str, ...] = (
    "EVID-ACCOUNT",
    "EVID-CUTOFF",
    "EVID-UNDATED",
    "EVID-SOURCE",
    "EVID-LEAK",
    "EVID-PROVENANCE",
    "EVID-ENVELOPE",
)


@dataclass(frozen=True)
class EvidenceScreening:
    """What survived the screen, and what did not."""

    citations: tuple[Citation, ...]
    guidance: tuple[Citation, ...]
    metrics: tuple[MetricObservation, ...]
    rejected: tuple[str, ...]
    rule_ids: tuple[str, ...]
    quantitative_valid: bool
    retrieval_valid: bool
    decision: GuardrailDecision

    @property
    def clean(self) -> bool:
        """Return whether every piece of evidence passed."""

        return not self.rejected


def citation_violation(
    citation: Citation,
    account_id: str,
    cutoff: date,
    lane: Literal["account", "guidance"] = "account",
) -> tuple[str, str] | None:
    """Return the rule this citation breaks and why, or None if it is sound.

    Guidance -- a knowledge-base article, which by contract has no account and
    no date -- is scoped by its own rule: it must carry neither. An article that
    somehow arrived with an account id is not guidance, and is refused.
    """

    if lane == "guidance":
        if citation.source_type != "knowledge_base":
            return (
                "EVID-SOURCE",
                f"{citation.doc_id}: {citation.source_type} cannot enter the guidance lane",
            )
        if citation.account_id is not None:
            return (
                "EVID-ACCOUNT",
                f"{citation.doc_id}: knowledge guidance unexpectedly belongs to "
                f"{citation.account_id}",
            )
        if citation.doc_date is not None and citation.doc_date > cutoff:
            return "EVID-CUTOFF", f"{citation.doc_id}: guidance dated after the cutoff {cutoff}"
    else:
        if citation.source_type == "knowledge_base":
            return (
                "EVID-SOURCE",
                f"{citation.doc_id}: knowledge guidance cannot enter the account lane",
            )
        if citation.account_id is None:
            return (
                "EVID-ACCOUNT",
                f"{citation.doc_id}: account evidence carries no account owner",
            )
        if citation.account_id != account_id:
            return (
                "EVID-ACCOUNT",
                f"{citation.doc_id}: belongs to {citation.account_id}, not {account_id}",
            )
        if citation.doc_date is None:
            return (
                "EVID-UNDATED",
                f"{citation.doc_id}: account evidence with no date cannot be shown "
                "to precede the cutoff",
            )
        if citation.doc_date > cutoff:
            return (
                "EVID-CUTOFF",
                f"{citation.doc_id}: dated {citation.doc_date}, after the cutoff {cutoff}",
            )

    leaked = set(forbidden_field_mentions(citation.excerpt)) - PROSE_SAFE_FIELD_NAMES
    if leaked:
        return "EVID-LEAK", f"{citation.doc_id}: excerpt names evaluation-only {sorted(leaked)}"
    return None


def metric_violation(metric: MetricObservation) -> tuple[str, str] | None:
    """Return the provenance rule this metric breaks, or None.

    Section 16.3 asks for "exact numeric provenance". `MetricObservation`
    already refuses an empty source, window, or calculation version, so this
    checks the two things a type cannot: that those strings are not merely
    whitespace, and that a *non-zero* value was computed from at least one
    observation. A zero with no coverage is an honest "nothing happened in this
    window"; a non-zero with no coverage is a number from nowhere.
    """

    if not metric.source.strip():
        return "EVID-PROVENANCE", f"{metric.name}: no source recorded"
    if not metric.window.strip():
        return "EVID-PROVENANCE", f"{metric.name}: no observation window recorded"
    if not metric.calculation_version.strip():
        return "EVID-PROVENANCE", f"{metric.name}: no calculation version recorded"
    if metric.coverage == 0 and metric.value != 0.0:
        return (
            "EVID-PROVENANCE",
            f"{metric.name}: value {metric.value:g} was computed from zero observations",
        )
    return None


def screen_evidence(
    quantitative: QuantitativeEvidence,
    retrieval: RetrievalEvidence,
    account_id: str,
    cutoff: date,
) -> EvidenceScreening:
    """Quarantine any evidence that cannot be shown to be in scope.

    Args:
        quantitative: The complete deterministic-lane envelope.
        retrieval: The complete semantic-lane envelope.
        account_id: The account this run is about.
        cutoff: The effective point-in-time cutoff for this run.

    Returns:
        The surviving evidence and a `GuardrailDecision` for the evidence stage:
        `pass` when nothing was dropped, `review` when something was.
    """

    kept_citations: list[Citation] = []
    kept_guidance: list[Citation] = []
    kept_metrics: list[MetricObservation] = []
    rejected: list[str] = []
    rules: list[str] = []
    quantitative_valid = True
    retrieval_valid = True

    if quantitative.account_id != account_id or quantitative.cutoff != cutoff:
        quantitative_valid = False
        rules.append("EVID-ENVELOPE")
        rejected.append(
            "quantitative envelope is scoped to "
            f"{quantitative.account_id} at {quantitative.cutoff}, not {account_id} at {cutoff}"
        )

    if retrieval.account_id != account_id or retrieval.cutoff != cutoff:
        retrieval_valid = False
        rules.append("EVID-ENVELOPE")
        rejected.append(
            "retrieval envelope is scoped to "
            f"{retrieval.account_id} at {retrieval.cutoff}, not {account_id} at {cutoff}"
        )

    if retrieval_valid:
        for citation in retrieval.citations:
            violation = citation_violation(citation, account_id, cutoff, "account")
            if violation is None:
                kept_citations.append(citation)
                continue
            rules.append(violation[0])
            rejected.append(violation[1])

        for article in retrieval.guidance:
            violation = citation_violation(article, account_id, cutoff, "guidance")
            if violation is None:
                kept_guidance.append(article)
                continue
            rules.append(violation[0])
            rejected.append(violation[1])

    if quantitative_valid:
        for metric in quantitative.metrics:
            violation = metric_violation(metric)
            if violation is None:
                kept_metrics.append(metric)
                continue
            quantitative_valid = False
            rules.append(violation[0])
            rejected.append(violation[1])

    unique_rules = tuple(dict.fromkeys(rules))
    if rejected:
        decision = GuardrailDecision(
            stage="evidence",
            outcome="review",
            rule_ids=unique_rules,
            reason_codes=("evidence_quarantined",),
            message=(
                f"{len(rejected)} piece(s) of evidence were withheld because they could not "
                "be shown to belong to this account at this cutoff with exact provenance: "
                + "; ".join(rejected[:5])
            ),
        )
    else:
        decision = GuardrailDecision(
            stage="evidence",
            outcome="pass",
            message=(
                "Every lane envelope, metric provenance record, and citation is scoped to "
                "this account and cutoff."
            ),
        )

    return EvidenceScreening(
        citations=tuple(kept_citations),
        guidance=tuple(kept_guidance),
        metrics=tuple(kept_metrics),
        rejected=tuple(rejected),
        rule_ids=unique_rules,
        quantitative_valid=quantitative_valid,
        retrieval_valid=retrieval_valid,
        decision=decision,
    )


__all__ = [
    "EVIDENCE_RULE_IDS",
    "EvidenceScreening",
    "citation_violation",
    "metric_violation",
    "screen_evidence",
]
