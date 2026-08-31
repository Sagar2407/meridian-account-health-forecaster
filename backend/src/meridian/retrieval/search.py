"""Runtime retrieval (plan section 11.4).

Two lanes run per query. The account lane is filtered hard on account id and the
effective cutoff before any vector is scored. The knowledge-base lane carries no
account filter because guidance is not account specific.

Every returned citation is re-validated after ranking. That check is redundant
by design: the filters should already guarantee it, so if post-validation ever
rejects something, a filter has failed and the result is dropped rather than
quietly returned.

Relevance and coverage are graded deterministically in Phase 3. A provider may
implement the same typed interfaces later, but local retrieval and its single
rewrite/retry remain fully functional without an API key.
"""

from datetime import date

import numpy as np

from meridian.data.repository import RuntimeRepository
from meridian.retrieval.contracts import (
    ACCOUNT_SOURCE_FAMILIES,
    AccountSourceFamily,
    Citation,
    RetrievalRequirements,
    RetrievalResult,
)
from meridian.retrieval.documents import KNOWLEDGE_TYPE, ParentDocument
from meridian.retrieval.embedding import TextEncoder
from meridian.retrieval.grading import (
    DeterministicRetrievalGrader,
    RetrievalGrader,
    infer_requirements,
)
from meridian.retrieval.index import RetrievalIndex, search_rows
from meridian.retrieval.rewrite import DeterministicQueryRewriter, QueryRewriter
from meridian.retrieval.store import ChunkRecord

CANDIDATES_PER_LANE = 20
MAX_ACCOUNT_CITATIONS = 5
MAX_KNOWLEDGE_CITATIONS = 2
MMR_LAMBDA = 0.7
MINIMUM_SCORE = 0.3
MAX_RETRIES = 1
MAX_QUERY_CHARACTERS = 2_000
MAX_PARENT_CONTEXT_CHARACTERS = 4_000


def _maximal_marginal_relevance(
    query_vector: np.ndarray,
    candidate_vectors: np.ndarray,
    scores: list[float],
    limit: int,
    lambda_weight: float = MMR_LAMBDA,
) -> list[int]:
    """Return candidate positions reranked for relevance minus redundancy.

    Notes for one account repeat themselves heavily, so pure similarity returns
    near-duplicates. MMR trades a little relevance for coverage.
    """

    selected: list[int] = []
    remaining = list(range(len(scores)))
    while remaining and len(selected) < limit:
        best_position = remaining[0]
        best_value = -np.inf
        for position in remaining:
            if selected:
                redundancy = float(
                    np.max(candidate_vectors[position] @ candidate_vectors[selected].T)
                )
            else:
                redundancy = 0.0
            value = lambda_weight * scores[position] - (1.0 - lambda_weight) * redundancy
            if value > best_value:
                best_value = value
                best_position = position
        selected.append(best_position)
        remaining.remove(best_position)
    return selected


class RetrievalService:
    """Account-scoped, point-in-time-safe semantic retrieval."""

    def __init__(
        self,
        index: RetrievalIndex,
        repository: RuntimeRepository,
        encoder: TextEncoder | None = None,
        grader: RetrievalGrader | None = None,
        rewriter: QueryRewriter | None = None,
    ) -> None:
        self._index = index
        self._repository = repository
        self._encoder = encoder if encoder is not None else TextEncoder()
        self._grader = grader if grader is not None else DeterministicRetrievalGrader()
        self._rewriter = rewriter if rewriter is not None else DeterministicQueryRewriter()

    def _rank(
        self, query_vector: np.ndarray, rows: list[int], limit: int
    ) -> list[tuple[ChunkRecord, float]]:
        """Return the top chunks for `rows` after MMR reranking."""

        hits = search_rows(self._index, query_vector, rows, CANDIDATES_PER_LANE)
        hits = [(row, score) for row, score in hits if score >= MINIMUM_SCORE]
        if not hits:
            return []
        records = self._index.store.chunks_by_rows(row for row, _ in hits)
        usable: list[tuple[int, float]] = []
        seen_parents: set[str] = set()
        for row, score in hits:
            record = records.get(row)
            if record is None or record.parent_id in seen_parents:
                continue
            usable.append((row, score))
            seen_parents.add(record.parent_id)
        if not usable:
            return []
        vectors = np.vstack(
            [self._index.faiss_index.reconstruct(int(row)) for row, _ in usable]  # type: ignore[attr-defined]
        )
        order = _maximal_marginal_relevance(
            query_vector, vectors, [score for _, score in usable], limit
        )
        return [(records[usable[position][0]], usable[position][1]) for position in order]

    def _validate(
        self,
        record: ChunkRecord,
        account_id: str,
        cutoff: date,
        knowledge_lane: bool,
        allowed_source_families: tuple[AccountSourceFamily, ...],
    ) -> str | None:
        """Return a rejection reason, or None when the record is admissible."""

        if knowledge_lane:
            if record.account_id is not None:
                return f"{record.child_id}: account document in the knowledge-base lane"
            if record.doc_type != KNOWLEDGE_TYPE:
                return f"{record.child_id}: non-KB document in the knowledge-base lane"
            if record.doc_date is not None:
                return f"{record.child_id}: knowledge document unexpectedly carries a date"
            return None
        if record.account_id != account_id:
            return f"{record.child_id}: belongs to {record.account_id}, not {account_id}"
        if record.doc_date is None:
            return f"{record.child_id}: account evidence has no date"
        if record.doc_date > cutoff:
            return f"{record.child_id}: dated {record.doc_date}, after cutoff {cutoff}"
        if record.doc_type not in allowed_source_families:
            return f"{record.child_id}: unauthorized source family {record.doc_type}"
        return None

    def _parent_for_record(
        self,
        record: ChunkRecord,
        account_id: str,
        cutoff: date,
        knowledge_lane: bool,
    ) -> tuple[ParentDocument | None, str | None]:
        """Resolve a parent and verify that its governance metadata agrees."""

        parent = self._index.store.parent(record.parent_id)
        if parent is None:
            return None, f"{record.child_id}: parent {record.parent_id} is missing"
        if parent.doc_type != record.doc_type or parent.subtype != record.subtype:
            return None, f"{record.child_id}: parent source metadata does not match the child"
        if parent.account_id != record.account_id or parent.doc_date != record.doc_date:
            return None, f"{record.child_id}: parent scope metadata does not match the child"
        if knowledge_lane:
            if parent.account_id is not None or parent.doc_type != KNOWLEDGE_TYPE:
                return None, f"{record.child_id}: invalid knowledge parent"
        elif parent.account_id != account_id or parent.doc_date is None or parent.doc_date > cutoff:
            return None, f"{record.child_id}: parent violates account or cutoff scope"
        return parent, None

    @property
    def repository(self) -> RuntimeRepository:
        """Return the underlying sanitized repository."""

        return self._repository

    def parent_document(
        self,
        doc_id: str,
        *,
        account_id: str,
        requested_as_of: date | None = None,
        allow_knowledge_base: bool = False,
    ) -> ParentDocument | None:
        """Return a parent only when the caller's scope permits it."""

        parent = self._index.store.parent(doc_id)
        if parent is None:
            return None
        if parent.doc_type == KNOWLEDGE_TYPE:
            return parent if allow_knowledge_base and parent.account_id is None else None
        cutoff = self._effective_cutoff(account_id, requested_as_of)
        if parent.account_id != account_id or parent.doc_date is None or parent.doc_date > cutoff:
            return None
        return parent

    def _effective_cutoff(self, account_id: str, requested_as_of: date | None) -> date:
        """Clamp a requested date so it can tighten but never widen visibility."""

        canonical = self._repository.cutoff_for(account_id)
        return min(canonical, requested_as_of) if requested_as_of is not None else canonical

    @staticmethod
    def _normalise_query(query: str) -> str:
        """Validate and normalize one bounded semantic query."""

        normalized = " ".join(query.split())
        if not normalized:
            raise ValueError("query must not be empty")
        if len(normalized) > MAX_QUERY_CHARACTERS:
            raise ValueError(f"query must not exceed {MAX_QUERY_CHARACTERS} characters")
        return normalized

    @staticmethod
    def _normalise_allowed_sources(
        allowed_source_families: tuple[AccountSourceFamily, ...] | None,
    ) -> tuple[AccountSourceFamily, ...]:
        """Return a unique, non-empty account-source allowlist."""

        requested = (
            ACCOUNT_SOURCE_FAMILIES if allowed_source_families is None else allowed_source_families
        )
        allowed = tuple(dict.fromkeys(requested))
        unknown = set(allowed) - set(ACCOUNT_SOURCE_FAMILIES)
        if unknown:
            raise ValueError(f"unknown account source families: {sorted(unknown)}")
        return allowed

    def search(
        self,
        account_id: str,
        query: str,
        *,
        requested_as_of: date | None = None,
        allowed_source_families: tuple[AccountSourceFamily, ...] | None = None,
        include_knowledge_base: bool = True,
    ) -> RetrievalResult:
        """Retrieve account evidence and supporting guidance for one query.

        Raises:
            UnknownAccountError: If `account_id` is not in the dataset.
        """

        normalized_query = self._normalise_query(query)
        allowed_sources = self._normalise_allowed_sources(allowed_source_families)
        cutoff = self._effective_cutoff(account_id, requested_as_of)
        query_vector = self._encoder.encode_queries([normalized_query])[0]

        rejected: list[str] = []
        account_hits = self._rank(
            query_vector,
            self._index.store.candidate_rows(
                account_id,
                cutoff,
                allowed_doc_types=allowed_sources,
            ),
            MAX_ACCOUNT_CITATIONS,
        )
        knowledge_hits = (
            self._rank(
                query_vector,
                self._index.store.candidate_rows(
                    None,
                    None,
                    knowledge_base_only=True,
                    allowed_doc_types=(KNOWLEDGE_TYPE,),
                ),
                MAX_KNOWLEDGE_CITATIONS,
            )
            if include_knowledge_base
            else []
        )

        account_citations: list[Citation] = []
        for record, score in account_hits:
            reason = self._validate(
                record,
                account_id,
                cutoff,
                knowledge_lane=False,
                allowed_source_families=allowed_sources,
            )
            if reason:
                rejected.append(reason)
                continue
            parent, parent_reason = self._parent_for_record(
                record, account_id, cutoff, knowledge_lane=False
            )
            if parent_reason or parent is None:
                rejected.append(parent_reason or f"{record.child_id}: parent unavailable")
                continue
            account_citations.append(_to_citation(record, score, parent))

        knowledge_citations: list[Citation] = []
        for record, score in knowledge_hits:
            reason = self._validate(
                record,
                account_id,
                cutoff,
                knowledge_lane=True,
                allowed_source_families=allowed_sources,
            )
            if reason:
                rejected.append(reason)
                continue
            parent, parent_reason = self._parent_for_record(
                record, account_id, cutoff, knowledge_lane=True
            )
            if parent_reason or parent is None:
                rejected.append(parent_reason or f"{record.child_id}: parent unavailable")
                continue
            knowledge_citations.append(_to_citation(record, score, parent))

        coverage: dict[str, int] = {family: 0 for family in ACCOUNT_SOURCE_FAMILIES}
        for citation in account_citations:
            coverage[citation.doc_type] = coverage.get(citation.doc_type, 0) + 1

        return RetrievalResult(
            query=normalized_query,
            effective_query=normalized_query,
            attempted_queries=(normalized_query,),
            account_id=account_id,
            requested_as_of=requested_as_of,
            cutoff=cutoff,
            allowed_source_families=allowed_sources,
            account_citations=tuple(account_citations),
            knowledge_citations=tuple(knowledge_citations),
            source_coverage=coverage,
            rejected=tuple(rejected),
        )

    def retrieve(
        self,
        account_id: str,
        query: str,
        *,
        requested_as_of: date | None = None,
        allowed_source_families: tuple[AccountSourceFamily, ...] | None = None,
        include_knowledge_base: bool = True,
        required_source_families: tuple[AccountSourceFamily, ...] = (),
        require_account_evidence: bool = True,
        require_corroboration: bool | None = None,
        maximum_age_days: int | None = None,
    ) -> RetrievalResult:
        """Grade one search and perform at most one filter-preserving retry."""

        original_query = self._normalise_query(query)
        allowed_sources = self._normalise_allowed_sources(allowed_source_families)
        disallowed_requirements = set(required_source_families) - set(allowed_sources)
        if disallowed_requirements:
            raise ValueError(
                f"required source families are not authorized: {sorted(disallowed_requirements)}"
            )
        requirements = infer_requirements(
            original_query,
            required_source_families=required_source_families,
            require_account_evidence=require_account_evidence,
            require_corroboration=require_corroboration,
            maximum_age_days=maximum_age_days,
        )
        # Inference must not silently demand a source the caller did not
        # authorize. Keep only explicit/inferred expectations within scope.
        requirements = RetrievalRequirements(
            required_source_families=tuple(
                family
                for family in requirements.required_source_families
                if family in allowed_sources
            ),
            require_account_evidence=requirements.require_account_evidence,
            require_corroboration=requirements.require_corroboration,
            maximum_age_days=requirements.maximum_age_days,
        )

        first = self.search(
            account_id,
            original_query,
            requested_as_of=requested_as_of,
            allowed_source_families=allowed_sources,
            include_knowledge_base=include_knowledge_base,
        )
        first_grade = self._grader.grade(first, requirements)
        if not first_grade.needs_retry:
            return first.model_copy(update={"grade": first_grade})

        rewritten_query = self._normalise_query(self._rewriter.rewrite(original_query, first_grade))
        second = self.search(
            account_id,
            rewritten_query,
            requested_as_of=requested_as_of,
            allowed_source_families=allowed_sources,
            include_knowledge_base=include_knowledge_base,
        )
        final_grade = self._grader.grade(second, requirements)
        audit_rejections = (
            *first.rejected,
            *(f"attempt 0: {reason}" for reason in first_grade.reasons),
            *second.rejected,
        )
        insufficiency = (
            "; ".join(final_grade.reasons) if final_grade.insufficient_evidence else None
        )
        payload = second.model_dump()
        payload.update(
            {
                "query": original_query,
                "effective_query": rewritten_query,
                "attempted_queries": (original_query, rewritten_query),
                "retry_count": MAX_RETRIES,
                "grade": final_grade,
                "rejected": tuple(audit_rejections),
                "insufficiency_reason": insufficiency,
            }
        )
        return RetrievalResult.model_validate(payload)


def _bounded_parent_context(parent_text: str, excerpt: str) -> str:
    """Return the whole parent or a bounded window containing the child."""

    if len(parent_text) <= MAX_PARENT_CONTEXT_CHARACTERS:
        return parent_text
    position = parent_text.find(excerpt)
    if position < 0:
        return parent_text[:MAX_PARENT_CONTEXT_CHARACTERS].rstrip()
    padding = max((MAX_PARENT_CONTEXT_CHARACTERS - len(excerpt)) // 2, 0)
    start = max(position - padding, 0)
    end = min(start + MAX_PARENT_CONTEXT_CHARACTERS, len(parent_text))
    start = max(end - MAX_PARENT_CONTEXT_CHARACTERS, 0)
    return parent_text[start:end].strip()


def _to_citation(record: ChunkRecord, score: float, parent: ParentDocument) -> Citation:
    """Return a citation for one scored chunk record."""

    return Citation(
        child_id=record.child_id,
        parent_id=record.parent_id,
        doc_type=record.doc_type,
        subtype=record.subtype,
        account_id=record.account_id,
        doc_date=record.doc_date,
        score=score,
        excerpt=record.text,
        parent_context=_bounded_parent_context(parent.text, record.text),
        segment=record.segment,
        product=record.product,
        source_severity=record.source_severity,
    )
