#!/usr/bin/env python3
"""Build sanitized runtime tables, the dataset manifest, and the account split.

Run with `make data`. Reads only the raw archive and writes only to ignored
directories under `data/`. The raw archive is never modified.
"""

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend" / "src"))
sys.path.insert(0, str(REPOSITORY_ROOT / "evaluation"))

from meridian.data.loader import load_raw_dataset  # noqa: E402
from meridian.data.manifest import build_manifest, write_manifest  # noqa: E402
from meridian.data.paths import processed_directory  # noqa: E402
from meridian.data.repository import assert_no_forbidden_fields  # noqa: E402
from meridian.data.sanitize import build_runtime_tables  # noqa: E402
from meridian_eval.splits import build_split, write_split  # noqa: E402


def main() -> int:
    """Materialize every Phase 1 artifact and report what was written."""

    print("[1/4] Loading and validating the raw archive")
    dataset = load_raw_dataset()
    row_counts = {
        name: len(dataset.table(name))
        for name in (
            "accounts",
            "usage_weekly",
            "support_tickets",
            "csm_notes",
            "external_events",
            "account_features",
            "renewal_outcomes",
        )
    }
    for name, count in row_counts.items():
        print(f"      {name:20s} {count:>6d} rows")

    print("[2/4] Writing sanitized runtime tables")
    destination = processed_directory()
    destination.mkdir(parents=True, exist_ok=True)
    for name, frame in build_runtime_tables(dataset).items():
        assert_no_forbidden_fields(frame, f"runtime table {name}")
        path = destination / f"{name}.parquet"
        frame.to_parquet(path, index=False)
        dropped = row_counts.get(name, len(frame)) - len(frame)
        suffix = f"  ({dropped} post-cutoff row(s) removed)" if dropped else ""
        print(f"      {path.name:28s} {len(frame):>6d} rows{suffix}")

    print("[3/4] Writing the dataset manifest")
    manifest_path = write_manifest(build_manifest(row_counts))
    print(f"      {manifest_path.name}")

    print("[4/4] Writing the deterministic account split")
    split, counts = build_split()
    split_path = write_split(split, counts)
    print(
        f"      {split_path.name}: {len(split.train)} train / "
        f"{len(split.validation)} validation / {len(split.test)} test"
    )
    for outcome, breakdown in sorted(counts.items()):
        print(f"      {outcome:12s} {breakdown}")

    print("\nData build complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
