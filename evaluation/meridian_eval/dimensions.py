"""The five evaluation dimensions, computed from one pass over a split.

Plan section 22. Each function here takes the runs `system_run.collect_runs`
produced and returns a JSON-serialisable block for the report. Nothing here runs
the graph, which is what lets the report be assembled from a single pass.

Two rules shape every measure below.

**A rate with no denominator is not a rate.** Every block reports the count it
was computed over, so a 1.00 supported-claim rate over three runs cannot be read
as a 1.00 over three hundred.

**A measure that cannot be computed says so.** Section 22.7 requires
deterministic metrics to be distinguished from judge metrics; this file has no
judge metrics at all, and where an input is missing the value is `None` with a
`reason`, never a zero that reads like a finding.
"""

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix

from meridian.contracts import OUTCOME_CLASSES
from meridian_eval.metrics import (
    confidence_band_errors,
    evaluate,
    reliability_table,
    slice_metrics,
)
from meridian_eval.system_run import SystemRun

#: Routes that reach a user without a person looking first.
AUTO_RELEASED = frozenset({"green"})

#: The class order every probability matrix uses.
#:
#: `OUTCOME_CLASSES` is a *display* order -- worst to best, for a decision card.
#: scikit-learn orders classes lexicographically, which is also the order the
#: trained artifact reports, so a matrix built in display order and handed to
#: `log_loss(labels=...)` is silently transposed against what sklearn assumes.
#: Sorting here makes the columns, the labels argument, and the model agree.
PROBABILITY_CLASSES: list[str] = sorted(OUTCOME_CLASSES)


def _rate(numerator: int, denominator: int) -> float | None:
    """Return a rounded rate, or None when there is nothing to divide."""

    return round(numerator / denominator, 4) if denominator else None


def _probability_matrix(runs: Sequence[SystemRun]) -> tuple[np.ndarray, np.ndarray]:
    """Return aligned labels and class-probability rows for released runs."""

    labels = np.array([run.label for run in runs], dtype=object)
    matrix = np.array(
        [[run.distribution.get(name, 0.0) for name in PROBABILITY_CLASSES] for run in runs],
        dtype=float,
    )
    # The stored distribution is rounded for display, so a row sums to 1.0000
    # give or take a few parts in a million. `log_loss` warns about that, and a
    # warning nobody can act on is a warning readers learn to ignore. The
    # contract already refuses a distribution more than 2% from one, so
    # renormalising here corrects rounding rather than hiding an error.
    totals = matrix.sum(axis=1, keepdims=True)
    matrix = np.divide(matrix, totals, out=matrix, where=totals > 0)
    return labels, matrix


def forecast_correctness(runs: Sequence[SystemRun]) -> dict[str, Any]:
    """Section 22.1: macro F1, per-class metrics, confusion, and slices.

    Measured over the runs that released a label. An abstention is not a wrong
    answer and folding it in as one would make the system look worse the more
    carefully it declined; the abstention rate is reported beside this instead.
    """

    released = [run for run in runs if run.released and run.outcome]
    if not released:
        return {"released": 0, "reason": "no run released a categorical outcome"}

    truth = np.array([run.label for run in released], dtype=object)
    predicted = np.array([run.outcome for run in released], dtype=object)
    labels, matrix = _probability_matrix(released)
    headline = evaluate(labels, matrix, PROBABILITY_CLASSES)

    # Display order here: a confusion matrix is read by a person, and worst to
    # best is the order the decision card uses.
    per_class = classification_report(
        truth, predicted, labels=list(OUTCOME_CLASSES), output_dict=True, zero_division=0
    )
    matrix_rows = confusion_matrix(truth, predicted, labels=list(OUTCOME_CLASSES))

    # The majority baseline every claim of usefulness has to beat: `Renewed` is
    # over half the portfolio, so an accuracy near 0.5 means nothing on its own.
    majority = max(set(truth), key=lambda name: int((truth == name).sum()))
    majority_accuracy = float((truth == majority).mean())

    return {
        "released": len(released),
        "abstained": sum(1 for run in runs if run.abstained),
        "blocked": sum(1 for run in runs if run.blocked),
        "macro_f1": round(headline.macro_f1, 4),
        "accuracy": round(headline.accuracy, 4),
        "majority_class": str(majority),
        "majority_baseline_accuracy": round(majority_accuracy, 4),
        "beats_majority": bool(headline.accuracy > majority_accuracy),
        "per_class": {
            name: {
                "precision": round(float(per_class[name]["precision"]), 4),
                "recall": round(float(per_class[name]["recall"]), 4),
                "f1": round(float(per_class[name]["f1-score"]), 4),
                "support": int(per_class[name]["support"]),
            }
            for name in OUTCOME_CLASSES
            if name in per_class
        },
        "confusion_matrix": {
            "classes": PROBABILITY_CLASSES,
            "rows": [[int(value) for value in row] for row in matrix_rows],
        },
        "slices": {
            "segment": slice_metrics(
                labels,
                matrix,
                PROBABILITY_CLASSES,
                pd.Series([run.segment for run in released]),
            ).to_dict("records"),
            "region": slice_metrics(
                labels,
                matrix,
                PROBABILITY_CLASSES,
                pd.Series([run.region for run in released]),
            ).to_dict("records"),
        },
    }


def grounded_explanation(runs: Sequence[SystemRun]) -> dict[str, Any]:
    """Section 22.2: supported claims, citation precision, numeric agreement.

    The three zero-tolerance measures -- wrong-account citations, post-cutoff
    citations, and unsupported numeric claims -- are reported as counts rather
    than rates. A rate of 0.003 invites rounding; a count of 2 does not.
    """

    released = [run for run in runs if run.released]
    if not released:
        return {"released": 0, "reason": "no run released a narrative to check"}

    verified_first_time = sum(
        1 for run in released if run.verification_passed and run.verification_attempts <= 1
    )
    with_citations = [run for run in released if run.cited_doc_ids]
    precisions = [
        run.citation_precision for run in with_citations if run.citation_precision is not None
    ]
    overlaps = [run.driver_overlap for run in released if run.driver_overlap is not None]
    conflicting = [run for run in released if run.conflict_triggered]

    return {
        "released": len(released),
        "supported_claim_rate": _rate(
            sum(1 for run in released if run.verification_passed), len(released)
        ),
        "verified_first_attempt_rate": _rate(verified_first_time, len(released)),
        "exact_numeric_agreement": _rate(
            sum(1 for run in released if run.unsupported_numeric_claims == 0), len(released)
        ),
        "unsupported_numeric_claim_count": sum(run.unsupported_numeric_claims for run in released),
        "citation_precision": (round(float(np.mean(precisions)), 4) if precisions else None),
        "runs_with_citations": len(with_citations),
        "wrong_account_citation_count": sum(run.wrong_account_citations for run in released),
        "post_cutoff_citation_count": sum(run.post_cutoff_citations for run in released),
        "driver_overlap": round(float(np.mean(overlaps)), 4) if overlaps else None,
        "runs_with_ground_truth_drivers": len(overlaps),
        "counterevidence_inclusion_rate_on_conflict": _rate(
            sum(1 for run in conflicting if run.counterevidence_count > 0), len(conflicting)
        ),
        "conflicting_runs": len(conflicting),
        "judge_metrics": None,
        "judge_note": (
            "Section 22.2 permits an LLM judge score only after validation against a "
            "double-reviewed human sample. No such sample exists, so no judge metric "
            "is reported. Every measure above is deterministic."
        ),
    }


def calibration(runs: Sequence[SystemRun]) -> dict[str, Any]:
    """Section 22.3: ECE, Brier, log loss, reliability, and band quality."""

    released = [run for run in runs if run.released]
    if len(released) < 2:
        return {"released": len(released), "reason": "too few released runs to calibrate"}

    labels, matrix = _probability_matrix(released)
    headline = evaluate(labels, matrix, PROBABILITY_CLASSES)

    # Band quality is the thing that makes the routing defensible: the error
    # rate inside each band is what a reviewer is implicitly promised.
    by_route: dict[str, dict[str, Any]] = {}
    for band in ("green", "amber", "red"):
        in_band = [run for run in released if run.route == band]
        wrong = sum(1 for run in in_band if run.correct is False)
        by_route[band] = {
            "count": len(in_band),
            "errors": wrong,
            "error_rate": _rate(wrong, len(in_band)),
            "auto_released": band in AUTO_RELEASED,
        }

    return {
        "released": len(released),
        "expected_calibration_error": round(headline.expected_calibration_error, 4),
        "brier": round(headline.brier, 4),
        "log_loss": round(headline.log_loss, 4),
        "reliability": reliability_table(labels, matrix, PROBABILITY_CLASSES).to_dict("records"),
        "confidence_bands": confidence_band_errors(labels, matrix, PROBABILITY_CLASSES).to_dict(
            "records"
        ),
        "routing_quality": by_route,
        "auto_release_rate": _rate(
            sum(1 for run in released if run.route in AUTO_RELEASED), len(runs)
        ),
    }


def operational_reliability(runs: Sequence[SystemRun]) -> dict[str, Any]:
    """Section 22.5: completion, latency by path, retries, tokens, and cost."""

    if not runs:
        return {"runs": 0, "reason": "no run to measure"}

    def percentiles(values: list[float]) -> dict[str, float | None]:
        """Return p50 and p95, or None when the sample is empty."""

        if not values:
            return {"p50_ms": None, "p95_ms": None}
        return {
            "p50_ms": round(float(np.percentile(values, 50)), 1),
            "p95_ms": round(float(np.percentile(values, 95)), 1),
        }

    paths = {
        name: [run.latency_ms for run in runs if run.path == name]
        for name in ("fast", "tree_of_thought", "abstained", "blocked")
    }
    exhausted = [run for run in runs if "critical_coverage_missing" in run.route_codes]

    return {
        "runs": len(runs),
        "completion_rate": _rate(
            sum(1 for run in runs if run.released or run.abstained), len(runs)
        ),
        "release_rate": _rate(sum(1 for run in runs if run.released), len(runs)),
        "abstention_rate": _rate(sum(1 for run in runs if run.abstained), len(runs)),
        "escalation_rate": _rate(sum(1 for run in runs if run.route == "red"), len(runs)),
        "retrieval_retry_rate": _rate(sum(1 for run in runs if run.retrieval_retried), len(runs)),
        "regeneration_rate": _rate(
            sum(1 for run in runs if run.verification_attempts > 1), len(runs)
        ),
        "node_error_count": sum(run.errors for run in runs),
        "latency": {
            "overall": percentiles([run.latency_ms for run in runs]),
            **{name: percentiles(values) for name, values in paths.items()},
        },
        "path_counts": {name: len(values) for name, values in paths.items()},
        "tokens": {
            "prompt": sum(run.prompt_tokens for run in runs),
            "completion": sum(run.completion_tokens for run in runs),
            "total": sum(run.total_tokens for run in runs),
            "model_calls": sum(run.model_calls for run in runs),
        },
        "exhausted_retrieval_fallback": {
            "runs": len(exhausted),
            # Section 22.6 asks for 1.00 here: a run whose critical coverage was
            # missing must abstain rather than forecast on the numbers alone.
            "safe_fallback_rate": _rate(
                sum(1 for run in exhausted if not run.released), len(exhausted)
            ),
        },
    }


__all__ = [
    "AUTO_RELEASED",
    "calibration",
    "forecast_correctness",
    "grounded_explanation",
    "operational_reliability",
]
