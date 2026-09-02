#!/usr/bin/env python3
"""Run the full evaluation and write one immutable result directory.

Plan section 22. One pass over a split feeds forecast correctness, grounded
explanation, calibration, operational reliability, and the threshold study; the
safety routing block is read from the guardrail suite's own artifact when it has
been run.

**The split matters and is not defaulted carelessly.** Section 22.7 forbids
tuning on final held-out outcomes, so this defaults to the development split.
Pass `--split test` deliberately, once, when the thresholds are frozen and you
intend the result to be the held-out number.

Offline by default: no provider means no tokens and no cost, and every measure
here except narrative wording is deterministic either way. `--use-provider`
lets a configured model write the narratives, which costs money per account.
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
from meridian.graph.thresholds import THRESHOLDS  # noqa: E402
from meridian.settings import Settings, get_settings  # noqa: E402
from meridian_eval.report import assemble, publish_summary, write  # noqa: E402
from meridian_eval.repository import EvaluationRepository  # noqa: E402
from meridian_eval.system_run import collect_runs  # noqa: E402

GUARDRAIL_ARTIFACT = REPOSITORY_ROOT / "artifacts" / "safety" / "guardrail_eval.json"


def _parser() -> argparse.ArgumentParser:
    """Build the command-line contract."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--split",
        choices=("development", "train", "validation", "test"),
        default="development",
        help=(
            "Which accounts to evaluate. Defaults to development: section 22.7 "
            "forbids tuning on held-out outcomes, so `test` is a deliberate choice"
        ),
    )
    parser.add_argument("--limit", type=int, help="Evaluate only the first N accounts")
    parser.add_argument(
        "--use-provider",
        action="store_true",
        help="Let a configured model write the narratives; this costs money per account",
    )
    parser.add_argument("--output", type=Path, help="Write the result directory here")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Evaluate one split and write its result directory."""

    args = _parser().parse_args(argv)
    settings: Settings = (
        get_settings() if args.use_provider else Settings(llm_provider="disabled", _env_file=None)
    )
    runtime = GraphRuntime.build(settings=settings)

    split = read_split()
    accounts = tuple(sorted(getattr(split, args.split)))
    if args.limit:
        accounts = accounts[: args.limit]

    if args.split == "test":
        print(
            "Evaluating the HELD-OUT test split. Section 22.7: this result is only "
            f"meaningful because thresholds are frozen at {THRESHOLDS.digest()} "
            f"({THRESHOLDS.version}). Do not tune on what follows.",
            file=sys.stderr,
        )

    print(f"evaluating {len(accounts)} {args.split} accounts...", file=sys.stderr)

    def progress(done: int, total: int, account_id: str) -> None:
        """Print a single progress line every twenty accounts."""

        if done % 20 == 0 or done == total:
            print(f"  {done}/{total} ({account_id})", file=sys.stderr)

    collection = collect_runs(
        runtime,
        EvaluationRepository(),
        accounts,
        split=args.split,
        on_progress=progress,
    )

    guardrails = None
    if GUARDRAIL_ARTIFACT.is_file():
        try:
            guardrails = json.loads(GUARDRAIL_ARTIFACT.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            guardrails = {"reason": f"{GUARDRAIL_ARTIFACT} could not be read"}

    result = assemble(
        collection,
        provider="configured model" if args.use_provider else "none (deterministic)",
        guardrails=guardrails,
    )
    folder = write(result, collection, destination=args.output)
    # The served evaluation page reads one summary rather than globbing for the
    # newest timestamped directory, so publish this run into it. Skipped when
    # the caller redirected the output: a run written somewhere else is not the
    # published result and must not overwrite what is.
    if args.output is None:
        summary = publish_summary(result, folder)
        print(f"summary: {summary}", file=sys.stderr)

    targets = result["release_targets"]
    unmet = [row for row in targets if row["met"] is False]
    for row in targets:
        state = "met" if row["met"] else ("not measured" if row["met"] is None else "NOT MET")
        print(f"  {row['metric']}: {row['measured']} ({state})")
    print(f"\nresult directory: {folder}", file=sys.stderr)

    # A provisional target that was not met is a finding, not a failure: section
    # 22.6 calls these targets rather than gates, and exiting non-zero would
    # turn an honest measurement into something worth suppressing.
    if unmet:
        print(
            f"{len(unmet)} provisional target(s) not met: {[row['metric'] for row in unmet]}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
