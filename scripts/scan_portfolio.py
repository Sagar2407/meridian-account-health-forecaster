#!/usr/bin/env python3
"""Run one autonomous portfolio scan from the command line.

Plan section 18.2's CLI trigger. Selects accounts by renewal horizon, runs the
whole graph on each under fixed concurrency and a shared model-call budget, and
writes the summary to `artifacts/portfolio/`.

Offline by default: no provider means no tokens and no cost, and the scan's
structure -- selection, concurrency, routing, review load -- is what this
command exists to exercise. Pass `--use-provider` to let a configured model
write the narratives, which costs money and scales with the number of accounts.
"""

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend" / "src"))

import pandas as pd  # noqa: E402

from meridian.graph.runtime import GraphRuntime  # noqa: E402
from meridian.serving.scan import eligible_accounts, run_portfolio_scan  # noqa: E402
from meridian.settings import Settings, get_settings  # noqa: E402

ARTIFACT_DIRECTORY = REPOSITORY_ROOT / "artifacts" / "portfolio"


def _parser() -> argparse.ArgumentParser:
    """Build the command-line contract."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accounts", nargs="*", help="Scan these accounts instead of selecting")
    parser.add_argument("--horizon-days", type=int, help="Renewal horizon for eligibility")
    parser.add_argument("--limit", type=int, help="Cap how many accounts are scanned")
    parser.add_argument("--concurrency", type=int, help="How many runs execute at once")
    parser.add_argument(
        "--use-provider",
        action="store_true",
        help="Let a configured model write the narratives; this costs money per account",
    )
    parser.add_argument(
        "--output", type=Path, default=ARTIFACT_DIRECTORY, help="Where to write artifacts"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Select, scan, and write the summary."""

    args = _parser().parse_args(argv)
    settings: Settings = (
        get_settings() if args.use_provider else Settings(llm_provider="disabled", _env_file=None)
    )
    runtime = GraphRuntime.build(settings=settings)

    horizon = args.horizon_days or settings.scan_renewal_horizon_days
    cap = min(args.limit or settings.scan_max_accounts, settings.scan_max_accounts)
    if args.accounts:
        known = set(runtime.repository.account_ids())
        unknown = sorted(set(args.accounts) - known)
        if unknown:
            print(f"unknown accounts: {unknown}", file=sys.stderr)
            return 2
        selected = tuple(args.accounts)[:cap]
    else:
        selected = eligible_accounts(runtime.repository, horizon, limit=cap)

    if not selected:
        print(f"no account renews within {horizon} days; nothing to scan", file=sys.stderr)
        return 1

    print(
        f"scanning {len(selected)} account(s) at concurrency "
        f"{args.concurrency or settings.scan_concurrency}...",
        file=sys.stderr,
    )
    scan = run_portfolio_scan(runtime, selected, settings=settings, concurrency=args.concurrency)
    summary = scan.summary()

    args.output.mkdir(parents=True, exist_ok=True)
    report = {
        "scan_id": scan.scan_id,
        "status": scan.status,
        "started_at": scan.started_at,
        "finished_at": scan.finished_at,
        "horizon_days": horizon,
        "concurrency_limit": scan.request.concurrency,
        "model_call_budget": scan.request.model_call_budget,
        "skipped_for_budget": list(scan.skipped),
        **summary.as_dict(),
    }
    (args.output / "portfolio_scan.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    pd.DataFrame([record.__dict__ for record in scan.runs]).to_csv(
        args.output / "portfolio_scan_runs.csv", index=False
    )

    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"\nartifacts written to {args.output}", file=sys.stderr)

    # The Phase 8 exit gate, enforced rather than reported: a scan that exceeded
    # either bound must not exit zero.
    if summary.concurrency_observed > scan.request.concurrency:
        print(
            f"FAIL: observed concurrency {summary.concurrency_observed} exceeded the "
            f"configured limit {scan.request.concurrency}",
            file=sys.stderr,
        )
        return 1
    if summary.total_model_calls > scan.request.model_call_budget:
        print(
            f"FAIL: {summary.total_model_calls} model calls exceeded the budget "
            f"{scan.request.model_call_budget}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
