#!/usr/bin/env python3
"""Run the 36 packaged guardrail cases and write the safety report.

Plan sections 22.4 and 23.4. Every case goes through the real graph, and the
result is written to `artifacts/safety/` so the final report can quote it rather
than assert it.

The run is offline by default: no provider means no tokens and no cost, and the
guardrails being measured are deterministic, so the numbers do not depend on a
model's mood. Pass `--use-provider` to let a configured model write the
narratives, which costs money.

The exit status is the gate. A hard-category false pass -- a privacy, HR,
leakage, commercial, out-of-domain, non-existent-account, missing-field, or
out-of-horizon request that was answered instead of refused -- exits non-zero,
so this can be wired into CI without anyone having to read the report to notice.
"""

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend" / "src"))
sys.path.insert(0, str(REPOSITORY_ROOT / "evaluation"))

import pandas as pd  # noqa: E402

from meridian.graph.runtime import GraphRuntime  # noqa: E402
from meridian.settings import Settings, get_settings  # noqa: E402
from meridian_eval.guardrail_eval import (  # noqa: E402
    SafetyReport,
    load_cases,
    run_guardrail_evaluation,
)

ARTIFACT_DIRECTORY = REPOSITORY_ROOT / "artifacts" / "safety"


def _parser() -> argparse.ArgumentParser:
    """Build the command-line contract."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="Run only the first N cases")
    parser.add_argument(
        "--use-provider",
        action="store_true",
        help="Let a configured model write the narratives; this costs money",
    )
    parser.add_argument(
        "--file-regressions",
        action="store_true",
        help=(
            "Record every false pass in application memory as a regression case "
            "(plan section 21.4) and export the whole set"
        ),
    )
    parser.add_argument(
        "--output", type=Path, default=ARTIFACT_DIRECTORY, help="Where to write artifacts"
    )
    return parser


def markdown(report: SafetyReport, offline: bool) -> str:
    """Render the safety report section 7's deliverable asks for."""

    metrics = report.metrics()
    lines = [
        "# Meridian safety report",
        "",
        f"Generated {metrics['generated_at']} from the {metrics['cases']} packaged "
        "guardrail cases in `data/raw/meridian-account-health/eval/guardrail_eval.jsonl`.",
        "",
        f"Provider: **{'none (deterministic run)' if offline else 'configured'}**. "
        f"Tokens spent: {metrics['total_tokens']}.",
        "",
        "## Plan section 22.4",
        "",
        "| Measure | Value |",
        "| --- | ---: |",
        f"| Hard-category false-pass rate | {metrics['hard_false_pass_rate']:.4f} |",
        f"| False-block rate (answerable cases) | {metrics['false_block_rate']:.4f} |",
        f"| Pass/block/escalate accuracy (within policy) | {metrics['disposition_accuracy']:.4f} |",
        f"| Exact expected-disposition match | {metrics['disposition_exact_match']:.4f} |",
        f"| Behaviour checks passed | {metrics['behaviour_pass_rate']:.4f} |",
        f"| Target-leakage, wrong-account, and post-cutoff citation findings | "
        f"{len(metrics['target_leakage_findings'])} |",
        "",
        f"Hard cases: {metrics['hard_cases']}. Answerable cases: {metrics['soft_cases']}.",
        "",
        "Observed dispositions: "
        + ", ".join(
            f"{count} {name}" for name, count in sorted(metrics["observed_dispositions"].items())
        )
        + ".",
        "",
        "The two accuracy rows differ, and the gap is the whole story rather than a "
        "rounding detail. "
        f"{len(metrics['escalated_behavioural_cases'])} behavioural case(s) "
        f"({', '.join(metrics['escalated_behavioural_cases']) or 'none'}) were answered "
        "*and* routed to a person. The packaged ideal response for those cases asks for "
        "human review, so an escalation is within policy and the first row counts it; the "
        "second row is the stricter reading that only an auto-released answer counts, and "
        "it is printed so the escalation rate cannot be hidden by the first. Cases outside "
        f"policy altogether: {metrics['out_of_policy'] or 'none'}.",
        "",
        "## By category",
        "",
        "| Category | Grading | Cases | Passed | Rate |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for name, bucket in sorted(metrics["by_category"].items()):
        grading = "hard (must refuse)" if bucket["hard"] else "behavioural"
        lines.append(
            f"| {name} | {grading} | {bucket['cases']} | {bucket['passed']} | "
            f"{bucket['pass_rate']:.2f} |"
        )

    lines += [
        "",
        "## Every case",
        "",
        "| Case | Category | Expected | Allowed | Observed | Pass | Detail |",
        "| --- | --- | --- | --- | --- | :---: | --- |",
    ]
    for row in report.rows():
        mark = "yes" if row["passed"] else "**NO**"
        lines.append(
            f"| {row['case_id']} | {row['category']} | {row['expected_behavior']} | "
            f"{'/'.join(row['allowed_dispositions'])} | {row['observed_disposition']} | "
            f"{mark} | {row['detail']} |"
        )

    failures = metrics["failures"]
    lines += ["", "## Failures", ""]
    if not failures:
        lines.append("None. Every case met the check printed beside it above.")
    else:
        for row in failures:
            lines.append(
                f"- **{row['case_id']}** ({row['category']}, "
                f"{'hard' if row['hard'] else 'behavioural'}): expected "
                f'`{row["expected_behavior"]}`; the check was "{row["check"]}" and the '
                f"system {row['detail']}."
            )
    lines += [
        "",
        "## How to read this",
        "",
        "Eight categories are graded as a binary refusal because anything else is a "
        "safety failure. Five are graded against a named behavioural check, printed "
        "beside each case so it can be argued with rather than trusted. Refusing every "
        "request would score 1.00 on the first group and 0.00 on the second, which is "
        "why the false-block rate is reported beside the false-pass rate.",
        "",
        f"Five cases name no account. They run against `{metrics['fallback_account']}`, "
        "a real account, so a case that is not refused shows up as a genuine answer "
        "rather than as an error.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run the cases, write the artifacts, and gate on the false-pass rate."""

    args = _parser().parse_args(argv)
    settings: Settings = (
        get_settings() if args.use_provider else Settings(llm_provider="disabled", _env_file=None)
    )
    runtime = GraphRuntime.build(settings=settings)

    cases = load_cases()
    if args.limit:
        cases = cases[: args.limit]

    print(f"running {len(cases)} guardrail cases through the graph...", file=sys.stderr)
    report = run_guardrail_evaluation(runtime, cases)
    metrics = report.metrics()

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "guardrail_eval.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    pd.DataFrame(report.rows()).to_csv(args.output / "guardrail_cases.csv", index=False)
    (args.output / "SAFETY_REPORT.md").write_text(
        markdown(report, offline=not args.use_provider), encoding="utf-8"
    )

    if args.file_regressions and runtime.store is not None:
        for result in report.hard_false_passes:
            runtime.store.record_regression(
                account_id=result.case.account_id or metrics["fallback_account"],
                origin="guardrail_false_pass",
                cutoff=runtime.repository.cutoff_for(
                    result.case.account_id or metrics["fallback_account"]
                ),
                question=result.case.question,
                system_outcome=result.disposition,
                reason_code="policy_requires_human_action",
                note=f"{result.case.case_id}: {result.detail}",
                confidence=0.0,
                route=result.route,
            )
        exported = runtime.store.export_regression_cases(args.output / "regression_cases.jsonl")
        print(f"exported {exported} regression case(s)", file=sys.stderr)

    print(
        json.dumps(
            {key: metrics[key] for key in sorted(metrics) if key != "by_category"},
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    print(f"\nartifacts written to {args.output}", file=sys.stderr)

    gate_failures: list[str] = []
    if report.hard_false_passes:
        gate_failures.append(
            f"{len(report.hard_false_passes)} hard-category false pass(es): "
            f"{[result.case.case_id for result in report.hard_false_passes]}"
        )
    if report.leakage_findings:
        gate_failures.append(f"{len(report.leakage_findings)} leakage finding(s)")
    if report.unclassified_categories:
        gate_failures.append(f"unclassified categories: {list(report.unclassified_categories)}")
    if gate_failures:
        print(
            "FAIL: " + "; ".join(gate_failures),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
