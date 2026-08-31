"""Reproducibility of the supplied dataset (plan section 8.6).

Section 8.6 requires proving "exact reproducibility of generated row counts and
non-image artifacts". These tests re-run the supplied generator at the project
seed and assert it reproduces the shipped archive byte for byte.

It does -- but only under `numpy < 2.5`. numpy 2.5 changes one text selection,
altering exactly one note body (`NOTE-204709`) out of 6,420. `pyproject.toml`
therefore constrains numpy, and `test_numpy_is_constrained_for_reproducibility`
guards that constraint so it cannot be widened without this failing.

Marked `slow`; one generator run takes about six seconds.
"""

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pandas as pd
import pytest

from meridian.data.manifest import file_digest
from meridian.data.paths import raw_dataset_directory, repository_root
from meridian.data.schemas import TABLE_SPECS

pytestmark = [pytest.mark.slow, pytest.mark.requires_dataset]

EXPECTED_ROW_COUNTS = {
    "accounts.csv": 260,
    "usage_weekly.csv": 67223,
    "support_tickets.csv": 6408,
    "csm_notes.csv": 6420,
    "external_events.csv": 595,
    "account_features.csv": 260,
    "renewal_outcomes.csv": 260,
}


def _regenerate(destination: Path) -> Path:
    """Run the supplied generator into `destination` and return its data directory."""

    archive = raw_dataset_directory()
    for module in archive.glob("*.py"):
        shutil.copy2(module, destination / module.name)
    result = subprocess.run(
        [sys.executable, "build_dataset.py"],
        cwd=destination,
        capture_output=True,
        text=True,
        timeout=600,
        env={"MPLCONFIGDIR": str(destination / ".mpl"), "PATH": "/usr/bin:/bin"},
    )
    if result.returncode != 0:
        pytest.fail(f"generator failed:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
    return destination / "data"


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Regenerate the dataset once for the whole module."""

    return _regenerate(tmp_path_factory.mktemp("regen"))


def test_generator_is_deterministic(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Two runs at the same seed must be byte-identical."""

    first = _regenerate(tmp_path_factory.mktemp("determinism_a"))
    second = _regenerate(tmp_path_factory.mktemp("determinism_b"))
    for spec in TABLE_SPECS:
        assert file_digest(first / spec.filename) == file_digest(second / spec.filename), (
            f"{spec.filename} is not reproducible across runs"
        )


def test_regenerated_row_counts_match_the_archive(regenerated: Path) -> None:
    """Every table must regenerate at exactly the documented row count."""

    for filename, expected in EXPECTED_ROW_COUNTS.items():
        frame = pd.read_csv(regenerated / filename, keep_default_na=False, dtype=str)
        assert len(frame) == expected, f"{filename} regenerated {len(frame)} rows"


def test_every_table_reproduces_the_shipped_archive(regenerated: Path) -> None:
    """All seven CSVs must regenerate byte for byte.

    If this fails on `csm_notes.csv` alone, check the resolved numpy version
    first: 2.5 changes one note body. See the module docstring.
    """

    shipped = raw_dataset_directory() / "data"
    mismatched = [
        spec.filename
        for spec in TABLE_SPECS
        if file_digest(regenerated / spec.filename) != file_digest(shipped / spec.filename)
    ]
    assert not mismatched, f"tables no longer reproduce the archive: {mismatched}"


def test_numpy_is_constrained_for_reproducibility() -> None:
    """The numpy ceiling is load-bearing, not incidental.

    Widening it past 2.5 silently breaks byte-exact reproduction of
    `csm_notes.csv`, so the constraint is asserted rather than trusted.
    """

    manifest = tomllib.loads((repository_root() / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = manifest["project"]["dependencies"]
    numpy_requirement = next(item for item in requirements if item.startswith("numpy"))
    assert "<2.5" in numpy_requirement, (
        f"numpy constraint {numpy_requirement!r} no longer pins below 2.5"
    )
