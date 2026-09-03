#!/usr/bin/env python3
"""Run the retrieval benchmark and the chunking ablation.

Run with `make evaluate-retrieval`. Requires an index built by `make index`.

The per-query and per-arm detail goes to CSV, and the headline numbers also go to
`retrieval_benchmark.json`, which is what `GET /api/evaluations/retrieval` reads.
Without that file the endpoint reported this evaluation as never run while the
CSVs sat beside it.
"""

import argparse
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend" / "src"))
sys.path.insert(0, str(REPOSITORY_ROOT / "evaluation"))

from meridian.data.repository import RuntimeRepository  # noqa: E402
from meridian.retrieval.documents import build_parent_documents  # noqa: E402
from meridian.retrieval.embedding import TextEncoder  # noqa: E402
from meridian.retrieval.index import load_verified_index  # noqa: E402
from meridian.retrieval.search import RetrievalService  # noqa: E402
from meridian_eval.chunking_ablation import run_ablation  # noqa: E402
from meridian_eval.retrieval_benchmark import (  # noqa: E402
    build_benchmark,
    golden_assessment_accounts,
    run_benchmark,
    summarise,
)

ARTIFACTS = REPOSITORY_ROOT / "artifacts" / "retrieval"


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """Return the command-line options."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full-corpus",
        action="store_true",
        help=(
            "Run the chunking ablation over all 260 accounts instead of the 18 "
            "benchmark accounts. Adds roughly twenty minutes, because both arms "
            "embed the corpus. The published result is the default run; this "
            "answers whether the small-corpus gap survives at full scale."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ARTIFACTS,
        help="Directory for the result files (default: artifacts/retrieval).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Benchmark the served index, then compare chunking strategies."""

    options = parse_arguments(argv)
    artifacts = options.output
    artifacts.mkdir(parents=True, exist_ok=True)
    repository = RuntimeRepository()
    encoder = TextEncoder()

    print("[1/3] Running the curated benchmark against the served index")
    queries = build_benchmark(repository=repository)
    # Verified, not plain: benchmark numbers must describe the corpus this
    # code builds today, not whatever index happens to be on disk.
    service = RetrievalService(load_verified_index(repository), repository, encoder)
    outcomes = run_benchmark(service, queries)
    outcomes.to_csv(artifacts / "benchmark_results.csv", index=False)
    headline = summarise(outcomes)
    for key, value in headline.items():
        print(f"      {key:28s} {value:10.4f}")

    print("\n[2/3] Per-family recall")
    by_family = outcomes.groupby("family")[
        ["recall_at_5", "precision_at_5", "reciprocal_rank", "ndcg"]
    ].mean()
    print(by_family.to_string())
    by_family.to_csv(artifacts / "benchmark_by_family.csv")

    print("\n[3/3] Chunking ablation: parent-child against fixed length")
    # Both arms are built over the benchmark accounts plus the knowledge base
    # rather than all 260 accounts. Embedding the full corpus twice would add
    # twenty minutes without changing what the comparison controls for: the
    # corpus, encoder, filters, top-k, and queries are identical across arms
    # either way. `--full-corpus` runs the wider one, because "the gap is small
    # and the corpus is small" is a fair objection to answer with a measurement
    # rather than an argument.
    ablation_accounts = (
        repository.account_ids() if options.full_corpus else golden_assessment_accounts()
    )
    parents = build_parent_documents(repository, ablation_accounts)
    print(f"      corpus: {len(parents)} documents from {len(ablation_accounts)} accounts")
    with tempfile.TemporaryDirectory() as workspace:
        _, frame = run_ablation(parents, queries, repository, Path(workspace), encoder)
    columns = [
        "strategy",
        "chunks",
        "graded_queries",
        "recall_at_5",
        "precision_at_5",
        "mrr",
        "ndcg",
        "mean_returned",
    ]
    print(frame[columns].to_string(index=False))
    frame.to_csv(artifacts / "chunking_ablation.csv", index=False)

    violations = (
        headline["wrong_account_citations"]
        + headline["post_cutoff_citations"]
        + headline["forbidden_parent_citations"]
    )

    # The served summary. `summarise` can return NaN when nothing was graded,
    # and NaN is not JSON, so it becomes null rather than an unparseable file
    # the endpoint would report as unreadable.
    summary: dict[str, Any] = {
        key: None if isinstance(value, float) and math.isnan(value) else value
        for key, value in headline.items()
    }
    summary["safety_violations"] = int(violations)
    summary["by_family"] = json.loads(by_family.to_json(orient="index"))
    summary["chunking_ablation"] = json.loads(frame[columns].to_json(orient="records"))
    (artifacts / "retrieval_benchmark.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"\nSafety violations (wrong account + post cutoff + leaked future doc): {int(violations)}"
    )
    return 0 if violations == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
