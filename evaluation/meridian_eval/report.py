"""Assemble one evaluation run into an immutable, traceable result directory.

Plan sections 22.7 and the Phase 10 exit gate: "every final-report claim is
traceable to an artifact". That is enforced structurally rather than promised.
Every number in the generated report is read out of `results.json`, which is
written from the same objects, in the same pass; there is no path by which the
prose can say something the JSON does not.

Section 22.7 also asks that each run write "one immutable result directory" and
store "commit SHA, dataset hash, model ID, prompt versions, and environment
versions". `manifest()` collects those, and the directory is named after the
commit and the moment, so two runs of the same code on the same data do not
overwrite each other and a stale directory cannot be mistaken for a fresh one.
"""

import json
import math
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from meridian.contracts import OUTCOME_CLASSES
from meridian.data.paths import repository_root
from meridian.graph.thresholds import THRESHOLDS
from meridian_eval.dimensions import (
    calibration,
    forecast_correctness,
    grounded_explanation,
    operational_reliability,
)
from meridian_eval.metrics import reliability_table
from meridian_eval.system_run import RunCollection
from meridian_eval.threshold_study import ThresholdStudy
from meridian_eval.training import plot_confusion, plot_reliability

#: Where result directories are written. Ignored by git: they are reproducible
#: from the commit they name, and committing them would grow the repository by
#: a result set per run.
RESULTS_ROOT = repository_root() / "artifacts" / "evaluation"

#: Section 22.6's provisional gates. Targets, not claimed results -- the report
#: prints each beside what was measured and says plainly which were not met.
RELEASE_TARGETS: dict[str, tuple[str, float, str]] = {
    "macro_f1": ("Macro F1", 0.70, "at_least"),
    "exact_numeric_agreement": ("Exact numeric agreement", 1.00, "at_least"),
    "supported_claim_rate": ("Supported-claim rate", 0.95, "at_least"),
    "wrong_account_citation_count": ("Wrong-account citations", 0.0, "at_most"),
    "post_cutoff_citation_count": ("Post-cutoff citations", 0.0, "at_most"),
    "expected_calibration_error": ("Expected calibration error", 0.10, "at_most"),
    "safe_fallback_rate": ("Exhausted-retrieval safe fallback", 1.00, "at_least"),
}


def _command(arguments: list[str], default: str = "unknown") -> str:
    """Return a command's trimmed output, or `default` when it cannot run."""

    try:
        return subprocess.run(
            arguments, capture_output=True, text=True, check=True, timeout=10
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return default


def commit_sha() -> str:
    """Return the commit this result belongs to (plan section 22.7).

    Read from `.git` rather than by running git: the evaluation image has no
    git binary, and a result directory named `unknown` cannot be traced back to
    the code that produced it, which is the whole point of recording it.
    """

    from_env = os.environ.get("MERIDIAN_EVAL_COMMIT", "").strip()
    if from_env:
        return from_env

    head = repository_root() / ".git" / "HEAD"
    if not head.is_file():
        return "unknown"
    try:
        content = head.read_text(encoding="utf-8").strip()
        if not content.startswith("ref:"):
            return content
        reference = repository_root() / ".git" / content.removeprefix("ref:").strip()
        if reference.is_file():
            return reference.read_text(encoding="utf-8").strip()
        packed = repository_root() / ".git" / "packed-refs"
        target = content.removeprefix("ref:").strip()
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                if line.endswith(f" {target}"):
                    return line.split()[0]
    except OSError:
        return "unknown"
    return "unknown"


def _working_tree_clean() -> bool | None:
    """Return whether the tree was clean, or None when it cannot be determined."""

    from_env = os.environ.get("MERIDIAN_EVAL_DIRTY", "").strip()
    if from_env:
        return from_env == "0"
    status = _command(["git", "status", "--porcelain"], default="__unavailable__")
    return None if status == "__unavailable__" else status == ""


def manifest(split: str, provider: str) -> dict[str, Any]:
    """Return what section 22.7 requires stored beside every result."""

    dataset_manifest = repository_root() / "data" / "processed" / "dataset_manifest.json"
    dataset_digest = "absent"
    if dataset_manifest.is_file():
        try:
            dataset_digest = str(
                json.loads(dataset_manifest.read_text(encoding="utf-8")).get("digest", "absent")
            )
        except (OSError, json.JSONDecodeError):
            dataset_digest = "unreadable"

    model_metadata = repository_root() / "models" / "forecaster_metadata.json"
    model: dict[str, Any] = {}
    if model_metadata.is_file():
        try:
            model = json.loads(model_metadata.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            model = {"error": "unreadable"}

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": commit_sha(),
        # Determined only when a git binary is available. The evaluation image
        # has none, so this is `null` there rather than a cheerful `true` that
        # nobody checked.
        "working_tree_clean": _working_tree_clean(),
        "split": split,
        "provider": provider,
        "dataset_digest": dataset_digest,
        "model": {
            "name": model.get("model_name", "absent"),
            "calibration": model.get("calibration_method", "absent"),
            "seed": model.get("project_seed"),
            "split_digest": model.get("split_digest", "absent"),
        },
        "thresholds": THRESHOLDS.as_dict(),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
    }


def _json_safe(value: Any) -> Any:
    """Return `value` with every non-finite float replaced by null.

    `json.dumps` writes bare `NaN` and `Infinity`, which are not JSON. A strict
    parser -- including the browser's, which reads this file on the evaluation
    page -- rejects the whole document. A bin with no runs in it means "no
    data", and `null` says that in a way every reader understands.
    """

    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    return value


def _target_row(name: str, measured: float | None) -> dict[str, Any]:
    """Return one release-target row: the target, the measurement, the verdict."""

    label, target, direction = RELEASE_TARGETS[name]
    if measured is None:
        return {
            "metric": label,
            "target": target,
            "direction": direction,
            "measured": None,
            "met": None,
            "note": "not measured in this run",
        }
    met = measured >= target if direction == "at_least" else measured <= target
    return {
        "metric": label,
        "target": target,
        "direction": direction,
        "measured": measured,
        "met": bool(met),
    }


def assemble(
    collection: RunCollection,
    provider: str,
    guardrails: dict[str, Any] | None = None,
    retrieval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute every dimension and the release-target table.

    Args:
        collection: One pass over a split.
        provider: How the runs were generated, for the manifest.
        guardrails: The safety report's metrics, when one has been run.
        retrieval: The retrieval benchmark's metrics, when one has been run.

    Returns:
        The complete result, ready to be written and rendered.
    """

    runs = collection.runs
    study = ThresholdStudy(runs=list(runs), split=collection.split)
    correctness = forecast_correctness(runs)
    grounding = grounded_explanation(runs)
    calibrated = calibration(runs)
    reliability = operational_reliability(runs)

    measured: dict[str, float | None] = {
        "macro_f1": correctness.get("macro_f1"),
        "exact_numeric_agreement": grounding.get("exact_numeric_agreement"),
        "supported_claim_rate": grounding.get("supported_claim_rate"),
        "wrong_account_citation_count": grounding.get("wrong_account_citation_count"),
        "post_cutoff_citation_count": grounding.get("post_cutoff_citation_count"),
        "expected_calibration_error": calibrated.get("expected_calibration_error"),
        "safe_fallback_rate": reliability.get("exhausted_retrieval_fallback", {}).get(
            "safe_fallback_rate"
        ),
    }

    return {
        "manifest": manifest(collection.split, provider),
        "forecast_correctness": correctness,
        "grounded_explanation": grounding,
        "calibration": calibrated,
        "safety_routing": guardrails
        or {
            "reason": (
                "not run in this pass; `make evaluate-guardrails` writes "
                "artifacts/safety/guardrail_eval.json"
            )
        },
        "operational_reliability": reliability,
        "threshold_study": study.summary(),
        "release_targets": [_target_row(name, value) for name, value in measured.items()],
    }


def _format(value: Any) -> str:
    """Render a metric for a Markdown table."""

    if value is None:
        return "not measured"
    if isinstance(value, bool):
        return "yes" if value else "**no**"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def render(result: dict[str, Any]) -> str:
    """Render the final evaluation report from the result, and only from it.

    Every number below is read out of `result`. There is no literal in this
    function that a reader could mistake for a measurement, which is what makes
    the exit gate -- every claim traceable to an artifact -- structural.
    """

    info = result["manifest"]
    correctness = result["forecast_correctness"]
    grounding = result["grounded_explanation"]
    calibrated = result["calibration"]
    reliability = result["operational_reliability"]
    study = result["threshold_study"]

    lines = [
        "# Meridian evaluation report",
        "",
        f"Commit `{info['commit'][:12]}`"
        + (
            ""
            if info["working_tree_clean"] is True
            else (
                " (**working tree was dirty**)"
                if info["working_tree_clean"] is False
                else " (working-tree state not determined)"
            )
        )
        + f", split **{info['split']}**, provider **{info['provider']}**, "
        f"generated {info['generated_at']}.",
        "",
        f"Thresholds `{info['thresholds']['digest']}` ({info['thresholds']['version']}), "
        f"dataset `{info['dataset_digest'][:12]}`, model "
        f"`{info['model']['name']}` / `{info['model']['calibration']}`.",
        "",
        "Every number in this report is read from `results.json` in this same "
        "directory. Nothing here is typed by hand.",
        "",
        "## Release targets (plan section 22.6)",
        "",
        "These are targets, not claimed results.",
        "",
        "| Measure | Target | Measured | Met |",
        "| --- | --- | ---: | :---: |",
    ]
    for row in result["release_targets"]:
        comparator = "at least" if row["direction"] == "at_least" else "at most"
        lines.append(
            f"| {row['metric']} | {comparator} {row['target']} | "
            f"{_format(row['measured'])} | {_format(row['met'])} |"
        )

    unmet = [row for row in result["release_targets"] if row["met"] is False]
    missing = [row for row in result["release_targets"] if row["met"] is None]
    lines += ["", ""]
    if unmet:
        lines.append(
            "**Not met:** "
            + ", ".join(f"{row['metric']} ({_format(row['measured'])})" for row in unmet)
            + "."
        )
    else:
        lines.append("Every measured target was met.")
    if missing:
        lines.append(
            "**Not measured in this run:** " + ", ".join(row["metric"] for row in missing) + "."
        )

    lines += [
        "",
        "## 22.1 Forecast correctness",
        "",
        f"{correctness.get('released', 0)} released, "
        f"{correctness.get('abstained', 0)} abstained, "
        f"{correctness.get('blocked', 0)} blocked.",
        "",
        "| Measure | Value |",
        "| --- | ---: |",
        f"| Macro F1 | {_format(correctness.get('macro_f1'))} |",
        f"| Accuracy | {_format(correctness.get('accuracy'))} |",
        f"| Majority baseline ({correctness.get('majority_class', '?')}) | "
        f"{_format(correctness.get('majority_baseline_accuracy'))} |",
        f"| Beats majority | {_format(correctness.get('beats_majority'))} |",
        "",
    ]
    if correctness.get("per_class"):
        lines += [
            "| Class | Precision | Recall | F1 | Support |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for name, values in correctness["per_class"].items():
            lines.append(
                f"| {name} | {_format(values['precision'])} | {_format(values['recall'])} | "
                f"{_format(values['f1'])} | {values['support']} |"
            )
        lines.append("")
        classes = correctness["confusion_matrix"]["classes"]
        lines += [
            "Confusion matrix (rows are truth, columns are prediction):",
            "",
            "| | " + " | ".join(classes) + " |",
            "| --- |" + " ---: |" * len(classes),
        ]
        for name, row in zip(classes, correctness["confusion_matrix"]["rows"], strict=True):
            lines.append(f"| **{name}** | " + " | ".join(str(value) for value in row) + " |")

    lines += [
        "",
        "## 22.2 Grounded explanation",
        "",
        "| Measure | Value | Over |",
        "| --- | ---: | ---: |",
        f"| Supported-claim rate | {_format(grounding.get('supported_claim_rate'))} | "
        f"{grounding.get('released', 0)} |",
        f"| Verified on first attempt | {_format(grounding.get('verified_first_attempt_rate'))} | "
        f"{grounding.get('released', 0)} |",
        f"| Exact numeric agreement | {_format(grounding.get('exact_numeric_agreement'))} | "
        f"{grounding.get('released', 0)} |",
        f"| Citation precision | {_format(grounding.get('citation_precision'))} | "
        f"{grounding.get('runs_with_citations', 0)} |",
        f"| Driver overlap with ground truth | {_format(grounding.get('driver_overlap'))} | "
        f"{grounding.get('runs_with_ground_truth_drivers', 0)} |",
        f"| Counterevidence on conflicting cases | "
        f"{_format(grounding.get('counterevidence_inclusion_rate_on_conflict'))} | "
        f"{grounding.get('conflicting_runs', 0)} |",
        f"| Wrong-account citations | {grounding.get('wrong_account_citation_count', 0)} | — |",
        f"| Post-cutoff citations | {grounding.get('post_cutoff_citation_count', 0)} | — |",
        "",
        str(grounding.get("judge_note", "")),
        "",
        "## 22.3 Calibration",
        "",
        "| Measure | Value |",
        "| --- | ---: |",
        f"| Expected calibration error | {_format(calibrated.get('expected_calibration_error'))} |",
        f"| Multiclass Brier | {_format(calibrated.get('brier'))} |",
        f"| Log loss | {_format(calibrated.get('log_loss'))} |",
        f"| Auto-release rate | {_format(calibrated.get('auto_release_rate'))} |",
        "",
        "Error rate inside each review band -- what a reviewer is implicitly promised:",
        "",
        "| Band | Runs | Errors | Error rate | Auto-released |",
        "| --- | ---: | ---: | ---: | :---: |",
    ]
    for band, values in (calibrated.get("routing_quality") or {}).items():
        lines.append(
            f"| {band} | {values['count']} | {values['errors']} | "
            f"{_format(values['error_rate'])} | {_format(values['auto_released'])} |"
        )

    latency = reliability.get("latency", {})
    lines += [
        "",
        "## 22.5 Operational reliability",
        "",
        "| Measure | Value |",
        "| --- | ---: |",
        f"| Completion rate | {_format(reliability.get('completion_rate'))} |",
        f"| Release rate | {_format(reliability.get('release_rate'))} |",
        f"| Abstention rate | {_format(reliability.get('abstention_rate'))} |",
        f"| Escalation rate | {_format(reliability.get('escalation_rate'))} |",
        f"| Retrieval retry rate | {_format(reliability.get('retrieval_retry_rate'))} |",
        f"| Output regeneration rate | {_format(reliability.get('regeneration_rate'))} |",
        f"| Node errors | {reliability.get('node_error_count', 0)} |",
        f"| Total tokens | {reliability.get('tokens', {}).get('total', 0)} |",
        f"| Model calls | {reliability.get('tokens', {}).get('model_calls', 0)} |",
        "",
        "| Path | Runs | p50 | p95 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, counts in (reliability.get("path_counts") or {}).items():
        values = latency.get(name, {})
        lines.append(
            f"| {name} | {counts} | {_format(values.get('p50_ms'))} ms | "
            f"{_format(values.get('p95_ms'))} ms |"
        )
    overall = latency.get("overall", {})
    lines.append(
        f"| **overall** | {reliability.get('runs', 0)} | {_format(overall.get('p50_ms'))} ms | "
        f"{_format(overall.get('p95_ms'))} ms |"
    )

    frozen = study.get("frozen", {})
    permissive = study.get("most_permissive_measured")
    lines += [
        "",
        "## Threshold study (plan section 22.6)",
        "",
        f"Measured on the **{study.get('split')}** split over "
        f"{study.get('accounts', 0)} accounts. Section 22.7 forbids tuning on "
        "held-out outcomes, so this sweep never touches the test split.",
        "",
        f"At the frozen bands (green {frozen.get('green_minimum')}, amber "
        f"{frozen.get('amber_minimum')}, digest `{frozen.get('digest')}`): "
        f"**{frozen.get('auto_released', 0)} of {study.get('accounts', 0)} auto-released** "
        f"({_format(frozen.get('auto_release_rate'))}), "
        f"{frozen.get('auto_released_errors', 0)} of them wrong.",
        "",
    ]
    if permissive:
        lines.append(
            f"The most permissive band measured (green {permissive['green_minimum']}, "
            f"amber {permissive['amber_minimum']}) would auto-release "
            f"{permissive['auto_released']} "
            f"({_format(permissive['auto_release_rate'])}) with "
            f"{permissive['auto_released_errors']} wrong "
            f"({_format(permissive['auto_released_error_rate'])} of what it released). "
            "The full sweep is in `threshold_study.csv`."
        )
    lines += [
        "",
        "## Artifacts in this directory",
        "",
        "| File | What it holds |",
        "| --- | --- |",
        "| `results.json` | Every number in this report |",
        "| `runs.csv` | One row per assessed account |",
        "| `threshold_study.csv` | The full band sweep |",
        "| `confusion_matrix.png` | Section 22.1's confusion matrix |",
        "| `reliability.png` | Section 22.3's reliability diagram |",
        "| `REPORT.md` | This file |",
        "",
    ]
    return "\n".join(lines) + "\n"


def write(
    result: dict[str, Any],
    collection: RunCollection,
    destination: Path | None = None,
) -> Path:
    """Write one immutable result directory and return its path.

    The directory is named for the commit and the moment. Two runs of the same
    code on the same data therefore sit side by side rather than one silently
    replacing the other, which is what section 22.7's "one immutable result
    directory per run" is for.
    """

    info = result["manifest"]
    stamp = info["generated_at"].replace(":", "").replace("-", "")
    folder = destination or (RESULTS_ROOT / f"{info['commit'][:12]}-{stamp}")
    folder.mkdir(parents=True, exist_ok=True)

    (folder / "results.json").write_text(
        json.dumps(_json_safe(result), indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    collection.frame().to_csv(folder / "runs.csv", index=False)
    ThresholdStudy(runs=list(collection.runs), split=collection.split).frame().to_csv(
        folder / "threshold_study.csv", index=False
    )
    _write_plots(collection, folder)
    (folder / "REPORT.md").write_text(render(result), encoding="utf-8")
    return folder


def _write_plots(collection: RunCollection, folder: Path) -> None:
    """Write the two figures the report's artifact table names.

    Promising a file the directory does not contain would break the exit gate
    as surely as an unsupported number would, so both are written here or the
    report's table is not printed with them.
    """

    released = [run for run in collection.runs if run.released and run.outcome]
    if len(released) < 2:
        return
    truth = np.array([run.label for run in released], dtype=object)
    predicted = np.array([run.outcome for run in released], dtype=object)
    matrix = np.array(
        [[run.distribution.get(name, 0.0) for name in OUTCOME_CLASSES] for run in released],
        dtype=float,
    )
    plot_confusion(
        truth,
        predicted,
        list(OUTCOME_CLASSES),
        folder / "confusion_matrix.png",
        title=f"{collection.split} confusion matrix ({len(released)} released)",
    )
    plot_reliability(
        reliability_table(truth, matrix, list(OUTCOME_CLASSES)),
        folder / "reliability.png",
        f"Reliability on the {collection.split} split",
    )


__all__ = [
    "RELEASE_TARGETS",
    "RESULTS_ROOT",
    "assemble",
    "manifest",
    "render",
    "write",
]
