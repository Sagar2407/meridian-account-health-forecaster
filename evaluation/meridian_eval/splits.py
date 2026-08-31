"""Deterministic split generation (plan section 8.5).

Stratification needs outcome labels, so this lives in the evaluation package.
The artifact it writes contains account ids only, which is why runtime code can
safely read it back through `meridian.data.splits`.

The split is a pure function of (sorted account ids, outcome labels, seed), so
regenerating it on any machine reproduces it byte for byte.
"""

import json
from pathlib import Path

import numpy as np

from meridian.data.constants import PROJECT_SEED
from meridian.data.paths import splits_directory
from meridian.data.splits import SPLIT_FILENAME, AccountSplit
from meridian_eval.repository import EvaluationRepository

TRAIN_FRACTION = 0.60
VALIDATION_FRACTION = 0.20


def build_split(
    repository: EvaluationRepository | None = None,
    seed: int = PROJECT_SEED,
) -> tuple[AccountSplit, dict[str, dict[str, int]]]:
    """Return a stratified 60/20/20 split and its per-outcome counts.

    Accounts are grouped by outcome, sorted for determinism, permuted with a
    seeded generator, then sliced. Stratifying keeps all four outcomes present in
    each partition, which matters because only 260 accounts exist.
    """

    source = repository if repository is not None else EvaluationRepository()
    labels = source.labels()
    generator = np.random.default_rng(seed)

    train: list[str] = []
    validation: list[str] = []
    test: list[str] = []
    counts: dict[str, dict[str, int]] = {}

    for outcome in sorted(labels.unique()):
        members = sorted(labels.index[labels == outcome])
        order = generator.permutation(len(members))
        shuffled = [members[index] for index in order]

        total = len(shuffled)
        train_size = round(total * TRAIN_FRACTION)
        validation_size = round(total * VALIDATION_FRACTION)

        train.extend(shuffled[:train_size])
        validation.extend(shuffled[train_size : train_size + validation_size])
        test.extend(shuffled[train_size + validation_size :])
        counts[str(outcome)] = {
            "total": total,
            "train": train_size,
            "validation": validation_size,
            "test": total - train_size - validation_size,
        }

    split = AccountSplit(
        seed=seed,
        train=tuple(sorted(train)),
        validation=tuple(sorted(validation)),
        test=tuple(sorted(test)),
    )
    return split, counts


def write_split(
    split: AccountSplit,
    counts: dict[str, dict[str, int]],
    directory: Path | None = None,
) -> Path:
    """Write the split as stable, sorted JSON and return its path."""

    target = directory if directory is not None else splits_directory()
    target.mkdir(parents=True, exist_ok=True)
    path = target / SPLIT_FILENAME
    payload = {
        "seed": split.seed,
        "proportions": {
            "train": TRAIN_FRACTION,
            "validation": VALIDATION_FRACTION,
            "test": round(1.0 - TRAIN_FRACTION - VALIDATION_FRACTION, 10),
        },
        "stratified_by": "outcome",
        "stratum_counts": counts,
        "splits": {
            "train": list(split.train),
            "validation": list(split.validation),
            "test": list(split.test),
        },
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
