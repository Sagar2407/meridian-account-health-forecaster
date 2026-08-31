"""Candidate models, selection, and calibration (plan sections 10.2 to 10.4).

Training lives in the evaluation package because it needs outcome labels, which
runtime code must never reach. The artifact it produces carries no labels, so
`meridian.model` can load and serve it across the boundary.
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.calibration import CalibratedClassifierCV
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import RepeatedStratifiedKFold, cross_validate
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from meridian.data.constants import PROJECT_SEED
from meridian.features.spec import MODEL_INPUT_FEATURES

OUTCOME_ORDER: tuple[str, ...] = ("Churned", "Contracted", "Renewed", "Expanded")
"""Outcomes from worst to best. The rule baseline treats health as ordinal."""

# Signs and relative magnitudes come from KB-012, the documented health
# methodology. Adoption trend carries the largest weight by design.
HEALTH_INDEX_WEIGHTS: dict[str, float] = {
    "adoption_trend_13w": 3.0,
    "adoption_level_last_q": 1.5,
    "advanced_feature_depth": 1.0,
    "product_breadth": 0.75,
    "support_escalation_rate": -1.25,
    "avg_ticket_sentiment_26w": 1.0,
    "avg_closed_csat_26w": 0.75,
    "adverse_events_2q": -1.0,
    "sponsor_change": -0.75,
    "sponsor_lost": -1.0,
    "onboarding_incomplete": -1.25,
}


class HealthIndexRuleBaseline(ClassifierMixin, BaseEstimator):
    """A transparent baseline scoring the documented health index (plan 10.2).

    Features are standardised, combined with the published weights into a single
    health index, then turned into class probabilities by a one-dimensional
    Gaussian model per outcome. Every step is inspectable, which is the point: it
    shows how much a learned model actually adds over the written methodology.
    """

    means_: np.ndarray
    scales_: np.ndarray
    weight_vector_: np.ndarray
    classes_: np.ndarray
    class_means_: np.ndarray
    class_scales_: np.ndarray
    class_priors_: np.ndarray

    def __init__(self, feature_names: tuple[str, ...] = MODEL_INPUT_FEATURES) -> None:
        self.feature_names = feature_names

    def _index(self, X: np.ndarray) -> np.ndarray:
        """Return the standardised weighted health index for each row."""

        standardised = (X - self.means_) / self.scales_
        index: np.ndarray = standardised @ self.weight_vector_
        return index

    def fit(self, X: Any, y: Any) -> "HealthIndexRuleBaseline":
        """Fit standardisation, then a Gaussian index model per outcome."""

        values = np.asarray(X, dtype=float)
        labels = np.asarray(y, dtype=object)
        self.means_ = values.mean(axis=0)
        scales_ = values.std(axis=0)
        self.scales_ = np.where(scales_ == 0.0, 1.0, scales_)
        self.weight_vector_ = np.array(
            [HEALTH_INDEX_WEIGHTS.get(name, 0.0) for name in self.feature_names], dtype=float
        )
        self.classes_ = np.array([name for name in OUTCOME_ORDER if name in set(labels)])

        index = self._index(values)
        self.class_means_ = np.array([index[labels == name].mean() for name in self.classes_])
        deviations = np.array([index[labels == name].std() for name in self.classes_])
        self.class_scales_ = np.where(deviations < 1e-6, 1.0, deviations)
        self.class_priors_ = np.array([(labels == name).mean() for name in self.classes_])
        return self

    def predict_proba(self, X: Any) -> np.ndarray:
        """Return outcome probabilities from the health index."""

        index = self._index(np.asarray(X, dtype=float))[:, None]
        density = np.exp(-0.5 * ((index - self.class_means_) / self.class_scales_) ** 2)
        density = density / self.class_scales_
        weighted = density * self.class_priors_
        totals = weighted.sum(axis=1, keepdims=True)
        totals[totals == 0.0] = 1.0
        probabilities: np.ndarray = weighted / totals
        return probabilities

    def predict(self, X: Any) -> np.ndarray:
        """Return the most probable outcome for each row."""

        chosen: np.ndarray = self.classes_[self.predict_proba(X).argmax(axis=1)]
        return chosen


def build_candidates(seed: int = PROJECT_SEED) -> dict[str, Pipeline]:
    """Return every candidate required by plan section 10.2, in comparison order."""

    return {
        "majority_baseline": Pipeline(
            [("model", DummyClassifier(strategy="prior", random_state=seed))]
        ),
        "rule_baseline": Pipeline([("model", HealthIndexRuleBaseline())]),
        "logistic_regression": Pipeline(
            [
                ("scale", StandardScaler()),
                (
                    "model",
                    LogisticRegression(
                        max_iter=2000,
                        C=1.0,
                        class_weight="balanced",
                        random_state=seed,
                    ),
                ),
            ]
        ),
        "random_forest": Pipeline(
            [
                (
                    "model",
                    RandomForestClassifier(
                        n_estimators=300,
                        min_samples_leaf=3,
                        class_weight="balanced_subsample",
                        random_state=seed,
                        n_jobs=-1,
                    ),
                )
            ]
        ),
        "gradient_boosting": Pipeline(
            [
                (
                    "model",
                    HistGradientBoostingClassifier(
                        max_iter=200,
                        learning_rate=0.06,
                        max_leaf_nodes=15,
                        l2_regularization=1.0,
                        random_state=seed,
                    ),
                )
            ]
        ),
    }


@dataclass(frozen=True)
class CandidateResult:
    """Cross-validated performance of one candidate."""

    name: str
    macro_f1_mean: float
    macro_f1_std: float
    log_loss_mean: float
    accuracy_mean: float
    fold_scores: list[float] = field(default_factory=list)


def cross_validate_candidates(
    features: pd.DataFrame,
    labels: "pd.Series[str]",
    seed: int = PROJECT_SEED,
    splits: int = 5,
    repeats: int = 3,
) -> list[CandidateResult]:
    """Score every candidate with repeated stratified cross-validation.

    Plan section 10.3 asks for repeated stratified CV because 260 accounts make
    a single split noisy. Selection is on macro F1, with log loss and fold
    stability as secondary signals.
    """

    splitter = RepeatedStratifiedKFold(n_splits=splits, n_repeats=repeats, random_state=seed)
    results: list[CandidateResult] = []
    for name, pipeline in build_candidates(seed).items():
        scores = cross_validate(
            pipeline,
            features.to_numpy(dtype=float),
            labels.to_numpy(dtype=object),
            cv=splitter,
            scoring=("f1_macro", "neg_log_loss", "accuracy"),
            n_jobs=-1,
            error_score="raise",
        )
        fold_scores = [float(value) for value in scores["test_f1_macro"]]
        results.append(
            CandidateResult(
                name=name,
                macro_f1_mean=float(np.mean(fold_scores)),
                macro_f1_std=float(np.std(fold_scores)),
                log_loss_mean=float(-np.mean(scores["test_neg_log_loss"])),
                accuracy_mean=float(np.mean(scores["test_accuracy"])),
                fold_scores=fold_scores,
            )
        )
    return results


def select_best(results: list[CandidateResult]) -> CandidateResult:
    """Return the selected candidate under a one-standard-error rule.

    Plan section 10.3 makes macro F1 primary and log loss plus calibration
    secondary. Ranking on macro F1 alone would pick the rule baseline, which
    scores well on F1 but has a log loss around 2.1 because its Gaussian index
    produces overconfident probabilities. That is disqualifying here: section 16
    routes human review on confidence, so an uncalibrated model cannot be
    served no matter how it ranks on F1.

    So: take every candidate within one standard error of the best macro F1 --
    statistically indistinguishable on the primary metric -- and among those
    choose the lowest log loss.
    """

    best = max(results, key=lambda item: item.macro_f1_mean)
    threshold = best.macro_f1_mean - best.macro_f1_std
    contenders = [item for item in results if item.macro_f1_mean >= threshold]
    return sorted(contenders, key=lambda item: item.log_loss_mean)[0]


CALIBRATION_METHOD = "isotonic"
CALIBRATION_FOLDS = 3
"""Calibration settings chosen from measured validation results, not by default.

Plan section 10.4 prefers sigmoid "unless validation demonstrates enough data
for isotonic". Validation demonstrated the opposite of the prior: sigmoid was
the worst option in every configuration tested, collapsing macro F1 from 0.72 to
around 0.51. With 156 training accounts and four classes, a 5-fold sigmoid
calibrator sees roughly three `Contracted` examples per fold and flattens the
minority classes.

Isotonic at 3 folds beat the uncalibrated model on macro F1, log loss, Brier,
and accuracy. `artifacts/model/calibration_study.csv` records the full grid.
"""


def fit_calibrated_model(
    name: str,
    features: pd.DataFrame,
    labels: "pd.Series[str]",
    seed: int = PROJECT_SEED,
    method: str = CALIBRATION_METHOD,
    folds: int = CALIBRATION_FOLDS,
) -> CalibratedClassifierCV:
    """Fit the selected candidate wrapped in probability calibration.

    `CalibratedClassifierCV` fits each underlying classifier on all folds but
    one and its calibrator on the held-out fold, so no calibrator ever sees the
    data that fitted its own classifier (plan section 10.4).
    """

    calibrated = CalibratedClassifierCV(
        estimator=build_candidates(seed)[name],
        method=method,
        cv=folds,
        n_jobs=1,
    )
    calibrated.fit(features.to_numpy(dtype=float), labels.to_numpy(dtype=object))
    return calibrated
