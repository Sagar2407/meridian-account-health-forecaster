"""Dataset provenance (plan section 8.1).

Records the dataset version, the SHA-256 of every source file, row counts, the
project seed, and the as-of date, so any result can be tied back to the exact
bytes it was computed from.
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from meridian.data.constants import DATASET_AS_OF_DATE, DATASET_VERSION, PROJECT_SEED
from meridian.data.paths import processed_directory, raw_tables_directory
from meridian.data.schemas import TABLE_SPECS

MANIFEST_FILENAME = "dataset_manifest.json"
_CHUNK_BYTES = 1 << 20


def file_digest(path: Path) -> str:
    """Return the SHA-256 hex digest of one file, read in chunks."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class DatasetManifest:
    """Provenance for one materialization of the dataset."""

    dataset_version: str
    as_of_date: str
    project_seed: int
    files: dict[str, str]
    row_counts: dict[str, int]

    def to_json(self) -> str:
        """Return the manifest as stable, sorted JSON."""

        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"


def build_manifest(
    row_counts: dict[str, int],
    directory: Path | None = None,
    as_of_date: date = DATASET_AS_OF_DATE,
) -> DatasetManifest:
    """Hash every source table and record it alongside observed row counts."""

    source = directory if directory is not None else raw_tables_directory()
    files = {spec.filename: file_digest(source / spec.filename) for spec in TABLE_SPECS}
    return DatasetManifest(
        dataset_version=DATASET_VERSION,
        as_of_date=as_of_date.isoformat(),
        project_seed=PROJECT_SEED,
        files=files,
        row_counts=row_counts,
    )


def write_manifest(manifest: DatasetManifest, directory: Path | None = None) -> Path:
    """Write the manifest to the processed directory and return its path."""

    target = directory if directory is not None else processed_directory()
    target.mkdir(parents=True, exist_ok=True)
    path = target / MANIFEST_FILENAME
    path.write_text(manifest.to_json(), encoding="utf-8")
    return path


def read_manifest(directory: Path | None = None) -> DatasetManifest:
    """Read a previously written manifest."""

    target = directory if directory is not None else processed_directory()
    record = json.loads((target / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    return DatasetManifest(**record)
