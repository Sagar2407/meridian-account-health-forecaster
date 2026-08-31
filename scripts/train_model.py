#!/usr/bin/env python3
"""Train, select, calibrate, and persist the account-health forecaster.

Run with `make train`. Reads the training and validation splits only; the
held-out test split is reserved for the final evaluation command.
"""

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend" / "src"))
sys.path.insert(0, str(REPOSITORY_ROOT / "evaluation"))

from meridian_eval.training import run_training  # noqa: E402


def main() -> int:
    """Run training and print a comparison table."""

    print("Training the account-health forecaster")
    report = run_training()

    print(f"\n{'candidate':22s} {'macro F1':>10s} {'sd':>8s} {'log loss':>10s} {'accuracy':>10s}")
    for candidate in sorted(report.candidates, key=lambda item: -item.macro_f1_mean):
        marker = " <- selected" if candidate.name == report.selected else ""
        print(
            f"{candidate.name:22s} {candidate.macro_f1_mean:10.4f} "
            f"{candidate.macro_f1_std:8.4f} {candidate.log_loss_mean:10.4f} "
            f"{candidate.accuracy_mean:10.4f}{marker}"
        )

    print("\nValidation split, calibrated:")
    for key, value in sorted(report.validation_metrics.items()):
        print(f"  {key:28s} {value:10.4f}")
    print("\nValidation split, uncalibrated:")
    for key, value in sorted(report.uncalibrated_metrics.items()):
        print(f"  {key:28s} {value:10.4f}")

    print(f"\nArtifact: {report.artifact_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
