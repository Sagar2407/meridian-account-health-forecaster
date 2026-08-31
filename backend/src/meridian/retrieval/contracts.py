"""Typed retrieval boundary models (implementation plan section 9.1).

The models validate the safety properties again at the return boundary.  SQL
filters and search-time checks should already enforce them; the redundancy
ensures a future ranking implementation cannot accidentally serialize a
wrong-account, future-dated, or unauthorized citation.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from meridian.data.constants import DATASET_AS_OF_DATE

AccountSourceFamily = Literal["csm_note", "support_ticket", "external_event"]
ACCOUNT_SOURCE_FAMILIES: tuple[AccountSourceFamily, ...] = (
    "csm_note",
    "support_ticket",
    "external_event",
)
KNOWLEDGE_SOURCE_FAMILY = "knowledge_base"


class Citation(BaseModel):
    """One verified child excerpt plus bounded parent context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    child_id: str = Field(min_length=1)
    parent_id: str = Field(min_length=1)
    doc_type: str = Field(min_length=1)
    subtype: str = Field(min_length=1)
    account_id: str | None
    doc_date: date | None
    score: float
    excerpt: str = Field(min_length=1)
    parent_context: str = Field(min_length=1)
    segment: str | None = None
    product: str | None = None
    source_severity: str | None = None

    @property
    def text(self) -> str:
        """Backward-compatible name for the precise matched child excerpt."""

        return self.excerpt

    @property
    def doc_id(self) -> str:
        """Return the cited source-document id from the plan's public vocabulary."""

        return self.parent_id

    @property
    def source_type(self) -> str:
        """Return the source family under its public contract name."""

        return self.doc_type

    @property
    def date(self) -> date | None:
        """Return the source date under its public contract name."""

        return self.doc_date

    @property
    def retrieval_score(self) -> float:
        """Return semantic similarity under its public contract name."""

        return self.score

    @property
    def is_knowledge_base(self) -> bool:
        """Return whether this citation is guidance rather than account evidence."""

        return self.doc_type == KNOWLEDGE_SOURCE_FAMILY


class RetrievalGrade(BaseModel):
    """Deterministic relevance and coverage decision for one attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    relevant_citation_ids: tuple[str, ...] = ()
    rejected_citation_ids: tuple[str, ...] = ()
    missing_required_sources: tuple[AccountSourceFamily, ...] = ()
    reasons: tuple[str, ...] = ()
    needs_retry: bool = False
    insufficient_evidence: bool = False


class RetrievalResult(BaseModel):
    """Auditable bounded retrieval result returned to callers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str = Field(min_length=1)
    effective_query: str = Field(min_length=1)
    attempted_queries: tuple[str, ...] = Field(min_length=1, max_length=2)
    account_id: str = Field(min_length=1)
    requested_as_of: date | None = None
    cutoff: date
    allowed_source_families: tuple[AccountSourceFamily, ...]
    account_citations: tuple[Citation, ...] = Field(max_length=5)
    knowledge_citations: tuple[Citation, ...] = Field(max_length=2)
    source_coverage: dict[str, int]
    rejected: tuple[str, ...] = ()
    retry_count: int = Field(default=0, ge=0, le=1)
    grade: RetrievalGrade | None = None
    insufficiency_reason: str | None = None

    @model_validator(mode="after")
    def validate_boundary(self) -> "RetrievalResult":
        """Recheck citation scope, dates, limits, and retry accounting."""

        if self.retry_count != len(self.attempted_queries) - 1:
            raise ValueError("retry_count must match the number of attempted queries")
        if self.effective_query != self.attempted_queries[-1]:
            raise ValueError("effective_query must be the final attempted query")
        if self.cutoff > DATASET_AS_OF_DATE:
            raise ValueError("effective cutoff exceeds the dataset observation horizon")
        if self.requested_as_of is not None and self.cutoff > self.requested_as_of:
            raise ValueError("effective cutoff exceeds the caller's requested as-of date")

        allowed = set(self.allowed_source_families)
        for citation in self.account_citations:
            if citation.account_id != self.account_id:
                raise ValueError("account citation belongs to another account")
            if citation.doc_date is None or citation.doc_date > self.cutoff:
                raise ValueError("account citation is undated or after the effective cutoff")
            if citation.doc_type not in allowed:
                raise ValueError("account citation comes from an unauthorized source family")
        for citation in self.knowledge_citations:
            if citation.account_id is not None or not citation.is_knowledge_base:
                raise ValueError("knowledge citation is not general guidance")

        measured: dict[str, int] = {family: 0 for family in ACCOUNT_SOURCE_FAMILIES}
        for citation in self.account_citations:
            measured[citation.doc_type] = measured.get(citation.doc_type, 0) + 1
        if any(self.source_coverage.get(family, 0) != count for family, count in measured.items()):
            raise ValueError("source_coverage does not match the returned account citations")
        return self

    @property
    def insufficient_evidence(self) -> bool:
        """Return whether the final graded attempt cannot support the request."""

        if self.grade is not None:
            return self.grade.insufficient_evidence
        return not self.account_citations

    @property
    def missing_families(self) -> tuple[AccountSourceFamily, ...]:
        """Return account source families that produced no final citation."""

        return tuple(
            family for family in ACCOUNT_SOURCE_FAMILIES if not self.source_coverage.get(family)
        )


class RetrievalRequirements(BaseModel):
    """Coverage expectations supplied by an orchestrator or inferred locally."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    required_source_families: tuple[AccountSourceFamily, ...] = ()
    require_account_evidence: bool = True
    require_corroboration: bool = False
    maximum_age_days: int | None = Field(default=None, ge=1)
