"""Filesystem locations for the dataset boundary.

The raw archive is never written to. Everything this project generates lands in
`data/processed/`, `data/splits/`, or another ignored directory.
"""

import os
from pathlib import Path
from typing import Final

_RAW_ARCHIVE_NAME: Final[str] = "meridian-account-health"
_DATA_ROOT_ENV_VAR: Final[str] = "MERIDIAN_DATA_ROOT"


def repository_root() -> Path:
    """Return the project root, four parents above this module."""

    return Path(__file__).resolve().parents[4]


def data_root() -> Path:
    """Return the data directory, overridable with `MERIDIAN_DATA_ROOT` for tests."""

    override = os.environ.get(_DATA_ROOT_ENV_VAR)
    if override:
        return Path(override).resolve()
    return repository_root() / "data"


def raw_dataset_directory() -> Path:
    """Return the unchanged extracted archive. Read-only by policy."""

    return data_root() / "raw" / _RAW_ARCHIVE_NAME


def raw_tables_directory() -> Path:
    """Return the directory holding the seven source CSVs."""

    return raw_dataset_directory() / "data"


def processed_directory() -> Path:
    """Return the directory for sanitized runtime derivatives."""

    return data_root() / "processed"


def splits_directory() -> Path:
    """Return the directory for the deterministic account split."""

    return data_root() / "splits"
