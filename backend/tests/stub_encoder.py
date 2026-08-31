"""A deterministic offline stand-in for the BGE encoder, shared by tests.

Two test modules need a real index built without downloading a model: the
retrieval suite and the tool-layer suite. Keeping one implementation here means
they cannot drift into testing subtly different behaviour.

The encoder must produce *graded* similarity, not noise. An encoder mapping each
text to an independent random direction leaves every score near zero in 384
dimensions, nothing clears `MINIMUM_SCORE`, and any test that iterates over the
returned citations passes against an empty list -- reporting success while
proving nothing.
"""

import hashlib
import re
from pathlib import Path

import numpy as np

from meridian.data.repository import RuntimeRepository
from meridian.retrieval.chunking import chunk_documents
from meridian.retrieval.documents import build_parent_documents
from meridian.retrieval.embedding import EMBEDDING_DIMENSIONS, normalize
from meridian.retrieval.index import build_index, load_index
from meridian.retrieval.search import RetrievalService

#: Account-health vocabulary the stub treats as shared topics. Overlap on these
#: terms is what lifts a query and a passage into the same region of the space,
#: standing in for what the real BGE model learns.
STUB_TOPICS: tuple[tuple[str, ...], ...] = (
    ("risk", "risky", "churn", "churning", "cancel", "cancellation"),
    ("renewal", "renew", "renewing", "contract", "term"),
    ("adoption", "adopt", "usage", "active", "seats", "licenses"),
    ("decline", "declining", "drop", "dropped", "down", "decrease"),
    ("sponsor", "champion", "executive", "stakeholder", "departure"),
    ("escalation", "escalated", "outage", "incident", "severity", "sev"),
    ("support", "ticket", "bug", "defect", "unresolved", "backlog"),
    ("expansion", "upsell", "growth", "expand"),
    ("onboarding", "training", "enablement", "workshop"),
    ("integration", "api", "migration", "deployment"),
    ("pricing", "budget", "cost", "discount", "invoice"),
    ("event", "news", "acquisition", "funding", "layoff", "earnings"),
    ("qbr", "review", "meeting", "call", "sync"),
    ("play", "playbook", "save", "remediation", "mitigation"),
    ("satisfaction", "csat", "nps", "sentiment", "feedback"),
    ("outlook", "forecast", "trend", "trajectory", "health"),
)
STUB_TOPIC_WEIGHT = 1.0
STUB_TOKEN_WEIGHT = 0.12
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class StubEncoder:
    """A deterministic lexical encoder with the real encoder's interface.

    The leading dimensions score presence of the shared topic vocabulary above,
    which gives related text genuinely high cosine similarity. The remaining
    dimensions carry a low-weight hashed bag of words, so unrelated passages
    stay well apart and no two documents collapse onto the same direction.
    """

    model_id = "BAAI/bge-small-en-v1.5"

    def _vector(self, text: str) -> np.ndarray:
        vector = np.zeros(EMBEDDING_DIMENSIONS)
        tokens = set(_TOKEN_PATTERN.findall(text.lower()))
        for position, topic in enumerate(STUB_TOPICS):
            if tokens.intersection(topic):
                vector[position] = STUB_TOPIC_WEIGHT
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = len(STUB_TOPICS) + (
                int.from_bytes(digest[:8], "big") % (EMBEDDING_DIMENSIONS - len(STUB_TOPICS))
            )
            vector[bucket] += STUB_TOKEN_WEIGHT
        return vector

    def encode_documents(self, texts: list[str], batch_size: int = 128) -> np.ndarray:
        return normalize(np.vstack([self._vector(text) for text in texts]))

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        return normalize(np.vstack([self._vector(text) for text in texts]))


def build_stub_service(
    repository: RuntimeRepository, directory: Path, accounts: tuple[str, ...]
) -> RetrievalService:
    """Build a small index over `accounts` and return a service over it."""

    parents = build_parent_documents(repository, accounts)
    chunks = chunk_documents(parents)
    encoder = StubEncoder()
    build_index(parents, chunks, directory, encoder)  # type: ignore[arg-type]
    return RetrievalService(load_index(directory), repository, encoder)  # type: ignore[arg-type]
