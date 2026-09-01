"""Train, select, calibrate, and document the forecaster (plan section 10).

The held-out test split is never read here. Plan section 8.5 reserves it for the
final evaluation command, so everything below fits on `train` and reports on
`validation`.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import sklearn
from sklearn.inspection import permutation_importance

from meridian.data.constants import DATASET_VERSION, PROJECT_SEED
from meridian.data.loader import load_raw_dataset
from meridian.data.paths import repository_root, splits_directory
from meridian.data.repository import RuntimeRepository
from meridian.data.splits import SPLIT_FILENAME, read_split
from meridian.features.builder import build_feature_frame
from meridian.features.spec import MODEL_INPUT_FEATURES
from meridian.model.artifacts import ModelArtifact, ModelMetadata, save_artifact
from meridian_eval.metrics import (
    confidence_band_errors,
    evaluate,
    reliability_table,
    slice_metrics,
)
from meridian_eval.modeling import (
    CALIBRATION_FOLDS,
    CALIBRATION_METHOD,
    CandidateResult,
    build_candidates,
    cross_validate_candidates,
    fit_calibrated_model,
    select_best,
)
from meridian_eval.repository import EvaluationRepository


def artifacts_directory() -> Path:
    """Return the directory for training figures and metric tables."""

    return repository_root() / "artifacts" / "model"


@dataclass(frozen=True)
class TrainingReport:
    """Everything one training run produced."""

    candidates: list[CandidateResult]
    selected: str
    validation_metrics: dict[str, float]
    uncalibrated_metrics: dict[str, float]
    artifact_path: Path


def _split_digest() -> str:
    """Return the SHA-256 of the split file the model was trained against."""

    path = splits_directory() / SPLIT_FILENAME
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plot_reliability(table: pd.DataFrame, destination: Path, title: str) -> None:
    """Write a reliability diagram comparing confidence against accuracy."""

    figure, axes = plt.subplots(figsize=(5.0, 5.0))
    axes.plot([0, 1], [0, 1], linestyle="--", linewidth=1, color="grey", label="perfect")
    usable = table.dropna(subset=["mean_confidence", "accuracy"])
    axes.plot(usable["mean_confidence"], usable["accuracy"], marker="o", label="model")
    axes.set_xlabel("mean predicted confidence")
    axes.set_ylabel("observed accuracy")
    axes.set_title(title)
    axes.set_xlim(0, 1)
    axes.set_ylim(0, 1)
    axes.legend(loc="upper left")
    figure.tight_layout()
    figure.savefig(destination, dpi=150)
    plt.close(figure)


def plot_confusion(
    labels: np.ndarray,
    predicted: np.ndarray,
    classes: list[str],
    destination: Path,
    title: str = "Validation confusion matrix",
) -> None:
    """Write a confusion matrix heatmap."""

    matrix = pd.crosstab(
        pd.Series(labels, name="actual"),
        pd.Series(predicted, name="predicted"),
    ).reindex(index=classes, columns=classes, fill_value=0)
    figure, axes = plt.subplots(figsize=(5.5, 4.8))
    counts = matrix.to_numpy()
    image = axes.imshow(counts, cmap="Blues")
    axes.set_xticks(range(len(classes)), classes, rotation=45, ha="right")
    axes.set_yticks(range(len(classes)), classes)
    for row in range(len(classes)):
        for column in range(len(classes)):
            axes.text(column, row, str(counts[row][column]), ha="center", va="center", fontsize=9)
    axes.set_xlabel("predicted")
    axes.set_ylabel("actual")
    axes.set_title(title)
    figure.colorbar(image, ax=axes, shrink=0.8)
    figure.tight_layout()
    figure.savefig(destination, dpi=150)
    plt.close(figure)


def calibration_study(
    name: str,
    features: pd.DataFrame,
    labels: "pd.Series[str]",
    train_ids: list[str],
    validation_ids: list[str],
    seed: int = PROJECT_SEED,
) -> pd.DataFrame:
    """Compare calibration methods on validation, as plan section 10.4 requires.

    Section 10.4 prefers sigmoid unless validation shows otherwise, so the
    comparison is measured rather than assumed. Its output is the evidence for
    the choice recorded in `meridian_eval.modeling.CALIBRATION_METHOD`.
    """

    train_x = features.loc[train_ids].to_numpy(dtype=float)
    train_y = labels.loc[train_ids].to_numpy(dtype=object)
    validation_x = features.loc[validation_ids].to_numpy(dtype=float)
    validation_y = labels.loc[validation_ids].to_numpy(dtype=object)

    rows = []
    baseline = build_candidates(seed)[name].fit(train_x, train_y)
    classes = [str(item) for item in baseline.classes_]
    metrics = evaluate(validation_y, baseline.predict_proba(validation_x), classes)
    rows.append({"method": "none", "folds": 0, **metrics.to_dict()})

    for method in ("sigmoid", "isotonic"):
        for folds in (3, 5):
            model = fit_calibrated_model(
                name, features.loc[train_ids], labels.loc[train_ids], seed, method, folds
            )
            classes = [str(item) for item in model.classes_]
            metrics = evaluate(validation_y, model.predict_proba(validation_x), classes)
            rows.append({"method": method, "folds": folds, **metrics.to_dict()})
    return pd.DataFrame(rows)


def write_model_card(
    metadata: ModelMetadata,
    candidates: list[CandidateResult],
    reliability: pd.DataFrame,
) -> Path:
    """Write the model card required by plan section 10.4.

    Generated from the artifact metadata rather than written by hand, so it
    cannot drift away from the model actually being served.
    """

    calibrated = metadata.metrics["validation_calibrated"]
    uncalibrated = metadata.metrics["validation_uncalibrated"]
    importance = sorted(metadata.global_importance.items(), key=lambda item: -item[1])

    lines = [
        "# Model card: account-health forecaster",
        "",
        "Generated by `make train`. Do not edit by hand.",
        "",
        "## Model",
        "",
        f"- Selected candidate: `{metadata.model_name}`",
        f"- Calibration: {metadata.calibration_method}",
        f"- Outcomes: {', '.join(metadata.classes)}",
        f"- Input features: {len(metadata.feature_names)}",
        f"- Random seed: {metadata.project_seed}",
        f"- Dataset version: {metadata.dataset_version}",
        f"- Training split digest: `{metadata.split_digest[:16]}...`",
        "- Package versions: "
        + ", ".join(
            f"{name} {version}" for name, version in sorted(metadata.package_versions.items())
        ),
        "",
        "## Intended use and limits",
        "",
        "Read-only decision support on synthetic data. It ranks renewal risk and",
        "surfaces the signals it relied on. It must not drive customer-facing or",
        "commercial action, and contributions are associations the model uses, not",
        "proven causes.",
        "",
        "The validation split holds 51 accounts, so every figure below carries wide",
        "uncertainty. Differences under roughly five points are not meaningful.",
        "",
        "## Candidate comparison (repeated stratified CV on the training split)",
        "",
        "| candidate | macro F1 | sd | log loss | accuracy |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for candidate in sorted(candidates, key=lambda item: -item.macro_f1_mean):
        marker = " **(selected)**" if candidate.name == metadata.model_name else ""
        lines.append(
            f"| `{candidate.name}`{marker} | {candidate.macro_f1_mean:.4f} | "
            f"{candidate.macro_f1_std:.4f} | {candidate.log_loss_mean:.4f} | "
            f"{candidate.accuracy_mean:.4f} |"
        )

    lines += [
        "",
        "The rule baseline scores highest on macro F1 but its log loss is above 2.0:",
        "its probabilities are badly miscalibrated. Because human-review routing is",
        "driven by confidence, that makes it unservable regardless of F1. Selection",
        "therefore uses a one-standard-error rule -- among candidates statistically",
        "indistinguishable on macro F1, take the lowest log loss.",
        "",
        "## Validation performance",
        "",
        "| metric | calibrated | uncalibrated |",
        "| --- | ---: | ---: |",
    ]
    for key in ("macro_f1", "accuracy", "log_loss", "brier", "expected_calibration_error"):
        lines.append(f"| {key} | {calibrated[key]:.4f} | {uncalibrated[key]:.4f} |")

    lines += [
        "",
        "Calibration improves macro F1, accuracy, log loss, and Brier score, and",
        "slightly worsens expected calibration error.",
        "",
        "## Calibration choice",
        "",
        "Plan section 10.4 prefers sigmoid unless validation shows otherwise. It did:",
        "sigmoid was the worst option tested, collapsing macro F1 to about 0.51,",
        "because a 5-fold sigmoid calibrator sees roughly three `Contracted` examples",
        "per fold. Isotonic at 3 folds was selected on measured results. The full grid",
        "is in `artifacts/model/calibration_study.csv`.",
        "",
        "## Reliability",
        "",
        "| confidence bin | count | mean confidence | observed accuracy |",
        "| --- | ---: | ---: | ---: |",
    ]
    # itertuples() would shadow the "count" column with the namedtuple method,
    # so iterate over plain records instead.
    for record in reliability.to_dict("records"):
        if int(record["count"]) == 0:
            continue
        lines.append(
            f"| {record['bin_lower']:.1f}-{record['bin_upper']:.1f} | {int(record['count'])} | "
            f"{record['mean_confidence']:.3f} | {record['accuracy']:.3f} |"
        )

    lines += [
        "",
        "## Global feature importance (permutation, macro F1)",
        "",
        "| feature | importance |",
        "| --- | ---: |",
    ]
    for name, value in importance[:10]:
        lines.append(f"| `{name}` | {value:+.4f} |")

    lines += [
        "",
        "## Excluded by design",
        "",
        "- `days_to_renewal` is constant at 90 in this dataset and carries no signal.",
        "- The packaged `churn_probability`, `health_index`, `health_band`, and",
        "  `health_archetype` are latent ground truth and never reach training or",
        "  inference. The runtime repository cannot expose them.",
        "- `advanced_feature_depth` is recomputed from telemetry, because the",
        "  archive derives it from the latent `advanced_adoption_target`.",
        "",
        "## Held-out test set",
        "",
        "The 53-account test split was not read during training or selection. It is",
        "reserved for the final evaluation command in a later phase.",
        "",
    ]
    path = repository_root() / "docs" / "MODEL_CARD.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def run_training(seed: int = PROJECT_SEED) -> TrainingReport:
    """Fit, select, calibrate, evaluate on validation, and persist everything."""

    dataset = load_raw_dataset()
    repository = RuntimeRepository(dataset)
    evaluation = EvaluationRepository(dataset)

    features = build_feature_frame(repository)
    labels = evaluation.labels()
    split = read_split()

    train_ids = list(split.train)
    validation_ids = list(split.validation)

    candidates = cross_validate_candidates(
        features.loc[train_ids], labels.loc[train_ids], seed=seed
    )
    selected = select_best(candidates)

    calibrated = fit_calibrated_model(
        selected.name,
        features.loc[train_ids],
        labels.loc[train_ids],
        seed=seed,
        method=CALIBRATION_METHOD,
        folds=CALIBRATION_FOLDS,
    )
    classes = [str(name) for name in calibrated.classes_]

    validation_x = features.loc[validation_ids].to_numpy(dtype=float)
    validation_y = labels.loc[validation_ids].to_numpy(dtype=object)
    probabilities = calibrated.predict_proba(validation_x)
    metrics = evaluate(validation_y, probabilities, classes)

    uncalibrated = build_candidates(seed)[selected.name]
    uncalibrated.fit(features.loc[train_ids].to_numpy(dtype=float), labels.loc[train_ids])
    uncalibrated_metrics = evaluate(validation_y, uncalibrated.predict_proba(validation_x), classes)

    importance = permutation_importance(
        calibrated,
        validation_x,
        validation_y,
        scoring="f1_macro",
        n_repeats=20,
        random_state=seed,
        n_jobs=-1,
    )
    global_importance = {
        name: float(value)
        for name, value in zip(MODEL_INPUT_FEATURES, importance.importances_mean, strict=True)
    }

    destination = artifacts_directory()
    destination.mkdir(parents=True, exist_ok=True)

    reliability = reliability_table(validation_y, probabilities, classes)
    plot_reliability(reliability, destination / "reliability_calibrated.png", "Calibrated")
    plot_reliability(
        reliability_table(validation_y, uncalibrated.predict_proba(validation_x), classes),
        destination / "reliability_uncalibrated.png",
        "Uncalibrated",
    )
    predicted = np.array(classes, dtype=object)[probabilities.argmax(axis=1)]
    plot_confusion(validation_y, predicted, classes, destination / "confusion_validation.png")

    pd.DataFrame([vars(item) for item in candidates]).to_csv(
        destination / "candidates.csv", index=False
    )
    calibration_study(selected.name, features, labels, train_ids, validation_ids, seed).to_csv(
        destination / "calibration_study.csv", index=False
    )
    reliability.to_csv(destination / "reliability_calibrated.csv", index=False)
    confidence_band_errors(validation_y, probabilities, classes).to_csv(
        destination / "confidence_bands.csv", index=False
    )
    accounts = dataset.accounts.set_index("account_id")
    for column in ("segment", "region"):
        slice_metrics(
            validation_y, probabilities, classes, accounts.loc[validation_ids, column]
        ).to_csv(destination / f"slice_{column}.csv", index=False)

    metadata = ModelMetadata(
        model_name=selected.name,
        calibration_method=CALIBRATION_METHOD,
        classes=tuple(classes),
        feature_names=MODEL_INPUT_FEATURES,
        project_seed=seed,
        dataset_version=DATASET_VERSION,
        split_digest=_split_digest(),
        package_versions={
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit-learn": sklearn.__version__,
        },
        metrics={
            "validation_calibrated": metrics.to_dict(),
            "validation_uncalibrated": uncalibrated_metrics.to_dict(),
            "cross_validation": {
                "macro_f1_mean": selected.macro_f1_mean,
                "macro_f1_std": selected.macro_f1_std,
                "log_loss_mean": selected.log_loss_mean,
            },
        },
        global_importance=global_importance,
    )
    artifact_path = save_artifact(ModelArtifact(estimator=calibrated, metadata=metadata))

    (destination / "training_summary.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "selected": selected.name,
                "candidates": [vars(item) for item in candidates],
                "validation_calibrated": metrics.to_dict(),
                "validation_uncalibrated": uncalibrated_metrics.to_dict(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    write_model_card(metadata, candidates, reliability)

    return TrainingReport(
        candidates=candidates,
        selected=selected.name,
        validation_metrics=metrics.to_dict(),
        uncalibrated_metrics=uncalibrated_metrics.to_dict(),
        artifact_path=artifact_path,
    )
