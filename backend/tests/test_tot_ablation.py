"""The linear-versus-ToT ablation reports what it measures (plan section 15.7).

Section 15.7 exists to answer one question honestly, so the arithmetic behind
the answer has to be right. These tests build records by hand and check that the
summaries say what they claim -- in particular the paired comparison, because an
unpaired one flatters whichever arm abstains more.
"""

import pytest

from meridian.serving.scan import AUTO_RELEASED_ROUTES as SERVING_AUTO_RELEASED_ROUTES
from meridian_eval.tot_ablation import (
    AUTO_RELEASED_ROUTES,
    DRIVER_ALIASES,
    AblationResult,
    RunRecord,
    _paired,
    _summarise,
    comparison,
)


def _record(
    account_id: str,
    arm: str,
    *,
    route: str = "amber",
    released: bool = True,
    outcome: str | None = "Churned",
    label: str | None = "Churned",
    drivers: tuple[str, ...] = ("adoption_level_last_q",),
    overlap: float = 1.0,
    verified: bool = True,
) -> RunRecord:
    return RunRecord(
        account_id=account_id,
        arm=arm,
        route=route,
        released=released,
        outcome=outcome,
        label=label,
        correct=None if (outcome is None or label is None) else outcome == label,
        drivers=drivers,
        driver_overlap=overlap,
        verified_first_time=verified,
        conflict_triggered=True,
        conflict_severity="moderate",
        tot_ran=arm == "conflict_gated",
        latency_ms=100.0,
        prompt_tokens=0,
        completion_tokens=0,
    )


def test_an_abstention_is_not_counted_as_an_unsupported_claim() -> None:
    """A run that declined wrote no narrative, so it made no claim to support."""

    records = [
        _record("ACC-1", "conflict_gated", released=True, verified=True),
        _record("ACC-2", "conflict_gated", released=False, outcome=None, verified=False),
    ]
    summary = _summarise("conflict_gated", records)
    assert summary.released == 1
    assert summary.abstained == 1
    assert summary.supported_claim_rate == 1.0


def test_escalation_counts_abstentions_and_red_routes() -> None:
    """Anything a person has to look at is an escalation, however it got there."""

    records = [
        _record("ACC-1", "linear", route="green"),
        _record("ACC-2", "linear", route="red"),
        _record("ACC-3", "linear", route="amber", released=False, outcome=None),
    ]
    summary = _summarise("linear", records)
    assert summary.auto_released == 1
    assert summary.escalation_rate == pytest.approx(2 / 3)
    # Equality, not membership. The old assertion -- green in, red out -- held
    # just as well for {"green", "amber"}, which is what this constant actually
    # said while the serving path used {"green"}. Two definitions of
    # "auto-released" under one name is how a metric quietly means two things.
    assert AUTO_RELEASED_ROUTES == SERVING_AUTO_RELEASED_ROUTES


def test_only_auto_released_errors_count_against_the_error_rate() -> None:
    """An error a human was asked to review did not reach anyone unchecked."""

    records = [
        _record("ACC-1", "linear", route="green", outcome="Renewed", label="Churned"),
        _record("ACC-2", "linear", route="red", outcome="Renewed", label="Churned"),
        _record("ACC-3", "linear", route="green"),
    ]
    summary = _summarise("linear", records)
    assert summary.accuracy == pytest.approx(1 / 3)
    assert summary.auto_released == 2
    assert summary.auto_release_errors == 1
    assert summary.auto_release_error_rate == pytest.approx(0.5)


def test_the_paired_comparison_only_compares_what_both_arms_answered() -> None:
    """Aggregate accuracy over different subsets is not a comparison.

    The gated arm abstains on what it finds hardest, so whatever it releases is
    an easier set by construction. Only the accounts both arms answered can be
    compared directly.
    """

    result = AblationResult(
        records=[
            _record("ACC-1", "linear", outcome="Churned", label="Churned"),
            _record("ACC-2", "linear", outcome="Churned", label="Renewed"),
            _record("ACC-3", "linear", outcome="Renewed", label="Renewed"),
            _record("ACC-1", "conflict_gated", outcome="Churned", label="Churned"),
            _record("ACC-2", "conflict_gated", outcome="Renewed", label="Renewed"),
            _record("ACC-3", "conflict_gated", released=False, outcome=None, label="Renewed"),
        ],
        conflicting_accounts=("ACC-1", "ACC-2", "ACC-3"),
        scanned_accounts=10,
    )
    paired = _paired(result)

    assert paired["both_released"] == 2
    assert paired["paired_accuracy_linear"] == pytest.approx(0.5)
    assert paired["paired_accuracy_conflict_gated"] == pytest.approx(1.0)
    assert paired["disagreements"] == 1
    assert paired["conflict_gated_right_when_they_differ"] == 1
    assert paired["linear_right_when_they_differ"] == 0


def test_declining_a_correct_answer_is_measured_as_a_cost() -> None:
    """The question that decides whether the search earned its place.

    An abstention is only worth its escalation cost when the answer it blocked
    was actually wrong, so the rate at which that happens is reported directly
    rather than left for a reader to infer from two accuracy numbers.
    """

    result = AblationResult(
        records=[
            _record("ACC-1", "linear", outcome="Churned", label="Churned"),
            _record("ACC-2", "linear", outcome="Churned", label="Renewed"),
            _record("ACC-1", "conflict_gated", released=False, outcome=None, label="Churned"),
            _record("ACC-2", "conflict_gated", released=False, outcome=None, label="Renewed"),
        ],
        conflicting_accounts=("ACC-1", "ACC-2"),
        scanned_accounts=4,
    )
    paired = _paired(result)

    assert paired["declined_by_conflict_gated_only"] == 2
    assert paired["linear_was_wrong_on_declined"] == 1
    assert paired["declined_precision"] == pytest.approx(0.5)


def test_the_comparison_reports_both_arms_and_their_deltas() -> None:
    """Section 15.7 asks for a side by side, not a verdict."""

    result = AblationResult(
        arms={
            "linear": _summarise("linear", [_record("ACC-1", "linear")]),
            "conflict_gated": _summarise("conflict_gated", [_record("ACC-1", "conflict_gated")]),
        },
        records=[_record("ACC-1", "linear"), _record("ACC-1", "conflict_gated")],
        conflicting_accounts=("ACC-1",),
        scanned_accounts=4,
    )
    report = comparison(result)

    assert report["conflict_rate"] == pytest.approx(0.25)
    assert set(report) >= {"linear", "conflict_gated", "deltas", "paired"}
    assert set(report["deltas"]) >= {"accuracy", "escalation_rate", "total_tokens"}


def test_a_renamed_ground_truth_driver_is_matched_not_missed() -> None:
    """The archive predates section 8.3's recomputation, so one metric moved."""

    assert DRIVER_ALIASES["avg_csat"] == "avg_closed_csat_26w"
