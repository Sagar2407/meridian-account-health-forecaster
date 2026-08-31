"""Parent-child versus fixed-length chunking (plan section 11.6).

The ablation holds the corpus, encoder, metadata filters, top-k, and queries
constant, and varies only how parents are split. Anything else would confound
the comparison.

Both arms are built into temporary index directories so neither disturbs the
served index.
"""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from meridian.data.repository import RuntimeRepository
from meridian.retrieval.chunking import chunk_documents, fixed_length_chunks
from meridian.retrieval.documents import ParentDocument
from meridian.retrieval.embedding import TextEncoder
from meridian.retrieval.index import build_index, load_index
from meridian.retrieval.search import RetrievalService
from meridian_eval.retrieval_benchmark import BenchmarkQuery, run_benchmark, summarise

PARENT_CHILD = "parent_child"
FIXED_LENGTH = "fixed_length"


@dataclass(frozen=True)
class AblationArm:
    """One chunking strategy and the measurements it produced."""

    strategy: str
    chunk_count: int
    metrics: dict[str, float]


def run_ablation(
    parents: list[ParentDocument],
    queries: list[BenchmarkQuery],
    repository: RuntimeRepository,
    workspace: Path,
    encoder: TextEncoder | None = None,
) -> tuple[list[AblationArm], pd.DataFrame]:
    """Build both chunking arms, run the benchmark on each, and compare.

    Returns:
        The per-arm summaries and a tidy frame suitable for a report table.
    """

    shared_encoder = encoder if encoder is not None else TextEncoder()
    arms: list[AblationArm] = []

    strategies = {
        PARENT_CHILD: chunk_documents(parents),
        FIXED_LENGTH: fixed_length_chunks(parents),
    }

    for strategy, chunks in strategies.items():
        directory = workspace / strategy
        directory.mkdir(parents=True, exist_ok=True)
        build_index(parents, chunks, directory, shared_encoder, strategy=strategy)
        index = load_index(directory)
        service = RetrievalService(index, repository, shared_encoder)
        outcomes = run_benchmark(service, queries)
        arms.append(
            AblationArm(
                strategy=strategy,
                chunk_count=len(chunks),
                metrics=summarise(outcomes),
            )
        )

    frame = pd.DataFrame(
        [{"strategy": arm.strategy, "chunks": arm.chunk_count, **arm.metrics} for arm in arms]
    )
    return arms, frame
