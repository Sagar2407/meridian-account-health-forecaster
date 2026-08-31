"""Serving-side guarantees for the forecaster (plan sections 10.4 and 10.5).

These build a small model in a fixture rather than depending on `make train`,
so the suite is self-contained.
"""

from pathlib import Path

import pytest

from meridian.data.constants import FORBIDDEN_RUNTIME_FIELDS
from meridian.data.repository import RuntimeRepository
from meridian.features.spec import MODEL_INPUT_FEATURES
from meridian.model.artifacts import (
    ArtifactBoundaryError,
    ModelArtifact,
    assert_servable,
    load_artifact,
)
from meridian.model.predict import predict_account
from meridian_eval.modeling import HealthIndexRuleBaseline

pytestmark = pytest.mark.requires_dataset


@pytest.fixture(scope="module")
def artifact(forecaster_artifact: ModelArtifact) -> ModelArtifact:
    """Return the shared calibrated model built in `conftest.py`.

    It moved there when the graph suite needed the same artifact; building two
    would double the slowest fixture in the suite to no benefit.
    """

    return forecaster_artifact


def test_artifact_round_trips(artifact: ModelArtifact) -> None:
    """Loading a saved artifact preserves the serving contract."""

    assert artifact.metadata.feature_names == MODEL_INPUT_FEATURES
    assert set(artifact.metadata.classes) <= {"Churned", "Contracted", "Renewed", "Expanded"}


def test_evaluation_only_estimators_cannot_be_served() -> None:
    """A model defined in `meridian_eval` must not be persisted for serving.

    Unpickling it would force `meridian` to import the evaluation package and
    break the section 8.4 boundary at load time rather than at review time.
    """

    with pytest.raises(ArtifactBoundaryError, match="meridian_eval"):
        assert_servable(HealthIndexRuleBaseline())


def test_servable_estimator_passes_the_guard(artifact: ModelArtifact) -> None:
    """The guard must not reject legitimate models, or it is useless."""

    assert_servable(artifact.estimator)


def test_missing_artifact_names_the_remedy(tmp_path: Path) -> None:
    """A helpful error beats a stack trace when no model has been trained."""

    with pytest.raises(FileNotFoundError, match="make train"):
        load_artifact(tmp_path)


def test_prediction_is_a_valid_distribution(
    artifact: ModelArtifact, runtime: RuntimeRepository
) -> None:
    """Probabilities must be a proper distribution over the four outcomes."""

    forecast = predict_account(artifact, runtime, runtime.account_ids()[0])
    assert set(forecast.probabilities) == set(artifact.metadata.classes)
    assert all(0.0 <= value <= 1.0 for value in forecast.probabilities.values())
    assert sum(forecast.probabilities.values()) == pytest.approx(1.0, abs=1e-6)
    assert forecast.confidence == pytest.approx(max(forecast.probabilities.values()))
    assert forecast.predicted_outcome == max(
        forecast.probabilities, key=lambda name: forecast.probabilities[name]
    )


def test_prediction_is_deterministic(artifact: ModelArtifact, runtime: RuntimeRepository) -> None:
    """Plan section 10 requires metrics to reproduce exactly from the same input."""

    account_id = runtime.account_ids()[7]
    first = predict_account(artifact, runtime, account_id)
    second = predict_account(artifact, runtime, account_id)
    assert first.probabilities == second.probabilities
    assert first.predicted_outcome == second.predicted_outcome


def test_forecast_exposes_no_forbidden_field(
    artifact: ModelArtifact, runtime: RuntimeRepository, sample_account_ids: list[str]
) -> None:
    """Nothing latent may surface through a contribution or coverage key."""

    for account_id in sample_account_ids[:5]:
        forecast = predict_account(artifact, runtime, account_id)
        names = {item.feature for item in forecast.contributions}
        assert not names & FORBIDDEN_RUNTIME_FIELDS
        assert not set(forecast.coverage) & FORBIDDEN_RUNTIME_FIELDS


def test_contributions_cover_every_model_input(
    artifact: ModelArtifact, runtime: RuntimeRepository
) -> None:
    """Every input feature gets a contribution, so nothing is silently hidden."""

    forecast = predict_account(artifact, runtime, runtime.account_ids()[2])
    assert tuple(item.feature for item in forecast.contributions) == MODEL_INPUT_FEATURES
    assert len(forecast.top_contributions(3)) == 3


def test_prediction_respects_an_earlier_cutoff(
    artifact: ModelArtifact, runtime: RuntimeRepository
) -> None:
    """Backtesting at an earlier cutoff must change the evidence used."""

    from datetime import timedelta

    account_id = runtime.account_ids()[5]
    full = predict_account(artifact, runtime, account_id)
    earlier = predict_account(artifact, runtime, account_id, full.cutoff - timedelta(weeks=40))
    assert earlier.cutoff < full.cutoff
    assert earlier.coverage["observed_weeks_total"] < full.coverage["observed_weeks_total"]
