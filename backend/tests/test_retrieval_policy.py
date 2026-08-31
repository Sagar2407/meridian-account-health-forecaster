"""Typed retrieval contracts, deterministic grading, and bounded rewriting."""

import sys
import types
from datetime import date, timedelta
from typing import ClassVar

import numpy as np
import pytest
from pydantic import ValidationError

from meridian.retrieval.contracts import (
    Citation,
    RetrievalGrade,
    RetrievalRequirements,
    RetrievalResult,
)
from meridian.retrieval.embedding import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL_ID,
    TextEncoder,
    normalize,
)
from meridian.retrieval.grading import DeterministicRetrievalGrader, infer_requirements
from meridian.retrieval.rewrite import (
    MAX_REWRITTEN_QUERY_CHARACTERS,
    DeterministicQueryRewriter,
)
from meridian.retrieval.search import _bounded_parent_context

ACCOUNT_ID = "ACC-1001"
CUTOFF = date(2026, 6, 28)


def _citation(
    child_id: str = "NOTE-1#c000",
    parent_id: str = "NOTE-1",
    doc_type: str = "csm_note",
    score: float = 0.8,
    doc_date: date = CUTOFF,
) -> Citation:
    """Return one valid account citation for policy tests."""

    return Citation(
        child_id=child_id,
        parent_id=parent_id,
        doc_type=doc_type,
        subtype="Quarterly Business Review",
        account_id=ACCOUNT_ID,
        doc_date=doc_date,
        score=score,
        excerpt="Adoption weakened while the sponsor stayed engaged.",
        parent_context="QBR context. Adoption weakened while the sponsor stayed engaged.",
        segment="Enterprise",
        product="Analytics",
    )


def _result(*citations: Citation) -> RetrievalResult:
    """Return a valid ungraded single-attempt result."""

    coverage = {"csm_note": 0, "support_ticket": 0, "external_event": 0}
    for citation in citations:
        coverage[citation.doc_type] += 1
    return RetrievalResult(
        query="Why is this account at risk?",
        effective_query="Why is this account at risk?",
        attempted_queries=("Why is this account at risk?",),
        account_id=ACCOUNT_ID,
        cutoff=CUTOFF,
        allowed_source_families=("csm_note", "support_ticket", "external_event"),
        account_citations=citations,
        knowledge_citations=(),
        source_coverage=coverage,
    )


def test_citation_contract_forbids_unknown_fields() -> None:
    """Citation payloads cannot acquire unreviewed or latent fields silently."""

    with pytest.raises(ValidationError, match="extra_forbidden"):
        Citation.model_validate({**_citation().model_dump(), "outcome": "Churned"})


def test_result_contract_rejects_wrong_account_future_and_unauthorized_citations() -> None:
    """The typed return boundary independently enforces the three hard filters."""

    base = _citation().model_dump()
    wrong_account = Citation.model_validate({**base, "account_id": "ACC-9999"})
    with pytest.raises(ValidationError, match="another account"):
        _result(wrong_account)

    future = Citation.model_validate({**base, "doc_date": CUTOFF + timedelta(days=1)})
    with pytest.raises(ValidationError, match="effective cutoff"):
        _result(future)

    ticket = Citation.model_validate({**base, "doc_type": "support_ticket"})
    payload = _result(ticket).model_dump()
    payload["allowed_source_families"] = ("csm_note",)
    with pytest.raises(ValidationError, match="unauthorized"):
        RetrievalResult.model_validate(payload)


def test_result_contract_checks_retry_accounting_and_coverage() -> None:
    """Attempt history and coverage cannot disagree with the returned evidence."""

    payload = _result(_citation()).model_dump()
    payload["retry_count"] = 1
    with pytest.raises(ValidationError, match="attempted queries"):
        RetrievalResult.model_validate(payload)

    payload = _result(_citation()).model_dump()
    payload["source_coverage"]["csm_note"] = 0
    with pytest.raises(ValidationError, match="source_coverage"):
        RetrievalResult.model_validate(payload)


def test_query_requirements_are_inferred_from_domain_terms() -> None:
    """Thin user phrasing maps to explicit source, corroboration, and recency needs."""

    requirements = infer_requirements(
        "Why did the latest sponsor change and support escalation affect market risk?"
    )
    assert set(requirements.required_source_families) == {
        "csm_note",
        "support_ticket",
        "external_event",
    }
    assert requirements.require_corroboration
    assert requirements.maximum_age_days == 365


def test_grader_reports_relevance_corroboration_source_and_staleness_gaps() -> None:
    """Every documented retry trigger is represented by a structured reason."""

    old = _citation(score=0.8, doc_date=CUTOFF - timedelta(days=500))
    low_score = _citation(
        child_id="TCK-1#c000",
        parent_id="TCK-1",
        doc_type="support_ticket",
        score=0.2,
    )
    requirements = RetrievalRequirements(
        required_source_families=("csm_note", "external_event"),
        require_corroboration=True,
        maximum_age_days=365,
    )
    grade = DeterministicRetrievalGrader().grade(_result(old, low_score), requirements)
    assert grade.needs_retry
    assert grade.insufficient_evidence
    assert grade.missing_required_sources == ("external_event",)
    assert low_score.child_id in grade.rejected_citation_ids
    assert any("two independent" in reason for reason in grade.reasons)
    assert any("older than" in reason for reason in grade.reasons)


def test_grader_accepts_two_relevant_independent_required_sources() -> None:
    """Sufficient evidence terminates without spending the retry."""

    note = _citation()
    ticket = _citation(
        child_id="TCK-1#c000",
        parent_id="TCK-1",
        doc_type="support_ticket",
        score=0.75,
    )
    requirements = RetrievalRequirements(
        required_source_families=("csm_note", "support_ticket"),
        require_corroboration=True,
    )
    grade = DeterministicRetrievalGrader().grade(_result(note, ticket), requirements)
    assert not grade.needs_retry
    assert not grade.insufficient_evidence
    assert not grade.reasons


def test_rewriter_targets_missing_sources_and_is_bounded() -> None:
    """A rewrite preserves the original intent and adds only diagnosed domain terms."""

    grade = RetrievalGrade(
        missing_required_sources=("external_event",),
        reasons=("required source coverage missing: external_event",),
        needs_retry=True,
        insufficient_evidence=True,
    )
    query = "What changed?"
    rewritten = DeterministicQueryRewriter().rewrite(query, grade)
    assert rewritten.startswith(query)
    assert "external event" in rewritten
    assert len(rewritten) <= MAX_REWRITTEN_QUERY_CHARACTERS

    very_long = "q" * MAX_REWRITTEN_QUERY_CHARACTERS
    assert len(DeterministicQueryRewriter().rewrite(very_long, grade)) == (
        MAX_REWRITTEN_QUERY_CHARACTERS
    )


def test_parent_context_window_contains_the_matched_excerpt() -> None:
    """Long parents are bounded without losing the evidence-bearing child."""

    excerpt = "MATCHED EVIDENCE"
    parent = f"{'a' * 5_000}{excerpt}{'b' * 5_000}"
    context = _bounded_parent_context(parent, excerpt)
    assert excerpt in context
    assert len(context) <= 4_000


class _FakeEmbedding:
    """Stand-in for `fastembed.TextEmbedding` that records which path ran."""

    instances: ClassVar[list["_FakeEmbedding"]] = []

    def __init__(self, model_name: str, cache_dir: str | None = None) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        _FakeEmbedding.instances.append(self)

    def embed(self, texts: list[str], batch_size: int = 128) -> list[np.ndarray]:
        self.calls.append(("embed", tuple(texts)))
        return [np.full(EMBEDDING_DIMENSIONS, float(index + 1)) for index in range(len(texts))]

    def query_embed(self, texts: list[str]) -> list[np.ndarray]:
        self.calls.append(("query_embed", tuple(texts)))
        return [np.full(EMBEDDING_DIMENSIONS, 2.0) for _ in texts]


@pytest.fixture
def fake_fastembed(monkeypatch: pytest.MonkeyPatch) -> type[_FakeEmbedding]:
    """Install a fake fastembed module so no model is downloaded."""

    _FakeEmbedding.instances.clear()
    module = types.ModuleType("fastembed")
    module.TextEmbedding = _FakeEmbedding  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fastembed", module)
    return _FakeEmbedding


def test_documents_and_queries_use_their_own_bge_encoding_path(
    fake_fastembed: type[_FakeEmbedding],
) -> None:
    """BGE prefixes queries; using the document path instead quietly costs recall."""

    encoder = TextEncoder()
    encoder.encode_documents(["first passage", "second passage"])
    encoder.encode_queries(["why is this account at risk"])

    (model,) = fake_fastembed.instances
    assert model.model_name == EMBEDDING_MODEL_ID
    assert [name for name, _ in model.calls] == ["embed", "query_embed"]


def test_the_model_loads_once_and_only_when_text_is_encoded(
    fake_fastembed: type[_FakeEmbedding],
) -> None:
    """The API imports this module at startup, so construction must stay cheap."""

    encoder = TextEncoder()
    assert not fake_fastembed.instances
    encoder.encode_documents(["one"])
    encoder.encode_queries(["two"])
    assert len(fake_fastembed.instances) == 1


def test_embeddings_are_unit_length_so_inner_product_is_cosine(
    fake_fastembed: type[_FakeEmbedding],
) -> None:
    """The FAISS index scores with inner product and assumes normalised rows."""

    vectors = TextEncoder().encode_documents(["a", "b"])
    assert vectors.dtype == np.float32
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)


def test_a_zero_vector_normalises_without_dividing_by_zero() -> None:
    """An empty or unrepresentable passage must not produce NaN scores."""

    normalised = normalize(np.zeros((1, EMBEDDING_DIMENSIONS)))
    assert not np.isnan(normalised).any()
    assert float(np.linalg.norm(normalised)) == 0.0
