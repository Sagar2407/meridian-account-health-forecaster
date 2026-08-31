"""Deterministic account prediction with no LLM involved (plan section 10.5).

Returns a four-class probability distribution plus per-feature contributions.
Contributions are associations the model relies on, not causal claims, and the
API and UI must present them that way.
"""

from dataclasses import dataclass
from datetime import date

import numpy as np

from meridian.data.repository import RuntimeRepository
from meridian.features.builder import AccountFeatures, build_features
from meridian.features.spec import FEATURE_SPECS
from meridian.model.artifacts import ModelArtifact

_DESCRIPTIONS = {spec.name: spec.description for spec in FEATURE_SPECS}


@dataclass(frozen=True)
class FeatureContribution:
    """One feature's signed contribution to the predicted outcome."""

    feature: str
    value: float
    contribution: float
    description: str

    @property
    def direction(self) -> str:
        """Return whether this pushed toward or away from the prediction."""

        return "supports" if self.contribution >= 0 else "opposes"


@dataclass(frozen=True)
class Forecast:
    """A calibrated four-class forecast for one account at one cutoff."""

    account_id: str
    cutoff: date
    probabilities: dict[str, float]
    predicted_outcome: str
    confidence: float
    contributions: tuple[FeatureContribution, ...]
    coverage: dict[str, int]
    model_name: str

    def top_contributions(self, limit: int = 3) -> tuple[FeatureContribution, ...]:
        """Return the strongest contributions by absolute magnitude."""

        ranked = sorted(self.contributions, key=lambda item: -abs(item.contribution))
        return tuple(ranked[:limit])


def _linear_contributions(
    artifact: ModelArtifact, vector: np.ndarray, class_index: int
) -> np.ndarray | None:
    """Return per-feature contributions for a calibrated linear pipeline.

    Averages `coefficient * standardised value` across the calibration
    ensemble. Returns None when the underlying estimator is not linear, in
    which case the caller falls back to stored global importance.
    """

    ensemble = getattr(artifact.estimator, "calibrated_classifiers_", None)
    if not ensemble:
        return None
    totals: list[np.ndarray] = []
    for member in ensemble:
        pipeline = getattr(member, "estimator", None)
        if pipeline is None or not hasattr(pipeline, "named_steps"):
            return None
        model = pipeline.named_steps.get("model")
        scaler = pipeline.named_steps.get("scale")
        coefficients = getattr(model, "coef_", None)
        if coefficients is None:
            return None
        scaled = vector if scaler is None else (vector - scaler.mean_) / scaler.scale_
        row = coefficients[class_index] if coefficients.shape[0] > class_index else coefficients[0]
        totals.append(row * scaled)
    return np.asarray(np.mean(totals, axis=0), dtype=float)


def predict_from_features(artifact: ModelArtifact, features: AccountFeatures) -> Forecast:
    """Return a forecast for an already-computed feature vector."""

    names = artifact.metadata.feature_names
    vector = np.array([features.values[name] for name in names], dtype=float)
    probabilities = artifact.estimator.predict_proba(vector.reshape(1, -1))[0]

    classes = list(artifact.metadata.classes)
    class_index = int(np.argmax(probabilities))
    distribution = {name: float(probabilities[index]) for index, name in enumerate(classes)}

    raw = _linear_contributions(artifact, vector, class_index)
    if raw is None:
        importance = artifact.metadata.global_importance
        raw = np.array([importance.get(name, 0.0) for name in names], dtype=float)

    contributions = tuple(
        FeatureContribution(
            feature=name,
            value=float(features.values[name]),
            contribution=float(raw[index]),
            description=_DESCRIPTIONS.get(name, ""),
        )
        for index, name in enumerate(names)
    )

    return Forecast(
        account_id=features.account_id,
        cutoff=features.cutoff,
        probabilities=distribution,
        predicted_outcome=classes[class_index],
        confidence=float(probabilities[class_index]),
        contributions=contributions,
        coverage=features.coverage.model_dump(),
        model_name=artifact.metadata.model_name,
    )


def predict_account(
    artifact: ModelArtifact,
    repository: RuntimeRepository,
    account_id: str,
    cutoff: date | None = None,
) -> Forecast:
    """Compute features and return a forecast for one account."""

    return predict_from_features(artifact, build_features(repository, account_id, cutoff))
