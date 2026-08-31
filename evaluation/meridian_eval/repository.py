"""The evaluation-only repository.

Everything here is forbidden at runtime. Import it from evaluation scripts,
notebooks, and tests only.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from meridian.data.loader import RawDataset, load_raw_dataset
from meridian.data.paths import raw_dataset_directory


@dataclass(frozen=True)
class GoldenQuestion:
    """One curated evaluation question and its derived correct answer."""

    id: str
    question: str
    answer_type: str
    ground_truth: Any


class EvaluationRepository:
    """Read access to labels, latent health, and curated evaluation sets."""

    def __init__(self, dataset: RawDataset | None = None, archive: Path | None = None) -> None:
        self._dataset = dataset if dataset is not None else load_raw_dataset()
        self._archive = archive if archive is not None else raw_dataset_directory()

    def outcomes(self) -> pd.DataFrame:
        """Return the renewal outcome table, including labels and latent health."""

        return self._dataset.renewal_outcomes.copy()

    def labels(self) -> pd.Series:
        """Return the outcome label indexed by account id."""

        frame = self.outcomes().set_index("account_id")
        return frame["outcome"]

    def latent_accounts(self) -> pd.DataFrame:
        """Return account ids with their latent archetype and health band."""

        return self._dataset.accounts.loc[
            :, ["account_id", "health_archetype", "health_band", "usage_cliff_date"]
        ].copy()

    def ground_truth_drivers(self) -> pd.DataFrame:
        """Return per-account true driver contributions."""

        path = self._archive / "eval" / "ground_truth_drivers.json"
        records = json.loads(path.read_text(encoding="utf-8"))
        return pd.DataFrame.from_records(records)

    def golden_questions(self) -> tuple[GoldenQuestion, ...]:
        """Return the curated golden question set."""

        path = self._archive / "eval" / "golden_qa.jsonl"
        questions: list[GoldenQuestion] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            questions.append(
                GoldenQuestion(
                    id=record["id"],
                    question=record["question"],
                    answer_type=record["answer_type"],
                    ground_truth=record["ground_truth"],
                )
            )
        return tuple(questions)

    def guardrail_cases(self) -> tuple[dict[str, Any], ...]:
        """Return the packaged guardrail evaluation cases."""

        path = self._archive / "eval" / "guardrail_eval.jsonl"
        return tuple(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
