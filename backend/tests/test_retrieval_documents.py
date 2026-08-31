"""Indexable document construction and chunking (plan sections 11.1 and 11.2)."""

import re

import pandas as pd
import pytest

from meridian.data.constants import FORBIDDEN_RUNTIME_FIELDS
from meridian.data.repository import RuntimeRepository
from meridian.retrieval.chunking import (
    MAX_CHUNK_CHARACTERS,
    chunk_documents,
    chunk_parent,
    fixed_length_chunks,
)
from meridian.retrieval.documents import (
    EVENT_TYPE,
    KNOWLEDGE_TYPE,
    NOTE_TYPE,
    TICKET_TYPE,
    ParentDocument,
    assert_no_latent_text,
    build_parent_documents,
    load_knowledge_base,
)

pytestmark = pytest.mark.requires_dataset


def _forbidden_mentions(text: str) -> set[str]:
    """Return exact forbidden schema tokens present in text."""

    lowered = text.lower()
    return {
        field
        for field in FORBIDDEN_RUNTIME_FIELDS
        if re.search(rf"(?<![a-z0-9_]){re.escape(field)}(?![a-z0-9_])", lowered)
    }


@pytest.fixture(scope="module")
def sample_documents(dataset_repository: RuntimeRepository) -> list[ParentDocument]:
    """Return documents for a small, deterministic slice of accounts."""

    return build_parent_documents(dataset_repository, dataset_repository.account_ids()[:12])


@pytest.fixture(scope="module")
def dataset_repository(dataset: object) -> RuntimeRepository:
    """Return a repository over the session dataset."""

    return RuntimeRepository(dataset)  # type: ignore[arg-type]


def test_all_four_source_families_are_indexed(sample_documents: list[ParentDocument]) -> None:
    """Notes, tickets, events, and the knowledge base must all appear."""

    families = {document.doc_type for document in sample_documents}
    assert families == {NOTE_TYPE, TICKET_TYPE, EVENT_TYPE, KNOWLEDGE_TYPE}


def test_knowledge_base_has_thirty_two_articles() -> None:
    """The archive ships 32 knowledge-base documents."""

    assert len(load_knowledge_base()) == 32


def test_no_telemetry_is_indexed(sample_documents: list[ParentDocument]) -> None:
    """Plan section 11.1 forbids indexing numeric telemetry."""

    telemetry_columns = ("active_users", "api_calls", "storage_gb", "feature_events")
    for document in sample_documents:
        if document.doc_type == KNOWLEDGE_TYPE:
            continue
        assert not any(column in document.text for column in telemetry_columns)


def test_documents_carry_no_forbidden_field(sample_documents: list[ParentDocument]) -> None:
    """Section 11.3 step 3 requires asserting forbidden-field absence."""

    assert_no_latent_text(sample_documents)
    for document in sample_documents:
        assert not set(document.metadata) & FORBIDDEN_RUNTIME_FIELDS
        serialized = f"{document.text}\n{document.metadata}".lower()
        assert not _forbidden_mentions(serialized)


def test_knowledge_base_is_sanitized_without_dropping_guidance() -> None:
    """Policy articles stay useful without putting forbidden schema names in the index."""

    articles = load_knowledge_base()
    assert len(articles) == 32
    policy = next(article for article in articles if article.doc_id == "KB-032")
    assert "Grounding and honesty" in policy.text
    assert "reason from observable features" in policy.text
    searchable = "\n".join(article.text for article in articles).lower()
    assert not _forbidden_mentions(searchable)


def test_latent_leak_is_detected() -> None:
    """The guard must fire, or it provides no protection."""

    leaky = ParentDocument(
        doc_id="NOTE-1", doc_type=NOTE_TYPE, subtype="x", text="health_band is at_risk"
    )
    with pytest.raises(ValueError, match="forbidden"):
        assert_no_latent_text([leaky])


def test_documents_respect_the_account_cutoff(
    dataset_repository: RuntimeRepository, sample_documents: list[ParentDocument]
) -> None:
    """No indexed document may postdate its account's effective cutoff."""

    for document in sample_documents:
        if document.account_id is None or document.doc_date is None:
            continue
        assert document.doc_date <= dataset_repository.cutoff_for(document.account_id)


def test_external_events_become_evidence_documents(
    sample_documents: list[ParentDocument],
) -> None:
    """Section 8.3: the packaged corpus has no event documents, so they are built."""

    events = [item for item in sample_documents if item.doc_type == EVENT_TYPE]
    assert events
    for event in events:
        assert event.text.startswith("[External event]")
        assert any(word in event.text for word in ("adverse", "favorable", "neutral"))


def test_child_ids_are_deterministic(sample_documents: list[ParentDocument]) -> None:
    """Rebuilding the index must produce identical child ids, so citations hold."""

    first = chunk_documents(sample_documents)
    second = chunk_documents(sample_documents)
    assert [chunk.child_id for chunk in first] == [chunk.child_id for chunk in second]
    assert len({chunk.child_id for chunk in first}) == len(first)


def test_children_point_at_a_real_parent(sample_documents: list[ParentDocument]) -> None:
    """Every chunk must resolve to a parent, or the citation cannot be expanded."""

    parents = {document.doc_id for document in sample_documents}
    for chunk in chunk_documents(sample_documents):
        assert chunk.parent_id in parents
        assert chunk.child_id.startswith(chunk.parent_id)


def test_children_inherit_account_scope_and_date(
    sample_documents: list[ParentDocument],
) -> None:
    """Filter metadata must survive chunking, since filtering happens on chunks."""

    by_id = {document.doc_id: document for document in sample_documents}
    for chunk in chunk_documents(sample_documents):
        parent = by_id[chunk.parent_id]
        assert chunk.account_id == parent.account_id
        assert chunk.doc_date == parent.doc_date
        assert chunk.segment == (parent.metadata.get("segment") or None)
        assert chunk.product == (
            parent.metadata.get("product") or parent.metadata.get("primary_product") or None
        )


def test_ticket_children_carry_severity_metadata(
    sample_documents: list[ParentDocument],
) -> None:
    """Ticket priority must remain available for filtering and citation context."""

    tickets = [
        chunk for chunk in chunk_documents(sample_documents) if chunk.doc_type == TICKET_TYPE
    ]
    assert tickets
    assert all(chunk.source_severity in {"P1", "P2", "P3", "P4"} for chunk in tickets)


def test_notes_split_but_tickets_stay_whole(
    sample_documents: list[ParentDocument],
) -> None:
    """Section 11.2: split notes and articles, keep short tickets and events intact."""

    tickets = [item for item in sample_documents if item.doc_type == TICKET_TYPE]
    events = [item for item in sample_documents if item.doc_type == EVENT_TYPE]
    assert all(len(chunk_parent(item)) == 1 for item in events)
    assert all(len(chunk_parent(item)) == 1 for item in tickets)

    notes = [item for item in sample_documents if item.doc_type == NOTE_TYPE]
    assert max(len(chunk_parent(note)) for note in notes) > 1


def test_chunks_stay_within_the_size_bound(sample_documents: list[ParentDocument]) -> None:
    """Oversized sections are split so no single embedding is diluted."""

    for chunk in chunk_documents(sample_documents):
        assert len(chunk.text) <= MAX_CHUNK_CHARACTERS


def test_fixed_length_arm_covers_the_same_parents(
    sample_documents: list[ParentDocument],
) -> None:
    """The ablation arm must differ only in how parents are split."""

    structural = chunk_documents(sample_documents)
    fixed = fixed_length_chunks(sample_documents)
    assert {chunk.parent_id for chunk in fixed} == {chunk.parent_id for chunk in structural}
    assert {chunk.child_id for chunk in fixed}.isdisjoint({c.child_id for c in structural})


def test_fixed_length_rejects_invalid_overlap(
    sample_documents: list[ParentDocument],
) -> None:
    """An overlap at or above the window would never terminate."""

    with pytest.raises(ValueError, match="overlap"):
        fixed_length_chunks(sample_documents, size=100, overlap=100)
    with pytest.raises(ValueError, match="positive"):
        fixed_length_chunks(sample_documents, size=0, overlap=0)
    with pytest.raises(ValueError, match="non-negative"):
        fixed_length_chunks(sample_documents, size=100, overlap=-1)


def test_no_empty_chunks(sample_documents: list[ParentDocument]) -> None:
    """Empty text would produce a meaningless embedding."""

    assert all(chunk.text.strip() for chunk in chunk_documents(sample_documents))
    assert not pd.isna(pd.Series([len(c.text) for c in chunk_documents(sample_documents)])).any()
