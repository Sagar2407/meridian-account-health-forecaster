#!/usr/bin/env python3
"""Record the four representative traces the final report cites (plan section 12).

The report claims the system takes four different paths through the graph
depending on what the evidence supports. A claim like that is worth nothing
without the runs behind it, so this captures one of each and writes both the
raw run and a readable index:

* **Fast path** -- aligned evidence, one adjudication, released or queued.
* **Tree-of-Thought** -- the deterministic conflict gate fires and the bounded
  search runs instead of the single draft.
* **Degraded** -- a subsystem is unavailable, so the run returns verified
  telemetry with no categorical label rather than forecasting on half the
  evidence.
* **Human review** -- the run routes red, pauses on section 16.6's interrupt,
  and is resumed by a reviewer's typed override.

Two rules keep this honest.

**Accounts are found, not hard-coded.** Which account conflicts depends on its
evidence; an id pinned here would quietly stop demonstrating conflict the first
time the index or the gate changed, and the trace would still be captioned
"conflict". So this scans until it has one of each and says plainly what it
could not find.

**The degraded run is caused, not hunted for.** Waiting for an account whose
coverage happens to collapse would make the most important failure path the
least reproducible one. Instead the retrieval service is made genuinely
unavailable, which is the failure section 14.3 describes, and the graph is left
to do whatever it does. Nothing about the run is simulated: the same nodes run,
the same coverage gate reads the same lane report.

Everything runs offline (`llm_provider="disabled"`), so capturing costs nothing
and sends no prompt to a provider.
"""

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend" / "src"))

from meridian.contracts import (  # noqa: E402
    OUTCOME_CLASSES,
    AssessmentRequest,
    ForecastDecision,
    ReviewerDecision,
)
from meridian.data.repository import RuntimeRepository  # noqa: E402
from meridian.graph import (  # noqa: E402
    AssessmentRun,
    build_graph,
    resume_assessment,
    run_assessment,
    sqlite_checkpointer,
)
from meridian.graph.runtime import GraphRuntime  # noqa: E402
from meridian.memory.store import AssessmentStore  # noqa: E402
from meridian.model.artifacts import load_artifact  # noqa: E402
from meridian.tools.registry import ToolRegistry  # noqa: E402
from meridian.tools.services import ToolServices, ToolUnavailableError  # noqa: E402

QUESTION = "What is the renewal outlook for this account, and what drives it?"

#: What each captured trace is evidence *of*. The report cites these labels, so
#: they live next to the capture rather than being retyped into prose.
KINDS: dict[str, str] = {
    "fast_path": "Aligned evidence, single adjudication",
    "tot": "Conflicting evidence, bounded Tree-of-Thought",
    "degraded": "Retrieval unavailable, verified telemetry only",
    "human_review": "Red route, paused for a reviewer, resumed by an override",
}


def node_path(run: AssessmentRun) -> list[str]:
    """Return the graph nodes this run visited, in order, without repeats.

    A reader wants the shape of the path, not one entry per event, and the two
    evidence lanes emit several events each. Consecutive duplicates collapse;
    a genuine revisit -- the bounded retry cycle, or `fast_adjudication` re-run
    after a failed verification -- still shows twice, because that is the fact
    the trace exists to record.
    """

    path: list[str] = []
    for event in run.trace:
        if not path or path[-1] != event.node:
            path.append(event.node)
    return path


def summarize(run: AssessmentRun) -> dict[str, Any]:
    """Return the few numbers a report quotes, extracted rather than retyped."""

    summary: dict[str, Any] = {
        "route": str(run.route) if run.route is not None else None,
        "abstained": run.abstained,
        "events": len(run.trace),
        "model_calls": run.model_calls,
        "total_tokens": run.total_tokens,
        "guardrail_stages": [decision.stage for decision in run.guardrails],
        "node_path": node_path(run),
    }
    result = run.result
    if isinstance(result, ForecastDecision):
        summary["outcome"] = result.outcome
        summary["confidence"] = round(result.confidence, 4)
        summary["applied_caps"] = list(result.confidence_breakdown.applied_caps)
        summary["citations"] = [citation.doc_id for citation in result.citations]
        summary["counterevidence"] = [c.doc_id for c in result.counterevidence]
    elif result is not None:
        summary["outcome"] = None
        summary["gaps"] = list(result.gaps)
        summary["verified_metrics"] = len(result.verified_metrics)
    return summary


def record(run: AssessmentRun, kind: str, commit: str, stamp: str) -> dict[str, Any]:
    """Return the full trace document written to disk."""

    return {
        "kind": kind,
        "label": KINDS[kind],
        "account_id": run.request.account_id,
        "question": run.request.question,
        "recorded_at": stamp,
        "commit": commit,
        "offline": True,
        "summary": summarize(run),
        "run": {
            "run_id": run.run_id,
            "thread_id": run.thread_id,
            "assessment_id": run.assessment_id,
            "review_case_id": run.review_case_id,
            "result": run.result.model_dump(mode="json") if run.result else None,
            "blocked": run.blocked.model_dump(mode="json") if run.blocked else None,
            "reviewer_decision": (
                run.reviewer_decision.model_dump(mode="json") if run.reviewer_decision else None
            ),
            "guardrails": [d.model_dump(mode="json") for d in run.guardrails],
            "errors": [e.model_dump(mode="json") for e in run.errors],
            "trace": [e.model_dump(mode="json") for e in run.trace],
        },
    }


def head_commit() -> str:
    """Return the current commit, read from `.git` because the image has no git."""

    head = REPOSITORY_ROOT / ".git" / "HEAD"
    if not head.is_file():
        return "unknown"
    content = head.read_text(encoding="utf-8").strip()
    if not content.startswith("ref:"):
        return content
    reference = REPOSITORY_ROOT / ".git" / content.removeprefix("ref:").strip()
    return reference.read_text(encoding="utf-8").strip() if reference.is_file() else "unknown"


def offline_runtime(repository: RuntimeRepository, retrieval_available: bool) -> GraphRuntime:
    """Assemble a runtime with no provider, optionally with retrieval broken.

    The broken variant raises the same typed failure a missing index raises, so
    the degraded capture exercises the handling path that a real outage would,
    not a special case that exists only for this script.
    """

    def unavailable() -> Any:
        raise ToolUnavailableError(
            "the retrieval index is unavailable (captured deliberately for the "
            "degraded-path trace); build it with `make index`"
        )

    store = AssessmentStore()
    services = ToolServices(
        repository,
        retrieval=(lambda: _index(repository)) if retrieval_available else unavailable,
        store=store,
    )
    try:
        artifact = load_artifact()
    except (FileNotFoundError, OSError, ValueError):
        artifact = None
    return GraphRuntime.assemble(
        repository=repository,
        registry=ToolRegistry(services),
        artifact=artifact,
        generator=None,
        store=store,
    )


def _index(repository: RuntimeRepository) -> Any:
    """Build the real retrieval service, deferring the seconds it costs."""

    from meridian.graph.runtime import _retrieval_factory

    return _retrieval_factory(repository)


def _render(traces: dict[str, dict[str, Any]], missing: list[str], commit: str) -> str:
    """Render the readable index. Every number comes from the captured runs."""

    lines = [
        "# Representative traces",
        "",
        "Four runs, one per path through the assessment graph. They are captured by",
        "`make traces` (`scripts/capture_traces.py`), which runs offline: no provider is",
        "called, so re-capturing costs nothing and the narratives are the deterministic",
        "ones. Accounts are found by scanning, not pinned, so a trace labelled *conflict*",
        "is one the conflict gate actually fired on.",
        "",
        f"Captured at commit `{commit[:12]}`.",
        "",
        "| Path | Account | Route | Outcome | Confidence | Nodes | Events |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for kind in KINDS:
        trace = traces.get(kind)
        if trace is None:
            lines.append(f"| {kind} | _not captured_ | | | | | |")
            continue
        summary = trace["summary"]
        outcome = summary.get("outcome") or "none"
        confidence = summary.get("confidence")
        lines.append(
            f"| {kind} | `{trace['account_id']}` | {summary['route']} | {outcome} | "
            f"{confidence if confidence is not None else '--'} | "
            f"{len(summary['node_path'])} | {summary['events']} |"
        )

    for kind, label in KINDS.items():
        trace = traces.get(kind)
        if trace is None:
            continue
        summary = trace["summary"]
        lines += [
            "",
            f"## {kind}",
            "",
            f"{label}. Account `{trace['account_id']}`, `artifacts/traces/{kind}.json`.",
            "",
            "```text",
            " -> ".join(summary["node_path"]),
            "```",
            "",
        ]
        rows = [
            ("Route", summary["route"]),
            ("Outcome", summary.get("outcome") or "none (no categorical label)"),
            ("Confidence", summary.get("confidence", "--")),
            ("Model calls", summary["model_calls"]),
            ("Tokens", summary["total_tokens"]),
            ("Guardrail stages", ", ".join(summary["guardrail_stages"]) or "none"),
        ]
        if summary.get("applied_caps"):
            rows.append(("Confidence caps", ", ".join(summary["applied_caps"])))
        if summary.get("citations"):
            rows.append(("Citations", ", ".join(summary["citations"])))
        if summary.get("gaps"):
            rows.append(("Gaps", "; ".join(summary["gaps"])))
        if summary.get("verified_metrics") is not None and summary.get("outcome") is None:
            rows.append(("Verified metrics returned", summary["verified_metrics"]))
        decision = trace["run"]["reviewer_decision"]
        if decision:
            rows.append(("Reviewer action", f"{decision['action']} ({decision['reason_code']})"))
            rows.append(("Corrected outcome", decision["corrected_outcome"] or "--"))
        if trace["run"]["review_case_id"]:
            rows.append(("Review case", f"`{trace['run']['review_case_id']}`"))
        lines.append("| Field | Value |")
        lines.append("| --- | --- |")
        lines += [f"| {name} | {value} |" for name, value in rows]

    if missing:
        lines += [
            "",
            "## Not captured",
            "",
            "The scan did not reach a run of these kinds, so nothing here claims one: "
            + ", ".join(f"`{kind}`" for kind in missing)
            + ".",
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Capture one trace of each kind and write the artifacts."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", type=int, default=40, help="How many accounts to try")
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "artifacts" / "traces",
        help="Where to write the traces",
    )
    args = parser.parse_args(argv)

    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    commit = head_commit()
    repository = RuntimeRepository()
    accounts = repository.account_ids()[: args.scan]
    traces: dict[str, dict[str, Any]] = {}

    # The degraded path first: it is caused rather than searched for, so it
    # needs one run on the first account and no scan at all.
    broken = build_graph(offline_runtime(repository, retrieval_available=False))
    degraded = run_assessment(
        broken,
        AssessmentRequest(account_id=accounts[0], question=QUESTION),
        run_id="TRACE-degraded",
    )
    if degraded.result is not None and degraded.abstained:
        traces["degraded"] = record(degraded, "degraded", commit, stamp)
        print(f"  captured degraded: {accounts[0]} ({degraded.route})", file=sys.stderr)
    else:
        print(
            "  retrieval was unavailable but the run did not degrade; not recording a "
            f"degraded trace (route {degraded.route})",
            file=sys.stderr,
        )

    runtime = offline_runtime(repository, retrieval_available=True)
    with (
        tempfile.TemporaryDirectory() as scratch,
        sqlite_checkpointer(Path(scratch) / "traces.sqlite3") as saver,
    ):
        graph = build_graph(runtime, checkpointer=saver)
        for account_id in accounts:
            if {"fast_path", "tot", "human_review"} <= set(traces):
                break
            run = run_assessment(
                graph,
                AssessmentRequest(account_id=account_id, question=QUESTION),
                run_id=f"TRACE-{account_id}",
                pause_on_red=True,
            )
            if run.awaiting_review:
                if "human_review" in traces:
                    continue
                interrupt = run.interrupt
                assert interrupt is not None
                # The correction must differ from what the run proposed.
                # An override to the same label is not an override, and a
                # trace captioned "reviewer disagreed" that shows agreement
                # is worse than no trace at all.
                corrected = next(
                    outcome for outcome in OUTCOME_CLASSES if outcome != interrupt.proposed_outcome
                )
                resumed = resume_assessment(
                    graph,
                    run.thread_id,
                    ReviewerDecision(
                        case_id=interrupt.case_id,
                        reviewer="trace-capture",
                        action="override",
                        reason_code="evidence_contradicts_outcome",
                        note=(
                            "Captured for the final report: the reviewer replaces the "
                            "proposed outcome so the trace shows a resolved case and "
                            "its linked regression record."
                        ),
                        corrected_outcome=corrected,
                    ),
                )
                traces["human_review"] = record(resumed, "human_review", commit, stamp)
                print(
                    f"  captured human_review: {account_id} "
                    f"(paused on {interrupt.case_id}, resumed)",
                    file=sys.stderr,
                )
                continue
            if run.result is None or run.abstained:
                continue
            kind = "tot" if run.events("conflict_detected") else "fast_path"
            if kind in traces:
                continue
            traces[kind] = record(run, kind, commit, stamp)
            print(f"  captured {kind}: {account_id} ({run.route})", file=sys.stderr)

    args.output.mkdir(parents=True, exist_ok=True)
    for kind, trace in traces.items():
        path = args.output / f"{kind}.json"
        path.write_text(json.dumps(trace, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    missing = [kind for kind in KINDS if kind not in traces]
    (args.output / "TRACES.md").write_text(_render(traces, missing, commit), encoding="utf-8")

    print(f"wrote {len(traces)} trace(s) to {args.output}", file=sys.stderr)
    if missing:
        print(
            f"no run of these kinds appeared in the first {args.scan} accounts: {missing}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
