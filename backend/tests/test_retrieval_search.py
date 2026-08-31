"""Retrieval filtering, ranking, and citation safety (plan section 11.4).

These use a deterministic stub encoder rather than the real BGE model, so they
run offline and in milliseconds. What is under test is the filtering and
validation logic, not embedding quality; embedding quality is measured by the
retrieval benchmark instead.

The stub must still produce *graded* similarity. An encoder that maps each text
to an independent random direction leaves every score near zero in 384
dimensions, nothing clears `MINIMUM_SCORE`, and every citation assertion here
passes against an empty list -- the tests would report success while proving
nothing. `test_the_stub_corpus_actually_returns_citations` guards that.
"""

from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from meridian.data.constants import DATASET_AS_OF_DATE
from meridian.data.repository import RuntimeRepository
from meridian.retrieval.chunking import chunk_documents
from meridian.retrieval.contracts import RetrievalGrade, RetrievalRequirements, RetrievalResult
from meridian.retrieval.documents import (
    KNOWLEDGE_TYPE,
    ParentDocument,
    build_parent_documents,
)
from meridian.retrieval.index import (
    CORPUS_MANIFEST_FILENAME,
    IndexManifestError,
    build_index,
    corpus_digest,
    load_index,
    load_verified_index,
    read_corpus_manifest,
)
from meridian.retrieval.search import (
    MAX_ACCOUNT_CITATIONS,
    MAX_KNOWLEDGE_CITATIONS,
    MINIMUM_SCORE,
    RetrievalService,
)
from meridian.retrieval.store import ChunkRecord, MetadataStore
from stub_encoder import StubEncoder

pytestmark = pytest.mark.requires_dataset

INDEXED_ACCOUNTS = 8


@pytest.fixture(scope="module")
def repository(dataset: object) -> RuntimeRepository:
    """Return a repository over the session dataset."""

    return RuntimeRepository(dataset)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def service(
    repository: RuntimeRepository, tmp_path_factory: pytest.TempPathFactory
) -> RetrievalService:
    """Build a small index with the stub encoder and return a search service."""

    accounts = repository.account_ids()[:INDEXED_ACCOUNTS]
    parents = build_parent_documents(repository, accounts)
    chunks = chunk_documents(parents)
    directory = tmp_path_factory.mktemp("index")
    encoder = StubEncoder()
    build_index(parents, chunks, directory, encoder)  # type: ignore[arg-type]
    return RetrievalService(load_index(directory), repository, encoder)  # type: ignore[arg-type]


SATURATING_QUERY = "renewal risk and sponsor change"


def test_the_stub_corpus_actually_returns_citations(
    service: RetrievalService, repository: RuntimeRepository
) -> None:
    """Guard the fixture: every assertion below is vacuous on an empty result.

    Most tests in this module iterate over the returned citations, so an
    encoder that retrieves nothing would make them pass without exercising
    ranking, validation, or the citation caps at all.
    """

    for account_id in repository.account_ids()[:INDEXED_ACCOUNTS]:
        result = service.search(account_id, SATURATING_QUERY)
        assert len(result.account_citations) == MAX_ACCOUNT_CITATIONS
        assert len(result.knowledge_citations) == MAX_KNOWLEDGE_CITATIONS
        assert not result.rejected
        for citation in (*result.account_citations, *result.knowledge_citations):
            assert citation.score >= MINIMUM_SCORE


def test_results_are_scoped_to_the_requested_account(
    service: RetrievalService, repository: RuntimeRepository
) -> None:
    """Zero wrong-account citations is a plan section 11.6 exit criterion."""

    for account_id in repository.account_ids()[:INDEXED_ACCOUNTS]:
        result = service.search(account_id, SATURATING_QUERY)
        assert result.account_citations
        for citation in result.account_citations:
            assert citation.account_id == account_id


def test_results_never_postdate_the_cutoff(
    service: RetrievalService, repository: RuntimeRepository
) -> None:
    """Zero post-cutoff citations is the other section 11.6 exit criterion."""

    for account_id in repository.account_ids()[:INDEXED_ACCOUNTS]:
        result = service.search(account_id, "recent adoption trend and escalations")
        assert result.account_citations
        for citation in result.account_citations:
            assert citation.doc_date is not None
            assert citation.doc_date <= result.cutoff


def test_citation_limits_are_enforced(
    service: RetrievalService, repository: RuntimeRepository
) -> None:
    """Section 11.4 caps account citations at five and guidance at two."""

    # This corpus has far more than five matching passages, so the caps have
    # to bind here; `<=` alone would also hold if nothing were retrieved.
    result = service.search(repository.account_ids()[0], SATURATING_QUERY)
    assert len(result.account_citations) == MAX_ACCOUNT_CITATIONS
    assert len(result.knowledge_citations) == MAX_KNOWLEDGE_CITATIONS


def test_knowledge_lane_is_not_account_scoped(
    service: RetrievalService, repository: RuntimeRepository
) -> None:
    """Guidance is shared, so knowledge citations carry no account id."""

    result = service.search(repository.account_ids()[1], "how do I run a save play")
    assert result.knowledge_citations
    for citation in result.knowledge_citations:
        assert citation.account_id is None
        assert citation.doc_type == KNOWLEDGE_TYPE
        assert citation.is_knowledge_base


def test_account_lane_excludes_knowledge_documents(
    service: RetrievalService, repository: RuntimeRepository
) -> None:
    """Guidance must not be presented as account-specific evidence."""

    result = service.search(repository.account_ids()[2], "renewal outlook")
    assert result.account_citations
    for citation in result.account_citations:
        assert citation.doc_type != KNOWLEDGE_TYPE


def test_citations_resolve_to_their_parent(
    service: RetrievalService, repository: RuntimeRepository
) -> None:
    """Section 11.2 returns the parent for usable context."""

    result = service.search(repository.account_ids()[0], "usage decline")
    assert result.account_citations
    for citation in result.account_citations:
        parent = service.parent_document(citation.parent_id, account_id=result.account_id)
        assert parent is not None
        assert parent.doc_id == citation.parent_id
        assert len(parent.text) >= len(citation.text) - 200
        assert citation.excerpt in citation.parent_context


def test_mmr_avoids_returning_duplicate_parents(
    service: RetrievalService, repository: RuntimeRepository
) -> None:
    """Notes repeat heavily, so ranking must not stack one document's chunks."""

    for account_id in repository.account_ids()[:INDEXED_ACCOUNTS]:
        parents = [
            c.parent_id for c in service.search(account_id, "renewal outlook").account_citations
        ]
        assert len(parents) > 1
        assert len(parents) == len(set(parents))


def test_unknown_account_is_rejected(service: RetrievalService) -> None:
    """An unknown account must raise rather than search everything."""

    from meridian.data.repository import UnknownAccountError

    with pytest.raises(UnknownAccountError):
        service.search("ACC-000000", "anything")


def test_result_reports_source_coverage(
    service: RetrievalService, repository: RuntimeRepository
) -> None:
    """Section 11.4 step 8 requires coverage reporting."""

    result = service.search(repository.account_ids()[0], "support escalations")
    assert result.account_citations
    assert set(result.source_coverage) >= {"csm_note", "support_ticket", "external_event"}
    assert sum(result.source_coverage.values()) == len(result.account_citations)
    assert isinstance(result.missing_families, tuple)


def test_stale_index_is_refused(repository: RuntimeRepository, tmp_path: Path) -> None:
    """Section 11.3 step 8: refuse to serve an index built from another corpus."""

    accounts = repository.account_ids()[:2]
    parents = build_parent_documents(repository, accounts, include_knowledge_base=False)
    chunks = chunk_documents(parents)
    manifest = build_index(parents, chunks, tmp_path, StubEncoder())  # type: ignore[arg-type]

    load_index(tmp_path, expected_digest=corpus_digest(chunks, parents))
    corpus_manifest = read_corpus_manifest(tmp_path)
    assert manifest.index_version.endswith(manifest.corpus_digest[:12])
    assert corpus_manifest.corpus_digest == manifest.corpus_digest
    assert corpus_manifest.parent_counts_by_source
    assert corpus_manifest.chunk_counts_by_source
    with pytest.raises(IndexManifestError, match="rebuild"):
        load_index(tmp_path, expected_digest="0" * 64)
    load_index(tmp_path, expected_digest="0" * 64, allow_mismatch=True)

    corpus_path = tmp_path / CORPUS_MANIFEST_FILENAME
    corpus_path.write_text(corpus_path.read_text().replace("parent_child", "tampered"))
    with pytest.raises(IndexManifestError, match="manifests disagree"):
        load_index(tmp_path)


def test_requested_cutoff_can_only_tighten_visibility(
    service: RetrievalService, repository: RuntimeRepository
) -> None:
    """A caller may request history, but a future date cannot widen the canonical cutoff."""

    account_id = repository.account_ids()[0]
    canonical = repository.cutoff_for(account_id)
    earlier = canonical - timedelta(days=90)
    historical = service.search(account_id, "renewal evidence", requested_as_of=earlier)
    assert historical.cutoff == earlier
    assert all(
        citation.doc_date is not None and citation.doc_date <= earlier
        for citation in historical.account_citations
    )

    attempted_widening = service.search(
        account_id,
        "renewal evidence",
        requested_as_of=canonical + timedelta(days=365),
    )
    assert attempted_widening.cutoff == canonical
    assert all(
        citation.doc_date is not None and citation.doc_date <= canonical
        for citation in attempted_widening.account_citations
    )


def test_source_authorization_is_enforced_before_and_after_ranking(
    service: RetrievalService, repository: RuntimeRepository
) -> None:
    """Only explicitly authorized account source families may be returned."""

    account_id = repository.account_ids()[0]
    result = service.search(
        account_id,
        "support escalation",
        allowed_source_families=("support_ticket",),
    )
    assert all(citation.doc_type == "support_ticket" for citation in result.account_citations)
    assert result.source_coverage["csm_note"] == 0
    assert result.source_coverage["external_event"] == 0

    with pytest.raises(ValueError, match="not authorized"):
        service.retrieve(
            account_id,
            "support escalation",
            allowed_source_families=("csm_note",),
            required_source_families=("support_ticket",),
        )


def test_parent_lookup_enforces_account_date_and_knowledge_scope(
    service: RetrievalService, repository: RuntimeRepository
) -> None:
    """The parent store must not become an unscoped citation bypass."""

    accounts = repository.account_ids()[:INDEXED_ACCOUNTS]
    parents = build_parent_documents(repository, accounts)
    account_parent = next(parent for parent in parents if parent.account_id == accounts[0])
    assert account_parent.doc_date is not None
    assert service.parent_document(account_parent.doc_id, account_id=accounts[0]) == account_parent
    assert service.parent_document(account_parent.doc_id, account_id=accounts[1]) is None
    assert (
        service.parent_document(
            account_parent.doc_id,
            account_id=accounts[0],
            requested_as_of=account_parent.doc_date - timedelta(days=1),
        )
        is None
    )

    assert service.parent_document("KB-001", account_id=accounts[0]) is None
    assert (
        service.parent_document("KB-001", account_id=accounts[0], allow_knowledge_base=True)
        is not None
    )


class _RetryThenPassGrader:
    """Script the two policy decisions so retry bounds are tested independently of embeddings."""

    def __init__(self, always_insufficient: bool = False) -> None:
        self.calls = 0
        self.always_insufficient = always_insufficient

    def grade(self, result: RetrievalResult, requirements: RetrievalRequirements) -> RetrievalGrade:
        self.calls += 1
        insufficient = self.always_insufficient or self.calls == 1
        return RetrievalGrade(
            missing_required_sources=("external_event",) if insufficient else (),
            reasons=("required source coverage missing: external_event",) if insufficient else (),
            needs_retry=insufficient,
            insufficient_evidence=insufficient,
        )


class _MarkerRewriter:
    """Make the second attempt unambiguous in the returned audit."""

    def rewrite(self, query: str, grade: RetrievalGrade) -> str:
        return f"{query} external event market evidence"


def _policy_service(
    repository: RuntimeRepository,
    directory: Path,
    grader: _RetryThenPassGrader,
) -> RetrievalService:
    """Build a tiny deterministic service with a scripted policy grader."""

    parents = build_parent_documents(repository, repository.account_ids()[:2])
    chunks = chunk_documents(parents)
    encoder = StubEncoder()
    build_index(parents, chunks, directory, encoder)  # type: ignore[arg-type]
    return RetrievalService(
        load_index(directory),
        repository,
        encoder,  # type: ignore[arg-type]
        grader,
        _MarkerRewriter(),
    )


def test_retrieval_rewrites_and_retries_at_most_once(
    repository: RuntimeRepository, tmp_path: Path
) -> None:
    """A recoverable grade causes exactly one second search, never an open loop."""

    grader = _RetryThenPassGrader()
    service = _policy_service(repository, tmp_path / "pass", grader)
    result = service.retrieve(repository.account_ids()[0], "What company news matters?")
    assert grader.calls == 2
    assert result.retry_count == 1
    assert len(result.attempted_queries) == 2
    assert result.attempted_queries[0] != result.attempted_queries[1]
    assert not result.insufficient_evidence


def test_exhausted_retry_returns_a_precise_typed_gap(
    repository: RuntimeRepository, tmp_path: Path
) -> None:
    """A failed second grade stops and exposes the missing information."""

    grader = _RetryThenPassGrader(always_insufficient=True)
    service = _policy_service(repository, tmp_path / "exhausted", grader)
    result = service.retrieve(repository.account_ids()[0], "What company news matters?")
    assert grader.calls == 2
    assert result.retry_count == 1
    assert result.insufficient_evidence
    assert result.insufficiency_reason == "required source coverage missing: external_event"
    assert any(reason.startswith("attempt 0:") for reason in result.rejected)


def test_empty_and_oversized_queries_are_rejected(
    service: RetrievalService, repository: RuntimeRepository
) -> None:
    """Embedding work is bounded before a caller can consume resources."""

    with pytest.raises(ValueError, match="empty"):
        service.search(repository.account_ids()[0], "   ")
    with pytest.raises(ValueError, match="exceed"):
        service.search(repository.account_ids()[0], "x" * 2_001)


class _TamperingStore(MetadataStore):
    """A metadata store that lies about scope, to prove the net is not theatre.

    `search` re-validates every citation after ranking even though the SQL
    filters should already guarantee scope. That redundancy is only worth
    keeping if it actually fires, and it cannot fire while the store and the
    filters read the same row -- so these tests corrupt the store between
    filtering and ranking and assert the citation is dropped with a reason.
    """

    def __init__(
        self,
        store: MetadataStore,
        chunk_mutation: Callable[[ChunkRecord], ChunkRecord] | None = None,
        parent_mutation: Callable[[ParentDocument], ParentDocument] | None = None,
        knowledge_lane: bool = False,
        drop_parents: bool = False,
    ) -> None:
        super().__init__(store.path)
        self._chunk_mutation = chunk_mutation
        self._drop_parents = drop_parents
        self._parent_mutation = parent_mutation
        # Corrupt one lane at a time. Mutating both would still be caught, but
        # the rejection reasons would mix and no longer pin down which guard
        # fired.
        self._knowledge_lane = knowledge_lane

    def chunks_by_rows(self, rows: Iterable[int]) -> dict[int, ChunkRecord]:
        """Return records after the configured corruption."""

        records = super().chunks_by_rows(rows)
        if self._chunk_mutation is None:
            return records
        return {
            row: self._chunk_mutation(record) if self._in_scope(record) else record
            for row, record in records.items()
        }

    def _in_scope(self, record: ChunkRecord) -> bool:
        """Return whether this record belongs to the lane under test."""

        return (record.account_id is None) == self._knowledge_lane

    def parent(self, doc_id: str) -> ParentDocument | None:
        """Return the parent after the configured corruption."""

        if self._drop_parents:
            return None
        parent = super().parent(doc_id)
        if parent is None or self._parent_mutation is None:
            return parent
        return self._parent_mutation(parent)


def _tampered(
    service: RetrievalService,
    chunk_mutation: Callable[[ChunkRecord], ChunkRecord] | None = None,
    parent_mutation: Callable[[ParentDocument], ParentDocument] | None = None,
    knowledge_lane: bool = False,
    drop_parents: bool = False,
) -> RetrievalService:
    """Return a service reading through a corrupted metadata store."""

    index = service._index
    corrupted = replace(
        index,
        store=_TamperingStore(
            index.store, chunk_mutation, parent_mutation, knowledge_lane, drop_parents
        ),
    )
    return RetrievalService(corrupted, service.repository, service._encoder)


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        (lambda record: replace(record, account_id="ACC-999999"), "belongs to ACC-999999"),
        (
            lambda record: replace(record, doc_date=DATASET_AS_OF_DATE + timedelta(days=1)),
            "after cutoff",
        ),
        (lambda record: replace(record, doc_date=None), "no date"),
        (lambda record: replace(record, doc_type=KNOWLEDGE_TYPE), "unauthorized source family"),
    ],
)
def test_post_validation_drops_out_of_scope_evidence(
    service: RetrievalService,
    repository: RuntimeRepository,
    mutation: Callable[[ChunkRecord], ChunkRecord],
    expected_reason: str,
) -> None:
    """A store that violates account, date, or source scope yields no citation."""

    account_id = repository.account_ids()[0]
    assert service.search(account_id, SATURATING_QUERY).account_citations
    result = _tampered(service, chunk_mutation=mutation).search(account_id, SATURATING_QUERY)
    assert not result.account_citations
    assert result.rejected
    assert all(expected_reason in reason for reason in result.rejected)


def test_a_parent_that_disagrees_with_its_child_is_dropped(
    service: RetrievalService, repository: RuntimeRepository
) -> None:
    """Parent context must not be able to smuggle in another account's text."""

    account_id = repository.account_ids()[0]
    result = _tampered(
        service,
        parent_mutation=lambda parent: replace(parent, account_id="ACC-999999"),
    ).search(account_id, SATURATING_QUERY)
    assert not result.account_citations
    assert all("parent scope metadata does not match" in reason for reason in result.rejected)


def test_a_missing_parent_is_dropped_rather_than_cited(
    service: RetrievalService, repository: RuntimeRepository
) -> None:
    """A citation without retrievable context is not auditable, so it is refused."""

    result = _tampered(service, drop_parents=True).search(
        repository.account_ids()[0], SATURATING_QUERY
    )
    assert not result.account_citations
    assert all("is missing" in reason for reason in result.rejected)


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        (
            lambda record: replace(record, account_id="ACC-999999"),
            "account document in the knowledge-base lane",
        ),
        (
            lambda record: replace(record, doc_date=DATASET_AS_OF_DATE),
            "knowledge document unexpectedly carries a date",
        ),
    ],
)
def test_the_knowledge_lane_refuses_anything_account_shaped(
    service: RetrievalService,
    repository: RuntimeRepository,
    mutation: Callable[[ChunkRecord], ChunkRecord],
    expected_reason: str,
) -> None:
    """Guidance must stay general; an account-scoped or dated row is a defect."""

    result = _tampered(service, chunk_mutation=mutation, knowledge_lane=True).search(
        repository.account_ids()[0], "how do I run a save play"
    )
    assert not result.knowledge_citations
    assert any(expected_reason in reason for reason in result.rejected)


def test_a_stale_index_is_refused_by_the_verifying_loader(
    repository: RuntimeRepository, tmp_path: Path
) -> None:
    """Scripts must not report numbers from an index built by older code.

    `load_index()` on its own cannot notice: only a caller that recomputes the
    corpus digest can, so the shared loader is what the CLI and the benchmark
    both go through.
    """

    parents = build_parent_documents(repository, repository.account_ids()[:2])
    build_index(parents, chunk_documents(parents), tmp_path, StubEncoder())  # type: ignore[arg-type]

    # The index above covers two accounts; the live corpus covers all of them.
    with pytest.raises(IndexManifestError, match="current corpus differs"):
        load_verified_index(repository, tmp_path)
    assert load_verified_index(repository, tmp_path, allow_mismatch=True) is not None
