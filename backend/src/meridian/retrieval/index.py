"""FAISS index build, persistence, and manifest checking (plan section 11.3).

Vectors are L2-normalised and stored in a flat inner-product index, which makes
inner product equal cosine similarity and keeps results exactly reproducible --
no approximate structure, no training randomness, at this corpus size.

The manifest records the corpus hash, the embedding model, and the chunking
strategy. `load_index` refuses to serve an index whose manifest disagrees with
the corpus it is asked about, unless an explicit rebuild flag is set.
"""

import hashlib
import json
import os
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from meridian.data.constants import DATASET_AS_OF_DATE, DATASET_VERSION
from meridian.data.paths import data_root
from meridian.data.repository import RuntimeRepository
from meridian.retrieval.chunking import (
    MAX_CHUNK_CHARACTERS,
    MIN_CHUNK_CHARACTERS,
    ChildChunk,
    chunk_documents,
)
from meridian.retrieval.documents import (
    TICKET_TYPE,
    ParentDocument,
    assert_no_latent_text,
    build_parent_documents,
)
from meridian.retrieval.embedding import EMBEDDING_MODEL_ID, TextEncoder
from meridian.retrieval.store import STORE_FILENAME, MetadataStore

INDEX_FILENAME = "chunks.faiss"
MANIFEST_FILENAME = "index_manifest.json"
CORPUS_MANIFEST_FILENAME = "corpus_manifest.json"
PARENT_CHILD_STRATEGY = "parent_child"
INDEX_SCHEMA_VERSION = 1
CORPUS_SCHEMA_VERSION = 1
METADATA_SCHEMA_VERSION = 2


class IndexManifestError(RuntimeError):
    """Raised when an index does not match the corpus it is asked to serve."""


@dataclass(frozen=True)
class IndexManifest:
    """What an index was built from, so drift is detectable."""

    embedding_model: str
    dimensions: int
    chunking_strategy: str
    corpus_digest: str
    parent_count: int
    chunk_count: int
    schema_version: int = INDEX_SCHEMA_VERSION
    index_version: str = ""
    corpus_manifest_digest: str = ""
    vectors_normalized: bool = True
    similarity: str = "cosine_via_inner_product"
    metadata_schema_version: int = METADATA_SCHEMA_VERSION

    def to_json(self) -> str:
        """Return stable, sorted JSON."""

        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True)
class CorpusManifest:
    """Versioned description of the exact sanitized corpus being embedded."""

    corpus_digest: str
    parent_count: int
    chunk_count: int
    parent_counts_by_source: dict[str, int]
    chunk_counts_by_source: dict[str, int]
    chunking_strategy: str
    schema_version: int = CORPUS_SCHEMA_VERSION
    dataset_version: str = DATASET_VERSION
    dataset_as_of_date: str = DATASET_AS_OF_DATE.isoformat()
    cutoff_policy: str = "min(forecast_as_of_date, dataset_as_of_date)"
    forbidden_fields_checked: bool = True
    minimum_chunk_characters: int = MIN_CHUNK_CHARACTERS
    maximum_chunk_characters: int = MAX_CHUNK_CHARACTERS

    def to_json(self) -> str:
        """Return stable, sorted JSON."""

        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"


def indexes_directory() -> Path:
    """Return the directory holding generated retrieval indexes."""

    return data_root() / "indexes"


def _json_safe(value: Any) -> Any:
    """Return a stable JSON value for dates and nested metadata."""

    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def corpus_digest(chunks: list[ChildChunk], parents: list[ParentDocument] | None = None) -> str:
    """Hash text and every field that governs filtering or parent return."""

    digest = hashlib.sha256()
    if parents is not None:
        for parent in parents:
            payload = _json_safe(asdict(parent))
            digest.update(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
            digest.update(b"\x02")
    for chunk in chunks:
        payload = _json_safe(asdict(chunk))
        digest.update(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
        digest.update(b"\x01")
    return digest.hexdigest()


def _validate_corpus(parents: list[ParentDocument], chunks: list[ChildChunk]) -> None:
    """Reject empty, duplicate, orphaned, or non-finite build inputs."""

    if not parents:
        raise ValueError("cannot build a retrieval index without parent documents")
    if not chunks:
        raise ValueError("cannot build a retrieval index without child chunks")
    parent_ids = [parent.doc_id for parent in parents]
    chunk_ids = [chunk.child_id for chunk in chunks]
    if len(parent_ids) != len(set(parent_ids)):
        raise ValueError("parent document ids must be unique")
    if len(chunk_ids) != len(set(chunk_ids)):
        raise ValueError("child chunk ids must be unique")
    unknown_parents = sorted({chunk.parent_id for chunk in chunks} - set(parent_ids))
    if unknown_parents:
        raise ValueError(f"chunks reference unknown parents: {unknown_parents[:5]}")
    if any(not chunk.text.strip() for chunk in chunks):
        raise ValueError("child chunks must contain non-empty text")
    assert_no_latent_text(parents)
    parents_by_id = {parent.doc_id: parent for parent in parents}
    for chunk in chunks:
        parent = parents_by_id[chunk.parent_id]
        if (
            chunk.doc_type != parent.doc_type
            or chunk.subtype != parent.subtype
            or chunk.account_id != parent.account_id
            or chunk.doc_date != parent.doc_date
        ):
            raise ValueError(f"chunk {chunk.child_id} does not inherit its parent scope")
        if chunk.account_id is not None and (chunk.segment is None or chunk.product is None):
            raise ValueError(f"account chunk {chunk.child_id} lacks segment/product metadata")
        if chunk.doc_type == TICKET_TYPE and chunk.source_severity is None:
            raise ValueError(f"ticket chunk {chunk.child_id} lacks severity metadata")


def _corpus_manifest(
    parents: list[ParentDocument], chunks: list[ChildChunk], strategy: str
) -> CorpusManifest:
    """Construct the persisted corpus manifest."""

    return CorpusManifest(
        corpus_digest=corpus_digest(chunks, parents),
        parent_count=len(parents),
        chunk_count=len(chunks),
        parent_counts_by_source=dict(sorted(Counter(p.doc_type for p in parents).items())),
        chunk_counts_by_source=dict(sorted(Counter(c.doc_type for c in chunks).items())),
        chunking_strategy=strategy,
    )


@dataclass(frozen=True)
class RetrievalIndex:
    """A loaded index with its metadata store and manifest."""

    faiss_index: object
    store: MetadataStore
    manifest: IndexManifest


def build_index(
    parents: list[ParentDocument],
    chunks: list[ChildChunk],
    directory: Path | None = None,
    encoder: TextEncoder | None = None,
    strategy: str = PARENT_CHILD_STRATEGY,
) -> IndexManifest:
    """Embed `chunks`, persist the FAISS index, store, and manifest."""

    import faiss

    target = directory if directory is not None else indexes_directory()
    target.parent.mkdir(parents=True, exist_ok=True)
    _validate_corpus(parents, chunks)

    text_encoder = encoder if encoder is not None else TextEncoder()
    vectors = text_encoder.encode_documents([chunk.text for chunk in chunks])
    if vectors.ndim != 2 or vectors.shape[0] != len(chunks) or vectors.shape[1] <= 0:
        raise ValueError("encoder returned an invalid embedding matrix shape")
    if not np.isfinite(vectors).all():
        raise ValueError("encoder returned non-finite embeddings")
    norms = np.linalg.norm(vectors, axis=1)
    if not np.allclose(norms, 1.0, atol=1e-4):
        raise ValueError("encoder embeddings must be L2-normalized")

    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    corpus_manifest = _corpus_manifest(parents, chunks, strategy)
    corpus_json = corpus_manifest.to_json()
    corpus_manifest_digest = hashlib.sha256(corpus_json.encode("utf-8")).hexdigest()
    model_slug = text_encoder.model_id.rsplit("/", maxsplit=1)[-1]
    manifest = IndexManifest(
        embedding_model=text_encoder.model_id,
        dimensions=int(vectors.shape[1]),
        chunking_strategy=strategy,
        corpus_digest=corpus_manifest.corpus_digest,
        parent_count=len(parents),
        chunk_count=len(chunks),
        index_version=(f"{model_slug}-{strategy}-{corpus_manifest.corpus_digest[:12]}"),
        corpus_manifest_digest=corpus_manifest_digest,
    )

    # Build complete files in a sibling staging directory. The serving manifest
    # is replaced last, so a failed build never advertises an incomplete set as
    # current.
    with tempfile.TemporaryDirectory(prefix=".retrieval-index-", dir=target.parent) as staging:
        stage = Path(staging)
        faiss.write_index(index, str(stage / INDEX_FILENAME))
        store = MetadataStore(stage / STORE_FILENAME)
        store.initialise()
        store.write(parents, chunks)
        (stage / CORPUS_MANIFEST_FILENAME).write_text(corpus_json, encoding="utf-8")
        (stage / MANIFEST_FILENAME).write_text(manifest.to_json(), encoding="utf-8")

        target.mkdir(parents=True, exist_ok=True)
        for filename in (INDEX_FILENAME, STORE_FILENAME, CORPUS_MANIFEST_FILENAME):
            os.replace(stage / filename, target / filename)
        os.replace(stage / MANIFEST_FILENAME, target / MANIFEST_FILENAME)
    return manifest


def read_manifest(directory: Path | None = None) -> IndexManifest:
    """Read an index manifest from disk."""

    target = directory if directory is not None else indexes_directory()
    path = target / MANIFEST_FILENAME
    if not path.is_file():
        raise FileNotFoundError(f"no index manifest at {path}; run `make index` first")
    return IndexManifest(**json.loads(path.read_text(encoding="utf-8")))


def read_corpus_manifest(directory: Path | None = None) -> CorpusManifest:
    """Read the sanitized-corpus manifest from disk."""

    target = directory if directory is not None else indexes_directory()
    path = target / CORPUS_MANIFEST_FILENAME
    if not path.is_file():
        raise FileNotFoundError(f"no corpus manifest at {path}; rebuild with `make index`")
    return CorpusManifest(**json.loads(path.read_text(encoding="utf-8")))


def load_index(
    directory: Path | None = None,
    expected_digest: str | None = None,
    allow_mismatch: bool = False,
) -> RetrievalIndex:
    """Load a persisted index, refusing a corpus mismatch by default.

    Args:
        directory: Where the index lives.
        expected_digest: Digest of the corpus the caller intends to serve. When
            given and different, the index is stale.
        allow_mismatch: Development escape hatch (plan section 11.3 step 8).

    Raises:
        IndexManifestError: If the manifest disagrees with `expected_digest`.
    """

    import faiss

    target = directory if directory is not None else indexes_directory()
    manifest = read_manifest(target)
    corpus_manifest_path = target / CORPUS_MANIFEST_FILENAME
    index_path = target / INDEX_FILENAME
    store_path = target / STORE_FILENAME

    if not all(path.is_file() for path in (corpus_manifest_path, index_path, store_path)):
        raise IndexManifestError(f"index at {target} is incomplete; rebuild with `make index`")
    corpus_json = corpus_manifest_path.read_text(encoding="utf-8")
    corpus_manifest = CorpusManifest(**json.loads(corpus_json))
    recorded_corpus_manifest_digest = hashlib.sha256(corpus_json.encode("utf-8")).hexdigest()
    if (
        not manifest.corpus_manifest_digest
        or manifest.corpus_manifest_digest != recorded_corpus_manifest_digest
        or manifest.corpus_digest != corpus_manifest.corpus_digest
    ) and not allow_mismatch:
        raise IndexManifestError("index and corpus manifests disagree; rebuild with `make index`")

    stale = expected_digest is not None and manifest.corpus_digest != expected_digest
    if stale and not allow_mismatch:
        raise IndexManifestError(
            f"index at {target} was built from corpus "
            f"{manifest.corpus_digest[:12]}... but the current corpus differs; "
            f"rebuild with `make index`"
        )
    if manifest.embedding_model != EMBEDDING_MODEL_ID and not allow_mismatch:
        raise IndexManifestError(
            f"index was built with {manifest.embedding_model}, "
            f"but this build pins {EMBEDDING_MODEL_ID}"
        )

    index = faiss.read_index(str(index_path))
    store = MetadataStore(store_path)
    counts = store.counts()
    structurally_stale = (
        int(index.ntotal) != manifest.chunk_count
        or int(index.d) != manifest.dimensions
        or counts["parents"] != manifest.parent_count
        or counts["chunks"] != manifest.chunk_count
        or corpus_manifest.parent_count != manifest.parent_count
        or corpus_manifest.chunk_count != manifest.chunk_count
    )
    if structurally_stale and not allow_mismatch:
        raise IndexManifestError(
            "index files do not match their manifest; rebuild with `make index`"
        )
    return RetrievalIndex(
        faiss_index=index,
        store=store,
        manifest=manifest,
    )


def search_rows(
    index: RetrievalIndex, query_vector: np.ndarray, allowed_rows: list[int], limit: int
) -> list[tuple[int, float]]:
    """Return `(row, score)` pairs restricted to `allowed_rows`, best first.

    The allowed set is scored directly rather than searched through FAISS with
    an id selector. After metadata filtering an account lane holds a few hundred
    chunks at most, so exact scoring costs nothing, and it keeps results
    deterministic and independent of FAISS search-parameter APIs that differ
    between index types and builds.
    """

    if not allowed_rows:
        return []
    vectors = np.vstack(
        [index.faiss_index.reconstruct(int(row)) for row in allowed_rows]  # type: ignore[attr-defined]
    )
    scores = vectors @ query_vector.reshape(-1)
    order = np.argsort(-scores)[: min(limit, len(allowed_rows))]
    return [(int(allowed_rows[position]), float(scores[position])) for position in order]


def load_verified_index(
    repository: RuntimeRepository,
    directory: Path | None = None,
    allow_mismatch: bool = False,
) -> RetrievalIndex:
    """Load the index only if it matches the corpus this code produces today.

    `load_index` can only detect drift when the caller supplies the digest of
    the corpus it means to serve, so a plain `load_index()` will happily serve
    an index built before a change to document rendering, chunking, or the
    dataset. Rebuilding the parents and chunks to compare costs seconds and no
    embedding, so anything that reports a number or answers a question pays it.

    Raises:
        IndexManifestError: If the served index was built from another corpus.
    """

    parents = build_parent_documents(repository)
    chunks = chunk_documents(parents)
    return load_index(
        directory,
        expected_digest=corpus_digest(chunks, parents),
        allow_mismatch=allow_mismatch,
    )
