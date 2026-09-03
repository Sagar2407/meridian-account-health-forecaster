"""The evaluation dimensions and the result directory (plan sections 22 and 22.7).

These run on constructed `SystemRun`s rather than on graph runs. The dimensions
are arithmetic over recorded facts, and the arithmetic is what can be wrong in a
way nobody notices -- a rate computed over the wrong denominator reads exactly
like a correct one.
"""

import json
from pathlib import Path

import pytest

from meridian.graph.thresholds import THRESHOLDS, DecisionThresholds
from meridian_eval.dimensions import (
    calibration,
    forecast_correctness,
    grounded_explanation,
    operational_reliability,
)
from meridian_eval.report import assemble, render, write
from meridian_eval.system_run import RunCollection, SystemRun
from meridian_eval.threshold_study import ThresholdStudy, band_at


def _run(**overrides: object) -> SystemRun:
    """Return a released, clean, green run unless told otherwise."""

    defaults: dict[str, object] = {
        "account_id": "ACC-1000",
        "label": "Renewed",
        "segment": "Strategic",
        "region": "NA",
        "released": True,
        "abstained": False,
        "blocked": False,
        "outcome": "Renewed",
        "route": "green",
        "route_codes": (),
        "confidence": 0.90,
        "margin": 0.40,
        "distribution": {"Renewed": 0.6, "Churned": 0.2, "Contracted": 0.1, "Expanded": 0.1},
        "verification_passed": True,
        "verification_attempts": 1,
        "unsupported_numeric_claims": 0,
        "cited_doc_ids": ("DOC-1",),
        "retrieved_doc_ids": ("DOC-1", "DOC-2"),
        "wrong_account_citations": 0,
        "post_cutoff_citations": 0,
        "counterevidence_count": 1,
        "driver_names": ("adoption_level_last_q",),
        "truth_driver_names": ("adoption_level_last_q", "avg_csat"),
        "conflict_triggered": False,
        "tot_ran": False,
        "retrieval_retried": False,
        "latency_ms": 1500.0,
        "node_latency_ms": 1400.0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "model_calls": 0,
        "errors": 0,
    }
    return SystemRun(**{**defaults, **overrides})  # type: ignore[arg-type]


class TestForecastCorrectness:
    def test_an_abstention_is_not_counted_as_a_wrong_answer(self) -> None:
        """Folding abstentions in would penalise the system for declining well."""

        runs = [
            _run(account_id="A", outcome="Renewed", label="Renewed"),
            _run(account_id="B", released=False, abstained=True, outcome=None, label="Churned"),
        ]
        result = forecast_correctness(runs)

        assert result["released"] == 1
        assert result["abstained"] == 1
        assert result["accuracy"] == 1.0

    def test_it_reports_the_majority_baseline_beside_accuracy(self) -> None:
        """Renewed is over half the portfolio; accuracy alone means little."""

        runs = [_run(account_id=f"A{index}") for index in range(4)]
        runs.append(_run(account_id="B", label="Churned", outcome="Renewed"))
        result = forecast_correctness(runs)

        assert result["majority_class"] == "Renewed"
        assert result["majority_baseline_accuracy"] == 0.8
        assert result["beats_majority"] is False

    def test_it_says_so_rather_than_dividing_by_zero(self) -> None:
        """A dimension with nothing to measure reports the reason, not a number."""

        result = forecast_correctness([_run(released=False, abstained=True, outcome=None)])

        assert result["released"] == 0
        assert "reason" in result
        assert "macro_f1" not in result


class TestGroundedExplanation:
    def test_zero_tolerance_measures_are_counts_not_rates(self) -> None:
        """A rate of 0.003 invites rounding; a count of 2 does not."""

        runs = [
            _run(account_id="A", wrong_account_citations=1, post_cutoff_citations=1),
            _run(account_id="B"),
        ]
        result = grounded_explanation(runs)

        assert result["wrong_account_citation_count"] == 1
        assert result["post_cutoff_citation_count"] == 1

    def test_citation_precision_is_measured_only_where_something_was_cited(self) -> None:
        """A run that cited nothing has no precision, not a precision of zero."""

        runs = [
            _run(account_id="A", cited_doc_ids=("DOC-1",), retrieved_doc_ids=("DOC-1",)),
            _run(account_id="B", cited_doc_ids=(), retrieved_doc_ids=("DOC-9",)),
        ]
        result = grounded_explanation(runs)

        assert result["runs_with_citations"] == 1
        assert result["citation_precision"] == 1.0

    def test_a_fabricated_citation_lowers_precision(self) -> None:
        """Citing a document that was never retrieved is the failure this catches."""

        runs = [_run(cited_doc_ids=("DOC-1", "GHOST"), retrieved_doc_ids=("DOC-1",))]

        assert grounded_explanation(runs)["citation_precision"] == 0.5

    def test_counterevidence_is_measured_on_conflicting_cases_only(self) -> None:
        """On an aligned case there is nothing for counterevidence to include."""

        runs = [
            _run(account_id="A", conflict_triggered=True, counterevidence_count=2),
            _run(account_id="B", conflict_triggered=True, counterevidence_count=0),
            _run(account_id="C", conflict_triggered=False, counterevidence_count=0),
        ]
        result = grounded_explanation(runs)

        assert result["conflicting_runs"] == 2
        assert result["counterevidence_inclusion_rate_on_conflict"] == 0.5

    def test_no_judge_metric_is_reported_without_a_human_sample(self) -> None:
        """Section 22.2 permits a judge score only after human validation."""

        result = grounded_explanation([_run()])

        assert result["judge_metrics"] is None
        assert "double-reviewed human sample" in result["judge_note"]


class TestCalibration:
    def test_it_reports_the_error_rate_inside_each_band(self) -> None:
        """The error rate inside a band is what a reviewer is implicitly promised."""

        runs = [
            _run(account_id="A", route="green", outcome="Renewed", label="Renewed"),
            _run(account_id="B", route="green", outcome="Renewed", label="Churned"),
            _run(account_id="C", route="red", outcome="Renewed", label="Renewed"),
        ]
        quality = calibration(runs)["routing_quality"]

        assert quality["green"]["count"] == 2
        assert quality["green"]["errors"] == 1
        assert quality["green"]["error_rate"] == 0.5
        assert quality["green"]["auto_released"] is True
        assert quality["red"]["auto_released"] is False

    def test_too_few_runs_reports_a_reason_rather_than_a_number(self) -> None:
        """A calibration curve over one point is not a calibration curve."""

        assert "reason" in calibration([_run()])


class TestOperationalReliability:
    def test_latency_is_reported_per_path(self) -> None:
        """A fast-path p95 averaged with Tree-of-Thought runs describes neither."""

        runs = [
            _run(account_id="A", latency_ms=1000.0),
            _run(account_id="B", tot_ran=True, latency_ms=9000.0),
        ]
        result = operational_reliability(runs)

        assert result["path_counts"]["fast"] == 1
        assert result["path_counts"]["tree_of_thought"] == 1
        assert result["latency"]["fast"]["p50_ms"] == 1000.0
        assert result["latency"]["tree_of_thought"]["p50_ms"] == 9000.0

    def test_the_exhausted_retrieval_fallback_is_measured_where_it_applies(self) -> None:
        """Section 22.6 wants 1.00: missing critical coverage must not forecast."""

        runs = [
            _run(
                account_id="A",
                released=False,
                abstained=True,
                outcome=None,
                route="red",
                route_codes=("critical_coverage_missing",),
            ),
            _run(account_id="B"),
        ]
        fallback = operational_reliability(runs)["exhausted_retrieval_fallback"]

        assert fallback["runs"] == 1
        assert fallback["safe_fallback_rate"] == 1.0

    def test_an_empty_pass_reports_a_reason(self) -> None:
        """Nothing to measure is a state, not a zero."""

        assert "reason" in operational_reliability([])


def _bands(green: float, amber: float) -> DecisionThresholds:
    """Return a candidate band pair with its caps moved to stay valid.

    Section 16.1's caps are defined one hundredth below the band each holds a
    run under, and `DecisionThresholds` refuses a set where one is not. A test
    that varies a band therefore has to vary its caps too -- exactly as
    `ThresholdStudy.sweep` does.
    """

    return DecisionThresholds(
        green_minimum_confidence=green,
        amber_minimum_confidence=amber,
        cap_exhausted_retrieval_gap=round(green - 0.01, 2),
        cap_repaired_verification=round(green - 0.01, 2),
        cap_critical_source_missing=round(amber - 0.01, 2),
        cap_unresolved_conflict=round(amber - 0.01, 2),
    )


class TestThresholdStudy:
    def test_a_threshold_independent_rule_survives_every_candidate(self) -> None:
        """Only three rules read a threshold; the rest cannot change under a sweep."""

        run = _run(confidence=0.99, margin=0.9, route_codes=("verification_failed",))

        assert band_at(run, THRESHOLDS) == "red"
        assert band_at(run, _bands(green=0.6, amber=0.5)) == "red"

    def test_lowering_the_green_band_releases_more(self) -> None:
        """The trade-off the study exists to quantify."""

        # Just under the frozen green band, so the strict arm releases nothing
        # whatever that band currently is. Writing 0.80 here made this test a
        # restatement of v1, and it started failing the moment green moved.
        below_green = round(THRESHOLDS.green_minimum_confidence - 0.05, 2)
        runs = [_run(account_id=f"A{index}", confidence=below_green) for index in range(4)]
        study = ThresholdStudy(runs=runs)

        strict = study.outcome_at(THRESHOLDS)
        loose = study.outcome_at(_bands(green=below_green, amber=round(below_green - 0.1, 2)))

        assert strict.auto_released == 0
        assert loose.auto_released == 4

    def test_the_sweep_never_offers_amber_above_green(self) -> None:
        """A band pair that cannot be ordered is not a candidate."""

        for outcome in ThresholdStudy(runs=[_run()]).sweep():
            assert outcome.amber_minimum < outcome.green_minimum


class TestResultDirectory:
    def test_it_writes_valid_json_even_with_empty_bins(self, tmp_path: Path) -> None:
        """`NaN` is not JSON, and the browser reads this file."""

        collection = RunCollection(runs=[_run(account_id="A"), _run(account_id="B")])
        result = assemble(collection, provider="none (deterministic)")
        folder = write(result, collection, destination=tmp_path / "result")

        # Strict parse: json.load raises on a bare NaN.
        parsed = json.loads((folder / "results.json").read_text(encoding="utf-8"))
        assert parsed["manifest"]["thresholds"]["digest"] == THRESHOLDS.digest()

    def test_it_records_what_section_22_7_requires(self, tmp_path: Path) -> None:
        """Commit, dataset hash, model, thresholds, and environment."""

        collection = RunCollection(runs=[_run()])
        info = assemble(collection, provider="none")["manifest"]

        assert info["commit"]
        assert "dataset_digest" in info
        assert info["thresholds"]["version"] == THRESHOLDS.version
        assert info["environment"]["python"]
        assert info["split"] == "development"

    def test_every_file_the_report_names_is_written(self, tmp_path: Path) -> None:
        """Promising an artifact the directory lacks breaks the exit gate."""

        runs = [
            _run(account_id="A", outcome="Renewed", label="Renewed"),
            _run(account_id="B", outcome="Churned", label="Churned", confidence=0.6),
        ]
        collection = RunCollection(runs=runs)
        result = assemble(collection, provider="none")
        folder = write(result, collection, destination=tmp_path / "result")

        report = (folder / "REPORT.md").read_text(encoding="utf-8")
        for name in ("results.json", "runs.csv", "threshold_study.csv"):
            assert name in report
            assert (folder / name).is_file(), name
        for name in ("confusion_matrix.png", "reliability.png"):
            assert name in report
            assert (folder / name).is_file(), name

    def test_the_report_prints_what_the_result_holds_and_nothing_else(self) -> None:
        """Every number in the report is read from the result, not typed."""

        collection = RunCollection(runs=[_run(), _run(account_id="B", confidence=0.5)])
        result = assemble(collection, provider="none (deterministic)")
        report = render(result)

        assert result["manifest"]["thresholds"]["digest"] in report
        assert str(result["forecast_correctness"]["released"]) in report
        assert "none (deterministic)" in report

    def test_an_unmet_target_is_named_rather_than_softened(self) -> None:
        """A provisional target that was missed is a finding, printed as one."""

        # Two runs whose cited document was never retrieved: citation precision
        # collapses and the supported-claim target cannot be met.
        runs = [
            _run(account_id="A", verification_passed=False),
            _run(account_id="B", verification_passed=False),
        ]
        result = assemble(RunCollection(runs=runs), provider="none")
        report = render(result)

        assert "**Not met:**" in report
        assert "Supported-claim rate" in report


@pytest.mark.parametrize("provider", ["none (deterministic)", "configured model"])
def test_the_report_names_how_the_runs_were_generated(provider: str) -> None:
    """A deterministic result and a model-written one are not the same claim."""

    result = assemble(RunCollection(runs=[_run()]), provider=provider)

    assert provider in render(result)
