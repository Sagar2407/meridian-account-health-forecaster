"""Dataset provenance (plan section 8.1)."""

import json
from pathlib import Path

import pytest

from meridian.data.constants import DATASET_AS_OF_DATE, DATASET_VERSION, PROJECT_SEED
from meridian.data.loader import RawDataset
from meridian.data.manifest import (
    build_manifest,
    file_digest,
    read_manifest,
    write_manifest,
)
from meridian.data.paths import data_root, raw_tables_directory, repository_root
from meridian.data.schemas import TABLE_SPECS


def test_file_digest_is_stable_and_content_sensitive(tmp_path: Path) -> None:
    """Equal bytes hash equally; a one-byte change does not."""

    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("meridian")
    second.write_text("meridian")
    assert file_digest(first) == file_digest(second)
    second.write_text("meridiam")
    assert file_digest(first) != file_digest(second)


def test_manifest_records_every_source_table(dataset: RawDataset) -> None:
    """One digest per source CSV, plus version, seed, and as-of date."""

    counts = {spec.name: len(dataset.table(spec.name)) for spec in TABLE_SPECS}
    manifest = build_manifest(counts)
    assert set(manifest.files) == {spec.filename for spec in TABLE_SPECS}
    assert all(len(digest) == 64 for digest in manifest.files.values())
    assert manifest.dataset_version == DATASET_VERSION
    assert manifest.project_seed == PROJECT_SEED
    assert manifest.as_of_date == DATASET_AS_OF_DATE.isoformat()
    assert manifest.row_counts == counts


@pytest.mark.requires_dataset
def test_manifest_round_trips_through_disk(tmp_path: Path) -> None:
    """Writing then reading a manifest preserves it exactly."""

    manifest = build_manifest({"accounts": 260})
    write_manifest(manifest, tmp_path)
    assert read_manifest(tmp_path) == manifest


@pytest.mark.requires_dataset
def test_manifest_json_is_stable_and_sorted(tmp_path: Path) -> None:
    """Sorted keys keep the artifact diffable across runs."""

    manifest = build_manifest({"accounts": 260})
    payload = manifest.to_json()
    assert payload.endswith("\n")
    parsed = json.loads(payload)
    assert list(parsed) == sorted(parsed)
    assert manifest.to_json() == payload


@pytest.mark.requires_dataset
def test_constants_agree_with_the_supplied_generator() -> None:
    """`DATASET_AS_OF_DATE` and `PROJECT_SEED` must match the archive's config.py.

    The generator is the source of truth. If it is ever regenerated at a
    different seed or horizon, this fails instead of silently diverging.
    """

    config = (raw_tables_directory().parent / "config.py").read_text(encoding="utf-8")
    assert f"RANDOM_SEED = {PROJECT_SEED}" in config
    expected = (
        f"AS_OF_DATE = date({DATASET_AS_OF_DATE.year}, "
        f"{DATASET_AS_OF_DATE.month}, {DATASET_AS_OF_DATE.day})"
    )
    assert expected in config


def test_data_root_honours_the_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tests and alternate checkouts can relocate the dataset."""

    monkeypatch.setenv("MERIDIAN_DATA_ROOT", str(tmp_path))
    assert data_root() == tmp_path.resolve()
    monkeypatch.delenv("MERIDIAN_DATA_ROOT")
    assert data_root() == repository_root() / "data"
