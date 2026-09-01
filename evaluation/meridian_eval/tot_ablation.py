"""Linear adjudication versus conflict-gated Tree-of-Thought (plan section 15.7).

Section 15.7 asks one question and refuses to let it be answered by assertion:
"The final report must show whether the added complexity earned its place." So
both arms run over the same accounts, with the same evidence, differing only in
where the conflict gate routes.

The subset is the conflicting one, because that is the only place the two arms
can differ: on an aligned case the gate does not fire and both arms take the
fast path, so including aligned accounts would dilute every difference toward
zero and make the comparison look reassuring for the wrong reason.

This module lives in `meridian_eval` because it reads outcome labels. Nothing in
`meridian` imports it, and `test_import_boundary.py` fails the build if that
ever changes.
"""

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from meridian.contracts import AssessmentRequest, ForecastDecision
from meridian.graph import AssessmentRun, build_graph, run_assessment
from meridian.graph.builder import Adjudication
from meridian.graph.runtime import GraphRuntime
from meridian_eval.repository import EvaluationRepository

#: The question every ablation run asks, held constant so the two arms differ
#: only in their adjudication path.
ABLATION_QUESTION = "What is the renewal outlook for this account, and what drives it?"

#: Ground-truth driver names that the runtime computes under a different name.
#: The archive predates the recomputation of section 8.3, so one metric moved.
DRIVER_ALIASES: dict[str, str] = {"avg_csat": "avg_closed_csat_26w"}

#: Routes a human never sees before the answer is used.
AUTO_RELEASED_ROUTES = frozenset({"green", "amber"})


@dataclass(frozen=True)
class RunRecord:
    """One assessment, reduced to what the ablation compares."""

    account_id: str
    arm: str
    route: str
    released: bool
    outcome: str | None
    label: str | None
    correct: bool | None
    drivers: tuple[str, ...]
    driver_overlap: float
    verified_first_time: bool
    conflict_triggered: bool
    conflict_severity: str
    tot_ran: bool
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int

    @property
    def auto_released(self) -> bool:
        """Return whether this answer would reach a user without review."""

        return self.released and self.route in AUTO_RELEASED_ROUTES


@dataclass(frozen=True)
class ArmSummary:
    """One arm's aggregate behaviour over the conflicting subset."""

    arm: str
    runs: int
    released: int
    abstained: int
    accuracy: float | None
    auto_released: int
    auto_release_errors: int
    auto_release_error_rate: float | None
    escalation_rate: float
    supported_claim_rate: float
    driver_fidelity: float
    mean_latency_ms: float
    total_tokens: int

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-ready summary."""

        return {
            "arm": self.arm,
            "runs": self.runs,
            "released": self.released,
            "abstained": self.abstained,
            "accuracy": self.accuracy,
            "auto_released": self.auto_released,
            "auto_release_errors": self.auto_release_errors,
            "auto_release_error_rate": self.auto_release_error_rate,
            "escalation_rate": self.escalation_rate,
            "supported_claim_rate": self.supported_claim_rate,
            "driver_fidelity": self.driver_fidelity,
            "mean_latency_ms": self.mean_latency_ms,
            "total_tokens": self.total_tokens,
        }


@dataclass
class AblationResult:
    """Both arms plus the per-run records behind them."""

    arms: dict[str, ArmSummary] = field(default_factory=dict)
    records: list[RunRecord] = field(default_factory=list)
    conflicting_accounts: tuple[str, ...] = ()
    scanned_accounts: int = 0

    def frame(self) -> pd.DataFrame:
        """Return the per-run records as a frame for the artifact."""

        return pd.DataFrame([record.__dict__ for record in self.records])


def _truth_drivers(evaluation: EvaluationRepository) -> dict[str, set[str]]:
    """Return the generator's own top drivers per account, by feature name."""

    frame = evaluation.ground_truth_drivers()
    truth: dict[str, set[str]] = {}
    for record in frame.to_dict("records"):
        names: set[str] = set()
        for column in ("top_negative_drivers", "top_positive_drivers"):
            for entry in record.get(column) or []:
                name = str(entry.get("driver", ""))
                names.add(DRIVER_ALIASES.get(name, name))
        truth[str(record["account_id"])] = names
    return truth


def _overlap(reported: Sequence[str], truth: set[str]) -> float:
    """Return the share of reported drivers the generator also considered top.

    Precision rather than recall: the system shows a handful of drivers and the
    question is whether those are real, not whether it listed every one.
    """

    if not reported:
        return 0.0
    return len([name for name in reported if name in truth]) / len(reported)


def _record(
    run: AssessmentRun,
    arm: str,
    label: str | None,
    truth: set[str],
    latency_ms: float,
) -> RunRecord:
    """Reduce one run to a comparable record."""

    decision = run.result
    released = isinstance(decision, ForecastDecision)
    outcome = decision.outcome if isinstance(decision, ForecastDecision) else None
    drivers = (
        tuple(driver.feature for driver in decision.drivers)
        if isinstance(decision, ForecastDecision)
        else ()
    )
    verified = run.events("output_verified")
    conflict = run.events("conflict_detected")

    return RunRecord(
        account_id=run.request.account_id,
        arm=arm,
        route=str(run.route),
        released=released,
        outcome=outcome,
        label=label,
        correct=None if (outcome is None or label is None) else outcome == label,
        drivers=drivers,
        driver_overlap=_overlap(drivers, truth),
        # "Supported claim rate" in section 22.2 terms: the narrative's numbers
        # and citations replayed against verified evidence without a repair.
        verified_first_time=bool(verified) and bool(verified[0].payload.get("passed")),
        conflict_triggered=bool(conflict),
        conflict_severity=str(conflict[0].payload.get("severity")) if conflict else "none",
        tot_ran=bool(run.events("tot_started")),
        latency_ms=latency_ms,
        prompt_tokens=sum(event.prompt_tokens for event in run.trace),
        completion_tokens=sum(event.completion_tokens for event in run.trace),
    )


def _summarise(arm: str, records: Sequence[RunRecord]) -> ArmSummary:
    """Aggregate one arm's records."""

    runs = len(records)
    released = [record for record in records if record.released]
    judged = [record for record in released if record.correct is not None]
    auto = [record for record in released if record.auto_released]
    auto_errors = [record for record in auto if record.correct is False]
    escalated = [record for record in records if not record.auto_released]

    return ArmSummary(
        arm=arm,
        runs=runs,
        released=len(released),
        abstained=runs - len(released),
        accuracy=(
            len([record for record in judged if record.correct]) / len(judged) if judged else None
        ),
        auto_released=len(auto),
        auto_release_errors=len(auto_errors),
        auto_release_error_rate=(len(auto_errors) / len(auto) if auto else None),
        escalation_rate=len(escalated) / runs if runs else 0.0,
        # Measured over released answers only. An abstention writes no narrative,
        # so counting it as an unsupported claim would punish an arm for
        # declining -- which is the behaviour this whole system is built to make
        # possible.
        supported_claim_rate=(
            len([record for record in released if record.verified_first_time]) / len(released)
            if released
            else 1.0
        ),
        driver_fidelity=(
            sum(record.driver_overlap for record in released) / len(released) if released else 0.0
        ),
        mean_latency_ms=(sum(record.latency_ms for record in records) / runs if runs else 0.0),
        total_tokens=sum(record.prompt_tokens + record.completion_tokens for record in records),
    )


def conflicting_accounts(
    runtime: GraphRuntime, account_ids: Sequence[str]
) -> tuple[tuple[str, ...], list[RunRecord]]:
    """Return the accounts whose evidence the gate finds in material conflict.

    The scan runs the linear arm, so its records are reused rather than thrown
    away: every conflicting account has already been assessed once without the
    search, which is exactly the control arm.
    """

    graph = build_graph(runtime, adjudication="linear")
    conflicting: list[str] = []
    records: list[RunRecord] = []
    for account_id in account_ids:
        started = time.perf_counter()
        run = run_assessment(
            graph, AssessmentRequest(account_id=account_id, question=ABLATION_QUESTION)
        )
        latency = (time.perf_counter() - started) * 1000
        if run.events("conflict_detected"):
            conflicting.append(account_id)
            records.append(_record(run, "linear", None, set(), latency))
    return tuple(conflicting), records


def run_arm(
    runtime: GraphRuntime,
    account_ids: Sequence[str],
    adjudication: Adjudication,
    labels: pd.Series,
    truth: dict[str, set[str]],
) -> list[RunRecord]:
    """Run one arm over the conflicting subset."""

    graph = build_graph(runtime, adjudication=adjudication)
    records: list[RunRecord] = []
    for account_id in account_ids:
        started = time.perf_counter()
        run = run_assessment(
            graph, AssessmentRequest(account_id=account_id, question=ABLATION_QUESTION)
        )
        latency = (time.perf_counter() - started) * 1000
        label = str(labels[account_id]) if account_id in labels.index else None
        records.append(_record(run, adjudication, label, truth.get(account_id, set()), latency))
    return records


def run_ablation(
    runtime: GraphRuntime,
    evaluation: EvaluationRepository,
    account_ids: Sequence[str] | None = None,
    limit: int | None = None,
) -> AblationResult:
    """Compare linear adjudication with the conflict-gated search.

    Args:
        runtime: An assembled graph runtime.
        evaluation: The label-bearing repository, used only here.
        account_ids: Accounts to scan. Callers should pass the development
            split: section 22.7 forbids tuning against held-out outcomes, and a
            comparison whose whole purpose is to inform a threshold must not be
            measured on the test set.
        limit: Optional cap on the conflicting subset, for a quick pass.

    Returns:
        Both arms' summaries and every per-run record behind them.
    """

    scanned = tuple(account_ids or runtime.repository.account_ids())
    conflicting, _ = conflicting_accounts(runtime, scanned)
    if limit is not None:
        conflicting = conflicting[:limit]

    labels = evaluation.labels()
    truth = _truth_drivers(evaluation)

    records: list[RunRecord] = []
    arms: dict[str, ArmSummary] = {}
    for adjudication in ("linear", "conflict_gated"):
        arm_records = run_arm(
            runtime,
            conflicting,
            adjudication,
            labels,
            truth,
        )
        records.extend(arm_records)
        arms[adjudication] = _summarise(adjudication, arm_records)

    return AblationResult(
        arms=arms,
        records=records,
        conflicting_accounts=conflicting,
        scanned_accounts=len(scanned),
    )


def _paired(result: AblationResult) -> dict[str, Any]:
    """Compare the two arms on the accounts they both answered.

    Aggregate accuracy over different subsets is not a comparison: the gated arm
    abstains on the cases it finds hardest, so whatever it releases is an easier
    set by construction and would look better -- or, as it happens here, still
    look worse -- for reasons that have nothing to do with the search.

    The question that decides whether the search earned its place is narrower
    and harder: on the cases the gated arm declined to answer, was the linear
    answer actually wrong? Declining a correct answer is a real cost.
    """

    linear = {record.account_id: record for record in result.records if record.arm == "linear"}
    gated = {
        record.account_id: record for record in result.records if record.arm == "conflict_gated"
    }
    shared = sorted(set(linear) & set(gated))

    both = [account for account in shared if linear[account].released and gated[account].released]
    judged = [
        account
        for account in both
        if linear[account].correct is not None and gated[account].correct is not None
    ]
    differ = [account for account in judged if linear[account].outcome != gated[account].outcome]
    declined = [
        account
        for account in shared
        if linear[account].released
        and not gated[account].released
        and linear[account].correct is not None
    ]

    return {
        "both_released": len(both),
        "agreement_rate": (
            round(
                len([a for a in judged if linear[a].outcome == gated[a].outcome]) / len(judged), 6
            )
            if judged
            else None
        ),
        "paired_accuracy_linear": (
            round(len([a for a in judged if linear[a].correct]) / len(judged), 6)
            if judged
            else None
        ),
        "paired_accuracy_conflict_gated": (
            round(len([a for a in judged if gated[a].correct]) / len(judged), 6) if judged else None
        ),
        "disagreements": len(differ),
        "conflict_gated_right_when_they_differ": len([a for a in differ if gated[a].correct]),
        "linear_right_when_they_differ": len([a for a in differ if linear[a].correct]),
        "declined_by_conflict_gated_only": len(declined),
        "linear_was_wrong_on_declined": len([a for a in declined if not linear[a].correct]),
        "declined_precision": (
            round(len([a for a in declined if not linear[a].correct]) / len(declined), 6)
            if declined
            else None
        ),
    }


def comparison(result: AblationResult) -> dict[str, Any]:
    """Return the side-by-side section 15.7 asks the final report to show."""

    linear = result.arms["linear"]
    gated = result.arms["conflict_gated"]

    def _delta(left: float | None, right: float | None) -> float | None:
        return None if left is None or right is None else round(right - left, 6)

    return {
        "conflicting_accounts": len(result.conflicting_accounts),
        "scanned_accounts": result.scanned_accounts,
        "conflict_rate": round(len(result.conflicting_accounts) / result.scanned_accounts, 6)
        if result.scanned_accounts
        else 0.0,
        "linear": linear.as_dict(),
        "conflict_gated": gated.as_dict(),
        "paired": _paired(result),
        "deltas": {
            "accuracy": _delta(linear.accuracy, gated.accuracy),
            "auto_release_error_rate": _delta(
                linear.auto_release_error_rate, gated.auto_release_error_rate
            ),
            "escalation_rate": round(gated.escalation_rate - linear.escalation_rate, 6),
            "driver_fidelity": round(gated.driver_fidelity - linear.driver_fidelity, 6),
            "mean_latency_ms": round(gated.mean_latency_ms - linear.mean_latency_ms, 3),
            "total_tokens": gated.total_tokens - linear.total_tokens,
        },
    }


__all__ = [
    "ABLATION_QUESTION",
    "AUTO_RELEASED_ROUTES",
    "DRIVER_ALIASES",
    "AblationResult",
    "ArmSummary",
    "RunRecord",
    "comparison",
    "conflicting_accounts",
    "run_ablation",
    "run_arm",
]
