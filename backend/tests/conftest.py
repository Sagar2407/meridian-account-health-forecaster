"""Shared fixtures and dataset availability handling.

The raw archive is git-ignored and excluded from Docker images, so it is absent
in some environments (the backend container in particular). Tests that need it
are skipped there rather than failing.

To stop that from silently hollowing out the data gate, `make validate-data`
sets `MERIDIAN_REQUIRE_DATASET=1`, which turns the skip into a hard error.
"""

import os
from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest

from meridian.data.loader import RawDataset, load_raw_dataset
from meridian.data.paths import raw_tables_directory
from meridian.data.repository import RuntimeRepository

if TYPE_CHECKING:
    from meridian.model.artifacts import ModelArtifact

REQUIRE_DATASET_ENV_VAR = "MERIDIAN_REQUIRE_DATASET"
_MISSING_ARCHIVE_REASON = (
    "raw archive not present; extract meridian-account-health.zip into data/raw/"
)


def archive_is_present() -> bool:
    """Return whether the extracted source archive is available."""

    return (raw_tables_directory() / "accounts.csv").is_file()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip dataset-dependent tests when the archive is absent.

    Raises:
        pytest.UsageError: If the archive is missing while
            `MERIDIAN_REQUIRE_DATASET=1`, so the data gate cannot pass vacuously.
    """

    if archive_is_present():
        return
    if os.environ.get(REQUIRE_DATASET_ENV_VAR) == "1":
        raise pytest.UsageError(
            f"{REQUIRE_DATASET_ENV_VAR}=1 but the raw archive is missing. {_MISSING_ARCHIVE_REASON}"
        )
    skip = pytest.mark.skip(reason=_MISSING_ARCHIVE_REASON)
    for item in items:
        needs_fixture = "dataset" in getattr(item, "fixturenames", ())
        if needs_fixture or item.get_closest_marker("requires_dataset"):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def dataset() -> RawDataset:
    """Return the validated raw dataset, loaded once."""

    return load_raw_dataset()


@pytest.fixture(scope="session")
def runtime(dataset: RawDataset) -> RuntimeRepository:
    """Return a runtime repository over the session dataset."""

    return RuntimeRepository(dataset)


@pytest.fixture
def sample_account_ids(dataset: RawDataset) -> Iterator[list[str]]:
    """Yield a deterministic spread of account ids for per-account assertions."""

    ids = sorted(dataset.accounts["account_id"])
    yield ids[::20]


@pytest.fixture(scope="session")
def forecaster_artifact(
    dataset: RawDataset, tmp_path_factory: pytest.TempPathFactory
) -> "ModelArtifact":
    """Fit, persist, and load a small calibrated forecaster.

    Shared by the model suite and the graph suite. It is built here rather than
    read from `models/` because that directory is excluded from the runtime
    image, so a fixture that loaded it would silently skip wherever the tests
    matter most.
    """

    from meridian.features.builder import build_feature_frame
    from meridian.features.spec import MODEL_INPUT_FEATURES
    from meridian.model.artifacts import ModelArtifact, ModelMetadata, load_artifact, save_artifact
    from meridian_eval.modeling import fit_calibrated_model
    from meridian_eval.repository import EvaluationRepository

    repository = RuntimeRepository(dataset)
    accounts = repository.account_ids()[:150]
    features = build_feature_frame(repository, accounts)
    labels = EvaluationRepository(dataset).labels().loc[list(accounts)]

    estimator = fit_calibrated_model("logistic_regression", features, labels)
    metadata = ModelMetadata(
        model_name="logistic_regression",
        calibration_method="isotonic",
        classes=tuple(str(name) for name in estimator.classes_),
        feature_names=MODEL_INPUT_FEATURES,
        project_seed=20260721,
        dataset_version="test",
        split_digest="0" * 64,
        package_versions={},
    )
    directory = tmp_path_factory.mktemp("model")
    save_artifact(ModelArtifact(estimator=estimator, metadata=metadata), directory)
    return load_artifact(directory)
