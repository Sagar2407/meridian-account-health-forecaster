"""The pinned embedding model (plan section 5, `BAAI/bge-small-en-v1.5`).

The model is served through ONNX rather than PyTorch. It is the same model and
the same weights, but the runtime is small enough to deploy without shipping a
multi-gigabyte image, which matters for the Phase 11 deployment target.

BGE distinguishes documents from queries: queries are encoded with an
instruction prefix. Using the wrong one silently degrades recall, so the two
paths are separate methods rather than a flag.
"""

from collections.abc import Iterable, Sequence

import numpy as np

EMBEDDING_MODEL_ID = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIMENSIONS = 384
DEFAULT_BATCH_SIZE = 128


def normalize(vectors: np.ndarray) -> np.ndarray:
    """Return L2-normalised rows, so inner product equals cosine similarity."""

    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    normalised: np.ndarray = (vectors / norms).astype(np.float32)
    return normalised


class TextEncoder:
    """Batch encoder over the pinned BGE model.

    The underlying model is loaded lazily so that importing this module, which
    the API does at startup, does not pay the model-load cost until something
    actually embeds text.
    """

    def __init__(self, model_id: str = EMBEDDING_MODEL_ID, cache_dir: str | None = None) -> None:
        self.model_id = model_id
        self._cache_dir = cache_dir
        self._model: object | None = None

    def _ensure_model(self) -> object:
        """Return the loaded model, loading it on first use."""

        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.model_id, cache_dir=self._cache_dir)
        return self._model

    def encode_documents(
        self, texts: Sequence[str], batch_size: int = DEFAULT_BATCH_SIZE
    ) -> np.ndarray:
        """Return normalised embeddings for corpus documents."""

        model = self._ensure_model()
        vectors: Iterable[np.ndarray] = model.embed(list(texts), batch_size=batch_size)  # type: ignore[attr-defined]
        return normalize(np.asarray(list(vectors), dtype=np.float32))

    def encode_queries(self, texts: Sequence[str]) -> np.ndarray:
        """Return normalised embeddings for search queries."""

        model = self._ensure_model()
        vectors: Iterable[np.ndarray] = model.query_embed(list(texts))  # type: ignore[attr-defined]
        return normalize(np.asarray(list(vectors), dtype=np.float32))
