#!/usr/bin/env python3
"""Record the curated runs the public demo replays (plan section 24.3).

Four runs, chosen by what they demonstrate rather than by account id: a
straightforward fast-path assessment, one whose evidence conflicts, one the
system declines to label, and one an intake guardrail refuses.

The accounts are **found, not hard-coded**. Which account conflicts depends on
its evidence, and an id pinned here would silently stop demonstrating what it
claims the first time the index or the conflict rules change. So this scans
until it has one of each, and says plainly if it could not find one.

Every recorded run comes from the real graph. Nothing here is written by hand:
a hand-written decision card is a mock-up, and a demo built on one is a lie
about what the system does.
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend" / "src"))

from meridian.api.routes.assessments import AssessmentState  # noqa: E402
from meridian.contracts import AssessmentRequest, ForecastDecision  # noqa: E402
from meridian.graph import AssessmentRun, build_graph, run_assessment  # noqa: E402
from meridian.graph.runtime import GraphRuntime  # noqa: E402
from meridian.serving.demo import (  # noqa: E402
    CURATED_KINDS,
    KIND_LABELS,
    CachedRun,
    write_cache,
)
from meridian.settings import Settings  # noqa: E402

DEMO_QUESTION = "What is the renewal outlook for this account, and what drives it?"

#: The refusal is deterministic and needs no search: any account will do, and
#: the question is what the guardrail refuses.
REFUSAL_QUESTION = "Rank our CSMs from best to worst and tell me which one to fire."


def _state(run: AssessmentRun) -> dict[str, object]:
    """Return the run projection the browser already knows how to render.

    Reusing `AssessmentState` rather than inventing a cache format means the
    demo page renders a recorded run through exactly the same component as a
    live one -- which is the point. A separate shape would be a second
    rendering path that nothing else exercises.
    """

    recorded = datetime.now(UTC).isoformat(timespec="seconds")
    state = AssessmentState(
        run_id=run.run_id,
        account_id=run.request.account_id,
        question=run.request.question,
        status="completed",
        started_at=recorded,
        finished_at=recorded,
        events_emitted=len(run.trace),
        last_event=run.trace[-1].event if run.trace else None,
        route=str(run.route) if run.route is not None else None,
        error=None,
        blocked=run.blocked.model_dump(mode="json") if run.blocked is not None else None,
        decision=run.result.model_dump(mode="json") if run.result is not None else None,
        guardrails=[decision.model_dump(mode="json") for decision in run.guardrails],
        trace=[event.model_dump(mode="json") for event in run.trace],
        assessment_id=run.assessment_id,
        review_case_id=run.review_case_id,
        total_tokens=run.total_tokens,
        model_calls=run.model_calls,
    )
    return state.model_dump(mode="json")


def _classify(run: AssessmentRun) -> str | None:
    """Return which curated slot this run fills, if any."""

    if run.blocked is not None:
        return "guardrail_refusal"
    if run.result is None:
        return None
    if not isinstance(run.result, ForecastDecision):
        return "insufficient_evidence"
    return "conflict" if run.events("conflict_detected") else "fast_path"


def main(argv: list[str] | None = None) -> int:
    """Find one run of each kind and write the cache."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", type=int, default=40, help="How many accounts to try")
    parser.add_argument("--output", type=Path, help="Where to write the cache")
    args = parser.parse_args(argv)

    runtime = GraphRuntime.build(settings=Settings(llm_provider="disabled", _env_file=None))
    graph = build_graph(runtime)
    accounts = runtime.repository.account_ids()[: args.scan]
    recorded: dict[str, CachedRun] = {}
    stamp = datetime.now(UTC).isoformat(timespec="seconds")

    commit = "unknown"
    head = REPOSITORY_ROOT / ".git" / "HEAD"
    if head.is_file():
        content = head.read_text(encoding="utf-8").strip()
        if content.startswith("ref:"):
            reference = REPOSITORY_ROOT / ".git" / content.removeprefix("ref:").strip()
            if reference.is_file():
                commit = reference.read_text(encoding="utf-8").strip()
        else:
            commit = content

    # The refusal first: it is deterministic and costs one intake check.
    refusal = run_assessment(
        graph,
        AssessmentRequest(account_id=accounts[0], question=REFUSAL_QUESTION),
        run_id="DEMO-refusal",
    )
    if refusal.blocked is not None:
        recorded["guardrail_refusal"] = CachedRun(
            kind="guardrail_refusal",
            label=KIND_LABELS["guardrail_refusal"],
            account_id=accounts[0],
            question=REFUSAL_QUESTION,
            recorded_at=stamp,
            commit=commit,
            route="blocked",
            payload=_state(refusal),
        )

    for account_id in accounts:
        if {"fast_path", "conflict", "insufficient_evidence"} <= set(recorded):
            break
        run = run_assessment(
            graph,
            AssessmentRequest(account_id=account_id, question=DEMO_QUESTION),
            run_id=f"DEMO-{account_id}",
        )
        kind = _classify(run)
        if kind is None or kind in recorded or kind == "guardrail_refusal":
            continue
        recorded[kind] = CachedRun(
            kind=kind,
            label=KIND_LABELS[kind],
            account_id=account_id,
            question=DEMO_QUESTION,
            recorded_at=stamp,
            commit=commit,
            route=str(run.route),
            payload=_state(run),
        )
        print(f"  recorded {kind}: {account_id} ({run.route})", file=sys.stderr)

    missing = [kind for kind in CURATED_KINDS if kind not in recorded]
    destination = write_cache(list(recorded.values()), commit, path=args.output)
    print(f"wrote {len(recorded)} curated run(s) to {destination}", file=sys.stderr)
    if missing:
        print(
            f"no run of these kinds was found in the first {args.scan} accounts: {missing}. "
            "The demo falls back to live runs for those.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
