"""Semantic retrieval over sanitized qualitative evidence (plan section 11).

Only text is indexed: CSM notes, support tickets, external events rendered as
short documents, and the knowledge base. Numeric telemetry and every latent or
outcome field are excluded by construction.
"""

from meridian.retrieval.chunking import ChildChunk, chunk_parent, fixed_length_chunks
from meridian.retrieval.contracts import Citation, RetrievalGrade, RetrievalResult
from meridian.retrieval.documents import ParentDocument, build_parent_documents
from meridian.retrieval.embedding import EMBEDDING_MODEL_ID, TextEncoder
from meridian.retrieval.index import RetrievalIndex, load_verified_index
from meridian.retrieval.search import RetrievalService

__all__ = [
    "EMBEDDING_MODEL_ID",
    "ChildChunk",
    "Citation",
    "ParentDocument",
    "RetrievalGrade",
    "RetrievalIndex",
    "RetrievalResult",
    "RetrievalService",
    "TextEncoder",
    "build_parent_documents",
    "chunk_parent",
    "fixed_length_chunks",
    "load_verified_index",
]
