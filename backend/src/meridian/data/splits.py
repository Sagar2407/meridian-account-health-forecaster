"""Read access to the deterministic account split (plan section 8.5).

Runtime and training code read the split from disk. Generating it requires
outcome labels, so generation lives in `meridian_eval.splits` instead. This
module never sees a label: the split file holds account ids only.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from meridian.data.paths import splits_directory

SPLIT_FILENAME = "account_split.json"


@dataclass(frozen=True)
class AccountSplit:
    """A 60/20/20 development-train, development-validation, held-out-test split."""

    seed: int
    train: tuple[str, ...]
    validation: tuple[str, ...]
    test: tuple[str, ...]

    def __post_init__(self) -> None:
        overlap = (
            (set(self.train) & set(self.validation))
            | (set(self.train) & set(self.test))
            | (set(self.validation) & set(self.test))
        )
        if overlap:
            raise ValueError(f"split partitions overlap on {sorted(overlap)[:5]}")

    @property
    def development(self) -> tuple[str, ...]:
        """Return train and validation ids: everything except the held-out test."""

        return tuple(sorted(set(self.train) | set(self.validation)))

    def __len__(self) -> int:
        return len(self.train) + len(self.validation) + len(self.test)


def read_split(directory: Path | None = None) -> AccountSplit:
    """Read the account split from disk.

    Raises:
        FileNotFoundError: If the split has not been generated. Run `make data`.
    """

    target = directory if directory is not None else splits_directory()
    path = target / SPLIT_FILENAME
    if not path.is_file():
        raise FileNotFoundError(f"account split not found at {path}; run `make data` first")
    record = json.loads(path.read_text(encoding="utf-8"))
    return AccountSplit(
        seed=int(record["seed"]),
        train=tuple(record["splits"]["train"]),
        validation=tuple(record["splits"]["validation"]),
        test=tuple(record["splits"]["test"]),
    )
