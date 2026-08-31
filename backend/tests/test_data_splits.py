"""Deterministic split guarantees (plan section 8.5)."""

from pathlib import Path

import pytest

from meridian.data.constants import PROJECT_SEED
from meridian.data.loader import RawDataset
from meridian.data.splits import AccountSplit, read_split
from meridian_eval.repository import EvaluationRepository
from meridian_eval.splits import build_split, write_split


@pytest.fixture(scope="module")
def evaluation(dataset: RawDataset) -> EvaluationRepository:
    """Return an evaluation repository over the session dataset."""

    return EvaluationRepository(dataset)


def test_split_covers_every_account_exactly_once(
    evaluation: EvaluationRepository, dataset: RawDataset
) -> None:
    """The three partitions must tile the account set with no overlap."""

    split, _ = build_split(evaluation)
    combined = list(split.train) + list(split.validation) + list(split.test)
    assert len(combined) == len(set(combined)) == len(dataset.accounts)
    assert set(combined) == set(dataset.accounts["account_id"])


def test_split_is_reproducible(evaluation: EvaluationRepository) -> None:
    """The same seed and labels must reproduce the split exactly."""

    first, first_counts = build_split(evaluation, seed=PROJECT_SEED)
    second, second_counts = build_split(evaluation, seed=PROJECT_SEED)
    assert first == second
    assert first_counts == second_counts


def test_a_different_seed_changes_the_split(evaluation: EvaluationRepository) -> None:
    """Confirms the split genuinely depends on the seed."""

    baseline, _ = build_split(evaluation, seed=PROJECT_SEED)
    alternative, _ = build_split(evaluation, seed=PROJECT_SEED + 1)
    assert baseline != alternative


def test_every_outcome_appears_in_every_partition(evaluation: EvaluationRepository) -> None:
    """Stratification must keep all four outcomes represented everywhere."""

    split, _ = build_split(evaluation)
    labels = evaluation.labels()
    outcomes = set(labels.unique())
    for partition in (split.train, split.validation, split.test):
        assert set(labels.loc[list(partition)].unique()) == outcomes


def test_partition_sizes_are_close_to_the_target_ratio(
    evaluation: EvaluationRepository,
) -> None:
    """Section 8.5 asks for roughly 60/20/20 across only 260 accounts."""

    split, _ = build_split(evaluation)
    total = len(split)
    assert 0.57 <= len(split.train) / total <= 0.63
    assert 0.17 <= len(split.validation) / total <= 0.23
    assert 0.17 <= len(split.test) / total <= 0.23


def test_development_excludes_the_held_out_test(evaluation: EvaluationRepository) -> None:
    """The final test set must never leak into model selection."""

    split, _ = build_split(evaluation)
    assert not set(split.development) & set(split.test)
    assert set(split.development) == set(split.train) | set(split.validation)


def test_overlapping_partitions_are_rejected() -> None:
    """A malformed split file must fail loudly on construction."""

    with pytest.raises(ValueError, match="overlap"):
        AccountSplit(seed=1, train=("ACC-1",), validation=("ACC-1",), test=("ACC-2",))


def test_split_round_trips_through_disk(evaluation: EvaluationRepository, tmp_path: Path) -> None:
    """Writing then reading the split must preserve it exactly."""

    split, counts = build_split(evaluation)
    write_split(split, counts, tmp_path)
    assert read_split(tmp_path) == split


def test_missing_split_file_names_the_remedy(tmp_path: Path) -> None:
    """A helpful error beats a stack trace when the split has not been built."""

    with pytest.raises(FileNotFoundError, match="make data"):
        read_split(tmp_path)
