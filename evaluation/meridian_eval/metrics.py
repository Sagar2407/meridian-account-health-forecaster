"""Classification and calibration metrics (plan sections 10.3 and 10.4).

Accuracy is deliberately not a selection metric: `Renewed` is 135 of 260
accounts, so a majority-class guess scores 52% while being useless.
"""

from dataclasses import asdict, dataclass
from itertools import pairwise

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, f1_score, log_loss

DEFAULT_CALIBRATION_BINS = 10
CONFIDENCE_BANDS: tuple[tuple[str, float, float], ...] = (
    ("low", 0.0, 0.5),
    ("medium", 0.5, 0.75),
    ("high", 0.75, 1.01),
)


@dataclass(frozen=True)
class ClassificationMetrics:
    """Headline quality and calibration for one model on one split."""

    macro_f1: float
    accuracy: float
    log_loss: float
    brier: float
    expected_calibration_error: float
    n: int

    def to_dict(self) -> dict[str, float]:
        """Return the metrics as a plain, JSON-serialisable mapping."""

        return {key: float(value) for key, value in asdict(self).items()}


def multiclass_brier(labels: np.ndarray, probabilities: np.ndarray, classes: list[str]) -> float:
    """Return the mean one-versus-rest Brier score across classes."""

    scores = []
    for index, name in enumerate(classes):
        actual = (labels == name).astype(int)
        if actual.sum() == 0:
            continue
        scores.append(brier_score_loss(actual, probabilities[:, index]))
    return float(np.mean(scores)) if scores else float("nan")


def expected_calibration_error(
    labels: np.ndarray,
    probabilities: np.ndarray,
    classes: list[str],
    bins: int = DEFAULT_CALIBRATION_BINS,
) -> float:
    """Return the ECE of the top-1 predicted probability.

    Confidence is binned, and each bin contributes the gap between its mean
    confidence and its observed accuracy, weighted by bin size.
    """

    confidence = probabilities.max(axis=1)
    predicted = np.array(classes, dtype=object)[probabilities.argmax(axis=1)]
    correct = (predicted == labels).astype(float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = 0.0
    for lower, upper in pairwise(edges):
        mask = (confidence > lower) & (confidence <= upper)
        if not mask.any():
            continue
        total += mask.mean() * abs(confidence[mask].mean() - correct[mask].mean())
    return float(total)


def reliability_table(
    labels: np.ndarray,
    probabilities: np.ndarray,
    classes: list[str],
    bins: int = DEFAULT_CALIBRATION_BINS,
) -> pd.DataFrame:
    """Return per-bin confidence, accuracy, and count for a reliability diagram."""

    confidence = probabilities.max(axis=1)
    predicted = np.array(classes, dtype=object)[probabilities.argmax(axis=1)]
    correct = (predicted == labels).astype(float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    rows = []
    for lower, upper in pairwise(edges):
        mask = (confidence > lower) & (confidence <= upper)
        rows.append(
            {
                "bin_lower": float(lower),
                "bin_upper": float(upper),
                "count": int(mask.sum()),
                "mean_confidence": float(confidence[mask].mean()) if mask.any() else float("nan"),
                "accuracy": float(correct[mask].mean()) if mask.any() else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def confidence_band_errors(
    labels: np.ndarray, probabilities: np.ndarray, classes: list[str]
) -> pd.DataFrame:
    """Return the error rate within each confidence band.

    Plan section 16 routes on confidence, so the error rate inside each band is
    what makes that routing defensible.
    """

    confidence = probabilities.max(axis=1)
    predicted = np.array(classes, dtype=object)[probabilities.argmax(axis=1)]
    correct = (predicted == labels).astype(float)
    rows = []
    for name, lower, upper in CONFIDENCE_BANDS:
        mask = (confidence >= lower) & (confidence < upper)
        rows.append(
            {
                "band": name,
                "lower": lower,
                "upper": upper,
                "count": int(mask.sum()),
                "error_rate": float(1.0 - correct[mask].mean()) if mask.any() else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def evaluate(
    labels: np.ndarray, probabilities: np.ndarray, classes: list[str]
) -> ClassificationMetrics:
    """Return headline metrics for one set of predictions."""

    predicted = np.array(classes, dtype=object)[probabilities.argmax(axis=1)]
    return ClassificationMetrics(
        macro_f1=float(f1_score(labels, predicted, average="macro", zero_division=0)),
        accuracy=float((predicted == labels).mean()),
        log_loss=float(log_loss(labels, probabilities, labels=classes)),
        brier=multiclass_brier(labels, probabilities, classes),
        expected_calibration_error=expected_calibration_error(labels, probabilities, classes),
        n=len(labels),
    )


def slice_metrics(
    labels: np.ndarray,
    probabilities: np.ndarray,
    classes: list[str],
    groups: "pd.Series[str]",
    minimum_size: int = 10,
) -> pd.DataFrame:
    """Return macro F1 per group, for slice checks by segment or region.

    Groups smaller than `minimum_size` are reported with their size but no
    metric, because a macro F1 over a handful of rows is noise.
    """

    rows = []
    for name in sorted(groups.unique()):
        mask = (groups == name).to_numpy()
        size = int(mask.sum())
        if size < minimum_size:
            rows.append({"group": name, "count": size, "macro_f1": float("nan")})
            continue
        metrics = evaluate(labels[mask], probabilities[mask], classes)
        rows.append({"group": name, "count": size, "macro_f1": metrics.macro_f1})
    return pd.DataFrame(rows)
