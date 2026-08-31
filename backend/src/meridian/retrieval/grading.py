"""Deterministic retrieval grading and coverage inference (plan section 11.5).

Phase 3 intentionally does not depend on a hosted language model.  Semantic
similarity supplies the relevance signal; deterministic policy decides whether
the evidence is sufficiently relevant, corroborated, recent, and source-complete
to stop or to spend the one permitted retry.
"""

from typing import Protocol

from meridian.retrieval.contracts import (
    ACCOUNT_SOURCE_FAMILIES,
    AccountSourceFamily,
    RetrievalGrade,
    RetrievalRequirements,
    RetrievalResult,
)

MIN_GRADED_RELEVANCE = 0.50
DEFAULT_RECENT_MAXIMUM_AGE_DAYS = 365

_SOURCE_TERMS: dict[AccountSourceFamily, tuple[str, ...]] = {
    "csm_note": (
        "adoption",
        "champion",
        "onboarding",
        "qbr",
        "relationship",
        "renewal",
        "sponsor",
        "usage",
    ),
    "support_ticket": (
        "bug",
        "defect",
        "escalation",
        "incident",
        "issue",
        "outage",
        "support",
        "ticket",
        "unresolved",
    ),
    "external_event": (
        "acquisition",
        "earnings",
        "event",
        "external",
        "funding",
        "layoff",
        "leadership",
        "market",
        "news",
    ),
}
_CORROBORATION_TERMS = ("assess", "assessment", "at risk", "forecast", "why")
_RECENCY_TERMS = ("current", "latest", "outstanding", "recent", "today")


class RetrievalGrader(Protocol):
    """Provider-neutral grader interface used by the bounded retriever."""

    def grade(self, result: RetrievalResult, requirements: RetrievalRequirements) -> RetrievalGrade:
        """Return a typed relevance and coverage decision."""


def infer_requirements(
    query: str,
    *,
    required_source_families: tuple[AccountSourceFamily, ...] = (),
    require_account_evidence: bool = True,
    require_corroboration: bool | None = None,
    maximum_age_days: int | None = None,
) -> RetrievalRequirements:
    """Combine explicit expectations with conservative query-term inference."""

    lowered = query.casefold()
    inferred = [
        family
        for family in ACCOUNT_SOURCE_FAMILIES
        if any(term in lowered for term in _SOURCE_TERMS[family])
    ]
    required = tuple(dict.fromkeys((*required_source_families, *inferred)))
    corroboration = (
        any(term in lowered for term in _CORROBORATION_TERMS)
        if require_corroboration is None
        else require_corroboration
    )
    age = maximum_age_days
    if age is None and any(term in lowered for term in _RECENCY_TERMS):
        age = DEFAULT_RECENT_MAXIMUM_AGE_DAYS
    return RetrievalRequirements(
        required_source_families=required,
        require_account_evidence=require_account_evidence,
        require_corroboration=corroboration,
        maximum_age_days=age,
    )


class DeterministicRetrievalGrader:
    """Grade semantic hits without a hosted model or hidden reasoning."""

    def __init__(self, minimum_relevance: float = MIN_GRADED_RELEVANCE) -> None:
        if not -1.0 <= minimum_relevance <= 1.0:
            raise ValueError("minimum_relevance must be between -1 and 1")
        self.minimum_relevance = minimum_relevance

    def grade(self, result: RetrievalResult, requirements: RetrievalRequirements) -> RetrievalGrade:
        """Return reasons that either accept the attempt or justify one retry."""

        relevant = tuple(
            citation
            for citation in result.account_citations
            if citation.score >= self.minimum_relevance
        )
        rejected = tuple(
            citation.child_id
            for citation in result.account_citations
            if citation.score < self.minimum_relevance
        )
        relevant_parents = {citation.parent_id for citation in relevant}
        relevant_sources = {citation.doc_type for citation in relevant}
        missing = tuple(
            family
            for family in requirements.required_source_families
            if family not in relevant_sources
        )

        reasons: list[str] = []
        if requirements.require_account_evidence and not relevant:
            reasons.append("no account passage passed deterministic relevance grading")
        if requirements.require_corroboration and len(relevant_parents) < 2:
            reasons.append("fewer than two independent account parents corroborate the query")
        if missing:
            reasons.append(f"required source coverage missing: {', '.join(missing)}")

        duplicate_count = len(relevant) - len(relevant_parents)
        if relevant and duplicate_count >= max(1, len(relevant) // 3):
            reasons.append("returned evidence is duplicate-heavy")

        if requirements.maximum_age_days is not None and relevant:
            fresh = [
                citation
                for citation in relevant
                if citation.doc_date is not None
                and (result.cutoff - citation.doc_date).days <= requirements.maximum_age_days
            ]
            if not fresh:
                reasons.append(
                    "all relevant account evidence is older than "
                    f"{requirements.maximum_age_days} days at the cutoff"
                )

        insufficient = bool(reasons)
        return RetrievalGrade(
            relevant_citation_ids=tuple(citation.child_id for citation in relevant),
            rejected_citation_ids=rejected,
            missing_required_sources=missing,
            reasons=tuple(reasons),
            needs_retry=insufficient,
            insufficient_evidence=insufficient,
        )
