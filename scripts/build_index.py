#!/usr/bin/env python3
"""Build the FAISS retrieval index from sanitized documents.

Run with `make index`. Only sanitized, cutoff-filtered text is indexed: CSM
notes, support tickets, external events rendered as evidence documents, and the
knowledge base. Numeric telemetry and every latent field are excluded.
"""

import sys
import time
from collections import Counter
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend" / "src"))

from meridian.data.repository import RuntimeRepository  # noqa: E402
from meridian.retrieval.chunking import chunk_documents  # noqa: E402
from meridian.retrieval.documents import build_parent_documents  # noqa: E402
from meridian.retrieval.index import build_index, indexes_directory  # noqa: E402


def main() -> int:
    """Build and persist the index, reporting corpus composition."""

    print("[1/3] Building sanitized parent documents")
    repository = RuntimeRepository()
    parents = build_parent_documents(repository)
    by_type = Counter(parent.doc_type for parent in parents)
    for name, count in sorted(by_type.items()):
        print(f"      {name:18s} {count:>6d} documents")
    print(f"      {'total':18s} {len(parents):>6d}")

    print("[2/3] Chunking parents into children")
    chunks = chunk_documents(parents)
    print(f"      {len(chunks)} chunks ({len(chunks) / max(len(parents), 1):.2f} per parent)")

    print("[3/3] Embedding and writing the index")
    started = time.time()
    manifest = build_index(parents, chunks)
    elapsed = time.time() - started
    print(f"      model      {manifest.embedding_model} ({manifest.dimensions} dims)")
    print(f"      version    {manifest.index_version}")
    print(f"      corpus     {manifest.corpus_digest[:16]}...")
    print(f"      embedded   {manifest.chunk_count} chunks in {elapsed:.1f}s")
    print(f"      written to {indexes_directory()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
