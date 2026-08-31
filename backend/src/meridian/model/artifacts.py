"""Persisting and loading the fitted forecaster (plan section 10.4).

The artifact records everything needed to reproduce a prediction: the feature
order, the class order, the split it was trained on, package versions, and the
seed.

A saved artifact must be loadable by runtime code alone. `save_artifact` refuses
an estimator defined inside the evaluation package, because unpickling it would
force `meridian` to import `meridian_eval` and silently break the section 8.4
boundary at load time rather than at review time.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import joblib

from meridian.data.paths import repository_root

ARTIFACT_FILENAME = "forecaster.joblib"
METADATA_FILENAME = "forecaster_metadata.json"
EVALUATION_PACKAGE = "meridian_eval"


class ArtifactBoundaryError(RuntimeError):
    """Raised when an artifact could not be served without evaluation code."""


@dataclass(frozen=True)
class ModelMetadata:
    """Provenance for one fitted model."""

    model_name: str
    calibration_method: str
    classes: tuple[str, ...]
    feature_names: tuple[str, ...]
    project_seed: int
    dataset_version: str
    split_digest: str
    package_versions: dict[str, str]
    metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    global_importance: dict[str, float] = field(default_factory=dict)

    def to_json(self) -> str:
        """Return stable, sorted JSON."""

        return json.dumps(asdict(self), indent=2, sort_keys=True, default=list) + "\n"


@dataclass(frozen=True)
class ModelArtifact:
    """A fitted estimator plus the metadata needed to trust its output."""

    estimator: Any
    metadata: ModelMetadata


def models_directory() -> Path:
    """Return the directory holding fitted model artifacts."""

    return repository_root() / "models"


def _estimator_modules(estimator: Any) -> set[str]:
    """Return the defining modules of `estimator` and any nested estimators."""

    modules = {type(estimator).__module__}
    for attribute in ("estimator", "base_estimator", "steps", "calibrated_classifiers_"):
        value = getattr(estimator, attribute, None)
        if value is None:
            continue
        candidates = value if isinstance(value, (list, tuple)) else [value]
        for candidate in candidates:
            inner = (
                candidate[1] if isinstance(candidate, tuple) and len(candidate) == 2 else candidate
            )
            if hasattr(inner, "__module__") or hasattr(type(inner), "__module__"):
                modules |= _estimator_modules(inner)
    return modules


def assert_servable(estimator: Any) -> None:
    """Raise if serving `estimator` would require the evaluation package.

    Raises:
        ArtifactBoundaryError: If any nested estimator is defined in
            `meridian_eval`, which runtime code must not import.
    """

    offenders = sorted(
        module
        for module in _estimator_modules(estimator)
        if module.split(".")[0] == EVALUATION_PACKAGE
    )
    if offenders:
        raise ArtifactBoundaryError(
            f"estimator depends on evaluation-only modules {offenders}; "
            "it cannot be served without breaking the runtime boundary"
        )


def save_artifact(artifact: ModelArtifact, directory: Path | None = None) -> Path:
    """Persist the estimator and its metadata, returning the artifact path."""

    assert_servable(artifact.estimator)
    target = directory if directory is not None else models_directory()
    target.mkdir(parents=True, exist_ok=True)
    path = target / ARTIFACT_FILENAME
    joblib.dump({"estimator": artifact.estimator, "metadata": asdict(artifact.metadata)}, path)
    (target / METADATA_FILENAME).write_text(artifact.metadata.to_json(), encoding="utf-8")
    return path


def load_artifact(directory: Path | None = None) -> ModelArtifact:
    """Load a previously fitted artifact.

    Raises:
        FileNotFoundError: If no artifact exists. Run `make train`.
    """

    target = directory if directory is not None else models_directory()
    path = target / ARTIFACT_FILENAME
    if not path.is_file():
        raise FileNotFoundError(f"no model artifact at {path}; run `make train` first")
    payload = joblib.load(path)
    record = dict(payload["metadata"])
    record["classes"] = tuple(record["classes"])
    record["feature_names"] = tuple(record["feature_names"])
    return ModelArtifact(estimator=payload["estimator"], metadata=ModelMetadata(**record))
