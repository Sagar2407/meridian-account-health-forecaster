"""The browsable generator source must match the committed archive.

`dataset/` exists so a reader can see how the synthetic data was produced
without downloading and unzipping anything. That convenience creates a second
copy of files that already live inside `meridian-account-health.zip`, and two
copies drift. These tests make drift a build failure instead of a surprise.

They compare against the zip rather than the extracted `data/raw/` tree, so
they run on a fresh clone where nothing has been extracted yet.

These are checks on the source tree, not on the running system. `.dockerignore`
deliberately keeps the archive and `dataset/` out of the runtime image -- the
application never reads either -- so inside the container there is nothing to
compare and the module skips. It runs on every developer checkout and in CI,
which is where a drifted copy would actually be introduced.
"""

import zipfile
from pathlib import Path

import pytest

from meridian.data.paths import repository_root

ARCHIVE_NAME = "meridian-account-health.zip"
ARCHIVE_ROOT = "meridian-account-health/"
GENERATOR_MODULES = (
    "build_dataset.py",
    "build_guardrail_eval.py",
    "build_knowledge_base.py",
    "config.py",
    "generators.py",
    "text_banks.py",
)
KNOWLEDGE_BASE_ARTICLES = 32


def dataset_directory() -> Path:
    """Return the committed, browsable copy of the generator source."""

    return repository_root() / "dataset"


def archive_path() -> Path:
    """Return the committed source archive."""

    return repository_root() / ARCHIVE_NAME


pytestmark = pytest.mark.skipif(
    not (repository_root() / ARCHIVE_NAME).is_file(),
    reason=(
        f"{ARCHIVE_NAME} is absent, so this is not a source checkout. "
        "The runtime image excludes it by design; these checks run on a "
        "developer checkout and in CI."
    ),
)


@pytest.fixture(scope="module")
def archive() -> zipfile.ZipFile:
    """Return the committed archive; the module skip guarantees it is present."""

    return zipfile.ZipFile(archive_path())


def test_the_archive_is_committed_and_small_enough_to_stay_committed() -> None:
    """The archive is the reference for reproducibility, so it ships with the repo."""

    size_mb = archive_path().stat().st_size / 1_000_000
    assert size_mb < 25, f"archive grew to {size_mb:.1f} MB; reconsider committing it"


def test_every_browsable_file_matches_the_archive_byte_for_byte(
    archive: zipfile.ZipFile,
) -> None:
    """A file edited in one copy but not the other must fail the build."""

    members = set(archive.namelist())
    mismatched: list[str] = []
    compared = 0
    for path in sorted(dataset_directory().rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(dataset_directory()).as_posix()
        member = f"{ARCHIVE_ROOT}{relative}"
        if member not in members:
            mismatched.append(f"{relative}: not present in the archive")
            continue
        if archive.read(member) != path.read_bytes():
            mismatched.append(f"{relative}: differs from the archive")
        compared += 1
    assert compared > 0, "dataset/ is empty; the browsable generator source is missing"
    assert not mismatched, f"dataset/ has drifted from {ARCHIVE_NAME}: {mismatched[:5]}"


def test_the_generator_modules_are_all_browsable() -> None:
    """The point of `dataset/` is that generation is readable without unzipping."""

    present = {path.name for path in dataset_directory().glob("*.py")}
    assert set(GENERATOR_MODULES) <= present


def test_the_knowledge_base_is_browsable() -> None:
    """The 32 KB articles are the qualitative half of the corpus, so they ship too."""

    articles = sorted((dataset_directory() / "knowledge_base").glob("KB-*.md"))
    assert len(articles) == KNOWLEDGE_BASE_ARTICLES


def test_no_bulk_data_was_copied_into_the_browsable_tree() -> None:
    """`dataset/` is source and documentation; the tables stay in the archive."""

    heavy = [
        path.relative_to(dataset_directory()).as_posix()
        for path in dataset_directory().rglob("*")
        if path.is_file() and path.suffix in {".csv", ".jsonl", ".json"}
    ]
    assert not heavy, f"bulk data does not belong in dataset/: {heavy}"
