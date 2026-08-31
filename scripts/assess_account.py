#!/usr/bin/env python3
"""Run one end-to-end account assessment through the LangGraph workflow.

This is the Phase 5 command-line deliverable. It streams safe trace events as
the graph produces them, prints the decision card, and leaves both the trace and
the decision persisted -- the checkpoint in SQLite, the assessment in
application memory.

The provider is whatever the environment configures. `--offline` forces the
deterministic path, which costs nothing and still exercises every node; use it
when you want to see the graph work rather than to see a model write.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend" / "src"))

from meridian.contracts import (  # noqa: E402
    AssessmentRequest,
    ForecastDecision,
    TraceEvent,
)
from meridian.data.repository import UnknownAccountError  # noqa: E402
from meridian.graph import (  # noqa: E402
    AssessmentRun,
    build_graph,
    run_assessment,
    sqlite_checkpointer,
)
from meridian.graph.runtime import GraphRuntime  # noqa: E402
from meridian.settings import Settings, get_settings  # noqa: E402

DEFAULT_QUESTION = "What is the renewal outlook for this account, and what drives it?"


def _iso_date(value: str) -> date:
    """Parse one strict ISO date for argparse."""

    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected an ISO date such as 2026-06-28") from error


def _parser() -> argparse.ArgumentParser:
    """Build the command-line contract."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("account_id", help="Synthetic Meridian account id, for example ACC-1042")
    parser.add_argument(
        "question", nargs="?", default=DEFAULT_QUESTION, help="What you want to know"
    )
    parser.add_argument(
        "--as-of",
        type=_iso_date,
        dest="requested_as_of",
        help="Optional earlier cutoff; a later date is clamped to the account cutoff",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Ignore any configured provider and use the deterministic narrative",
    )
    parser.add_argument(
        "--no-checkpoint",
        action="store_true",
        help="Do not persist resumable run state to SQLite",
    )
    parser.add_argument("--json", action="store_true", help="Print the run as JSON")
    return parser


def _print_event(event: TraceEvent) -> None:
    """Print one safe trace event as it happens."""

    print(
        f"  {event.node:<20} {event.event:<24} {event.latency_ms:>9.1f}ms",
        file=sys.stderr,
        flush=True,
    )


def _decision_card(run: AssessmentRun) -> str:
    """Render the run the way section 20.4's decision card presents it."""

    lines: list[str] = []
    if run.blocked is not None:
        return f"BLOCKED ({', '.join(run.blocked.reason_codes)})\n{run.blocked.message}"

    result = run.result
    if result is None:
        return "The run produced no result."

    lines.append(f"Account {result.account_id} at cutoff {result.cutoff.isoformat()}")
    lines.append(f"Route: {result.route.upper()} -- {result.route_reason}")
    lines.append("")

    if isinstance(result, ForecastDecision):
        ranked = sorted(result.distribution.items(), key=lambda item: -item[1])
        lines.append(f"Outcome: {result.outcome}  (confidence {result.confidence:.2f})")
        lines.append(
            "Distribution: " + ", ".join(f"{name} {value * 100:.1f}%" for name, value in ranked)
        )
        breakdown = result.confidence_breakdown
        lines.append(
            f"  = 0.70 x {breakdown.calibrated_probability:.3f} "
            f"+ 0.15 x {breakdown.coverage_score:.3f} "
            f"+ 0.15 x {breakdown.agreement_score:.3f}"
            + (f"  caps: {', '.join(breakdown.applied_caps)}" if breakdown.applied_caps else "")
        )
        lines.append("")
        lines.append(f"Rationale ({result.narrative_source}): {result.rationale}")
        lines.append("")
        lines.append("Drivers:")
        lines.extend(
            f"  {driver.direction:<8} {driver.feature} = {driver.value:g}"
            for driver in result.drivers
        )
        lines.append("")
        lines.append("Citations: " + (", ".join(c.doc_id for c in result.citations) or "none"))
        lines.append(
            "Counterevidence: " + (", ".join(c.doc_id for c in result.counterevidence) or "none")
        )
    else:
        lines.append("No categorical outcome: the evidence could not support one.")
        lines.append("")
        lines.append("Gaps:")
        lines.extend(f"  - {gap}" for gap in result.gaps)
        lines.append("")
        lines.append("Requested data:")
        lines.extend(
            f"  - {item.source}: {item.detail} ({item.window})" for item in result.requested_data
        )
        lines.append("")
        lines.append(f"Verified metrics: {len(result.verified_metrics)}")

    lines.append("")
    lines.append("Limitations:")
    lines.extend(f"  - {limitation}" for limitation in result.limitations)
    lines.append("")
    lines.append(f"Recommended action: {result.recommended_action}")
    if run.review_case_id:
        lines.append(f"Review case: {run.review_case_id}")
    return "\n".join(lines)


def _json_payload(run: AssessmentRun) -> dict[str, Any]:
    """Return the whole run as JSON-ready data."""

    return {
        "run_id": run.run_id,
        "thread_id": run.thread_id,
        "route": run.route,
        "abstained": run.abstained,
        "assessment_id": run.assessment_id,
        "review_case_id": run.review_case_id,
        "total_tokens": run.total_tokens,
        "blocked": run.blocked.model_dump(mode="json") if run.blocked else None,
        "result": run.result.model_dump(mode="json") if run.result else None,
        "errors": [error.model_dump(mode="json") for error in run.errors],
        "trace": [event.model_dump(mode="json") for event in run.trace],
    }


def main(argv: list[str] | None = None) -> int:
    """Assess one account and print the decision."""

    args = _parser().parse_args(argv)
    settings: Settings = (
        Settings(llm_provider="disabled", _env_file=None) if args.offline else get_settings()
    )

    try:
        runtime = GraphRuntime.build(settings=settings)
        request = AssessmentRequest(
            account_id=args.account_id,
            question=args.question,
            requested_as_of=args.requested_as_of,
        )
    except (UnknownAccountError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    provider = runtime.generator.model_name if runtime.generator is not None else "none"
    print(
        f"provider: {provider}; forecaster: "
        f"{'loaded' if runtime.has_forecaster else 'unavailable'}",
        file=sys.stderr,
    )

    if args.no_checkpoint:
        run = run_assessment(build_graph(runtime), request, on_event=_print_event)
    else:
        with sqlite_checkpointer() as saver:
            run = run_assessment(
                build_graph(runtime, checkpointer=saver), request, on_event=_print_event
            )

    if args.json:
        print(json.dumps(_json_payload(run), indent=2, sort_keys=True))
    else:
        print()
        print(_decision_card(run))
    return 0 if run.route != "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())
