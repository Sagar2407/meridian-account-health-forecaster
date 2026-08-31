#!/usr/bin/env python3
"""Forecast one account deterministically, with no LLM involved.

Run with `make predict ACCOUNT=ACC-1042`. Every number printed here comes from
the calibrated model and the point-in-time feature builder; nothing is generated
text. Contributions describe what the model relied on, not proven causes.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend" / "src"))

from meridian.data.repository import RuntimeRepository, UnknownAccountError  # noqa: E402
from meridian.model.artifacts import load_artifact  # noqa: E402
from meridian.model.predict import predict_account  # noqa: E402


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """Return parsed command-line arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("account_id", help="Account to forecast, e.g. ACC-1042")
    parser.add_argument(
        "--cutoff",
        type=date.fromisoformat,
        default=None,
        help="Optional earlier cutoff for backtesting; clamped to the account's own.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Print a forecast for one account."""

    arguments = parse_arguments(argv)
    repository = RuntimeRepository()
    try:
        profile = repository.profile(arguments.account_id)
    except UnknownAccountError:
        print(f"Unknown account {arguments.account_id!r}", file=sys.stderr)
        return 2

    forecast = predict_account(load_artifact(), repository, arguments.account_id, arguments.cutoff)

    if arguments.json:
        print(
            json.dumps(
                {
                    "account_id": forecast.account_id,
                    "cutoff": forecast.cutoff.isoformat(),
                    "predicted_outcome": forecast.predicted_outcome,
                    "confidence": forecast.confidence,
                    "probabilities": forecast.probabilities,
                    "coverage": forecast.coverage,
                    "model": forecast.model_name,
                    "top_contributions": [
                        {
                            "feature": item.feature,
                            "value": item.value,
                            "contribution": item.contribution,
                            "direction": item.direction,
                        }
                        for item in forecast.top_contributions(5)
                    ],
                },
                indent=2,
            )
        )
        return 0

    print(f"{profile.account_name}  ({forecast.account_id})")
    print(f"  {profile.segment} / {profile.industry} / {profile.region}")
    print(f"  evidence cutoff {forecast.cutoff}, renewal {profile.renewal_date}")
    print(f"\nForecast: {forecast.predicted_outcome}  (confidence {forecast.confidence:.1%})")
    print("\n  outcome probabilities")
    for outcome, probability in sorted(forecast.probabilities.items(), key=lambda item: -item[1]):
        bar = "#" * round(probability * 40)
        print(f"    {outcome:12s} {probability:6.1%}  {bar}")

    print("\n  strongest contributions")
    for item in forecast.top_contributions(5):
        label = f"{item.feature:26s} {item.value:10.3f}"
        print(f"    {label}  {item.direction:8s} {item.contribution:+.3f}")

    print("\n  evidence coverage")
    for key, value in sorted(forecast.coverage.items()):
        print(f"    {key:34s} {value}")

    print(f"\n  model: {forecast.model_name} (deterministic; no language model involved)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
