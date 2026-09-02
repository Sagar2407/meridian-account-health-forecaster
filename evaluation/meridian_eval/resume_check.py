"""Does a paused run actually resume? (ER-006)

Requirement ER-006 lists resume behaviour among the things the evaluation must
cover, and until now nothing measured it. The graph has an interrupt, the API
has a review endpoint, and there are unit tests for both -- but no published
number said that a red-routed run, paused mid-flight and handed a reviewer's
decision, comes back and finishes.

This measures exactly that, on a small sample and offline:

1. Run an account with `pause_on_red=True` until it stops on the interrupt.
2. Resume it with each of section 16.6's four reviewer actions in turn.
3. Record whether the run finished, whether the case was resolved, and how long
   the resume took.

The sample is small on purpose. Resume is a control-flow property -- it works or
it does not -- so a handful of accounts across the four actions answers the
question, and running the whole portfolio through four resumes each would cost
minutes to learn nothing more.
"""

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from meridian.contracts import (
    AssessmentRequest,
    RequestedData,
    ReviewerDecision,
)
from meridian.graph import resume_assessment, run_assessment

QUESTION = "What is the renewal outlook for this account, and what drives it?"

#: One decision per reviewer action (section 16.6). Each carries what its own
#: validator requires, so a rejected decision is a real failure rather than a
#: malformed test fixture.
ACTIONS: tuple[str, ...] = ("approve", "override", "request_data", "escalate")


@dataclass(frozen=True)
class ResumeRecord:
    """One paused run, resumed with one action."""

    account_id: str
    action: str
    paused: bool
    resumed: bool
    finished: bool
    case_resolved: bool
    detail: str
    latency_ms: float


def decision_for(action: str, case_id: str, proposed: str | None) -> ReviewerDecision:
    """Build a valid decision for one action."""

    if action == "override":
        corrected = "Churned" if proposed != "Churned" else "Renewed"
        return ReviewerDecision(
            case_id=case_id,
            reviewer="resume-check",
            action="override",
            reason_code="evidence_contradicts_outcome",
            note="Recorded by the resume check; the correction differs from the proposal.",
            corrected_outcome=corrected,
        )
    if action == "request_data":
        return ReviewerDecision(
            case_id=case_id,
            reviewer="resume-check",
            action="request_data",
            reason_code="coverage_insufficient",
            note="Recorded by the resume check.",
            requested_data=(
                RequestedData(
                    source="csm_notes",
                    detail="documented account activity for the quarter",
                    window="the 26 weeks before the cutoff",
                ),
            ),
        )
    if action == "escalate":
        return ReviewerDecision(
            case_id=case_id,
            reviewer="resume-check",
            action="escalate",
            reason_code="policy_requires_human_action",
            note="Recorded by the resume check.",
        )
    return ReviewerDecision(
        case_id=case_id,
        reviewer="resume-check",
        action="approve",
        reason_code="agrees_with_evidence",
        note="Recorded by the resume check.",
    )


def check_account(graph: Any, account_id: str, action: str) -> ResumeRecord:
    """Pause one run and resume it with one action."""

    started = time.perf_counter()
    paused = run_assessment(
        graph,
        AssessmentRequest(account_id=account_id, question=QUESTION),
        run_id=f"RESUME-{action}-{account_id}",
        pause_on_red=True,
    )
    if not paused.awaiting_review or paused.interrupt is None:
        # Not a failure: this account did not route red, so there was nothing to
        # pause. It is reported rather than retried, so the denominator stays
        # honest about how often a red route was actually available.
        return ResumeRecord(
            account_id=account_id,
            action=action,
            paused=False,
            resumed=False,
            finished=False,
            case_resolved=False,
            detail=f"did not pause; routed {paused.route}",
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
        )

    interrupt = paused.interrupt
    resume_started = time.perf_counter()
    try:
        resumed = resume_assessment(
            graph,
            paused.thread_id,
            decision_for(action, interrupt.case_id, interrupt.proposed_outcome),
        )
    except Exception as error:  # a failed resume is the finding, not a crash
        return ResumeRecord(
            account_id=account_id,
            action=action,
            paused=True,
            resumed=False,
            finished=False,
            case_resolved=False,
            detail=f"{type(error).__name__}: {error}",
            latency_ms=round((time.perf_counter() - resume_started) * 1000, 1),
        )

    return ResumeRecord(
        account_id=account_id,
        action=action,
        paused=True,
        resumed=True,
        finished=not resumed.awaiting_review,
        case_resolved=resumed.reviewer_decision is not None,
        detail=f"routed {resumed.route}",
        latency_ms=round((time.perf_counter() - resume_started) * 1000, 1),
    )


def summarise(records: Sequence[ResumeRecord]) -> dict[str, Any]:
    """Return what ER-006 asks about resume behaviour."""

    paused = [record for record in records if record.paused]
    by_action = {
        action: {
            "attempts": sum(1 for r in records if r.action == action),
            "paused": sum(1 for r in records if r.action == action and r.paused),
            "resumed": sum(1 for r in records if r.action == action and r.resumed),
            "finished": sum(1 for r in records if r.action == action and r.finished),
        }
        for action in ACTIONS
    }
    return {
        "attempts": len(records),
        "paused": len(paused),
        # Of the runs that actually paused, how many came back and finished.
        # An account that never routed red is excluded rather than counted as a
        # success, which would make the rate look better the less it was tested.
        "resume_rate": (
            round(sum(1 for r in paused if r.resumed) / len(paused), 4) if paused else None
        ),
        "completion_rate": (
            round(sum(1 for r in paused if r.finished) / len(paused), 4) if paused else None
        ),
        "case_resolution_rate": (
            round(sum(1 for r in paused if r.case_resolved) / len(paused), 4) if paused else None
        ),
        "mean_resume_latency_ms": (
            round(sum(r.latency_ms for r in paused) / len(paused), 1) if paused else None
        ),
        "by_action": by_action,
        "failures": [
            {"account_id": r.account_id, "action": r.action, "detail": r.detail}
            for r in paused
            if not r.finished
        ],
    }


def run_resume_check(
    graph: Any,
    account_ids: Sequence[str],
) -> tuple[dict[str, Any], list[ResumeRecord]]:
    """Pause and resume across the four reviewer actions."""

    records: list[ResumeRecord] = []
    for index, account_id in enumerate(account_ids):
        records.append(check_account(graph, account_id, ACTIONS[index % len(ACTIONS)]))
    return summarise(records), records


__all__ = [
    "ACTIONS",
    "ResumeRecord",
    "check_account",
    "decision_for",
    "run_resume_check",
    "summarise",
]
