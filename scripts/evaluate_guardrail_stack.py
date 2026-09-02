#!/usr/bin/env python3
"""Measure what each guardrail layer is worth (Checkpoint 6.1's second ablation).

Run with `make evaluate-guardrail-stack`. Four arms over the same 36 packaged
cases, differing only in how many guardrail layers run: none, intake only,
intake plus evidence screening, and the full stack that ships.

Offline and free: no provider is configured, so no tokens are spent, and the
guardrails being measured are deterministic anyway.

The exit status is a gate in the opposite direction from the usual one. The
full arm must still refuse every hard case -- if it does not, something has
broken and the ablation is measuring a bug rather than a design. It also fails
if removing every guardrail changes nothing, because an ablation where the arms
are indistinguishable is either measuring the wrong thing or reporting that the
guardrails do not work, and both deserve a non-zero exit rather than a table
nobody reads twice.
"""

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend" / "src"))
sys.path.insert(0, str(REPOSITORY_ROOT / "evaluation"))

from meridian.graph.runtime import GraphRuntime  # noqa: E402
from meridian.settings import Settings  # noqa: E402
from meridian_eval.guardrail_ablation import (  # noqa: E402
    ARM_LAYERS,
    ARMS,
    run_ablation,
)
from meridian_eval.guardrail_eval import load_cases  # noqa: E402

ARTIFACTS = REPOSITORY_ROOT / "artifacts" / "safety"


def main(argv: list[str] | None = None) -> int:
    """Run the four arms and write the comparison."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fallback-account",
        default="ACC-1000",
        help="Account for cases that name none of their own",
    )
    args = parser.parse_args(argv)

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    runtime = GraphRuntime.build(settings=Settings(llm_provider="disabled", _env_file=None))
    cases = load_cases()
    print(f"{len(cases)} packaged cases through {len(ARMS)} arms", file=sys.stderr)

    summary, frame = run_ablation(runtime, cases, args.fallback_account)

    print(
        f"\n{'arm':<18}{'hard false pass':>17}{'false block':>14}"
        f"{'answered':>10}{'unsupported':>13}"
    )
    for arm in ARMS:
        row = summary.get(arm)
        if row is None:
            continue
        print(
            f"{arm:<18}{row['hard_false_pass_rate']:>17.4f}{row['false_block_rate']:>14.4f}"
            f"{int(row['auto_answered']):>10}{int(row['unsupported_claim_count']):>13}"
        )

    frame.to_csv(ARTIFACTS / "guardrail_stack_runs.csv", index=False)
    (ARTIFACTS / "guardrail_stack.json").write_text(
        json.dumps(
            {"arms": summary, "layers": ARM_LAYERS, "cases": len(cases), "total_tokens": 0},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nartifacts written to {ARTIFACTS}", file=sys.stderr)

    full = summary.get("full")
    if full is None:
        print("the full arm produced no rows", file=sys.stderr)
        return 1
    if full["hard_false_pass_rate"] > 0:
        print(
            f"the shipped stack let {full['hard_false_pass_rate']:.4f} of hard cases through; "
            "the ablation is measuring a defect, not a design",
            file=sys.stderr,
        )
        return 1

    none = summary.get("none")
    if none is not None and none["hard_false_pass_rate"] == full["hard_false_pass_rate"]:
        print(
            "removing every guardrail changed no hard-case outcome. Either the arms are not "
            "actually different, or the refusals come from somewhere this ablation does not "
            "vary. Both need looking at before the table is quoted.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
