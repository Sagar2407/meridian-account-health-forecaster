#!/usr/bin/env python3
"""Compare linear adjudication with the conflict-gated Tree-of-Thought search.

Plan section 15.7. Both arms run over the same conflicting accounts with the
same evidence, differing only in where the conflict gate routes, and the result
is written to `artifacts/tot/` so the final report can quote it rather than
assert it.

The run is offline by default: no provider means no tokens and no cost, and the
comparison still measures what the *structure* changes, which is the question
section 15.7 asks. Pass `--use-provider` to include model-written candidate
rationales, which costs money.
"""

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend" / "src"))
sys.path.insert(0, str(REPOSITORY_ROOT / "evaluation"))

from meridian.data.splits import read_split  # noqa: E402
from meridian.graph.runtime import GraphRuntime  # noqa: E402
from meridian.settings import Settings, get_settings  # noqa: E402
from meridian_eval.repository import EvaluationRepository  # noqa: E402
from meridian_eval.tot_ablation import comparison, run_ablation  # noqa: E402

ARTIFACT_DIRECTORY = REPOSITORY_ROOT / "artifacts" / "tot"


def _parser() -> argparse.ArgumentParser:
    """Build the command-line contract."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accounts", type=int, help="Scan only the first N accounts of the split")
    parser.add_argument(
        "--split",
        choices=("development", "train", "validation", "test", "all"),
        default="development",
        help=(
            "Which accounts to scan. Defaults to development (train + validation): "
            "section 22.7 forbids tuning against held-out outcomes, and this "
            "comparison exists to inform tuning"
        ),
    )
    parser.add_argument("--limit", type=int, help="Cap the conflicting subset both arms run over")
    parser.add_argument(
        "--use-provider",
        action="store_true",
        help="Let a configured model write the candidate rationales; this costs money",
    )
    parser.add_argument(
        "--output", type=Path, default=ARTIFACT_DIRECTORY, help="Where to write artifacts"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run both arms and write the comparison."""

    args = _parser().parse_args(argv)
    settings: Settings = (
        get_settings() if args.use_provider else Settings(llm_provider="disabled", _env_file=None)
    )
    runtime = GraphRuntime.build(settings=settings)
    evaluation = EvaluationRepository()

    if args.split == "all":
        scanned = runtime.repository.account_ids()
    else:
        split = read_split()
        scanned = tuple(
            sorted(split.development if args.split == "development" else getattr(split, args.split))
        )
    if args.accounts:
        scanned = scanned[: args.accounts]

    print(
        f"scanning {len(scanned)} {args.split} accounts for material conflicts...",
        file=sys.stderr,
    )
    result = run_ablation(runtime, evaluation, scanned, limit=args.limit)
    report = comparison(result)

    report["split"] = args.split
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "tot_ablation.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    result.frame().to_csv(args.output / "tot_ablation_runs.csv", index=False)

    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"\nartifacts written to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
