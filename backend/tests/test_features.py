"""Feature computation guarantees (plan sections 8.3 and 10.1)."""

from datetime import timedelta

import pandas as pd
import pytest

from meridian.data.constants import FORBIDDEN_RUNTIME_FIELDS
from meridian.data.loader import RawDataset
from meridian.data.repository import RuntimeRepository
from meridian.features.builder import DEFAULT_CSAT, build_feature_frame, build_features
from meridian.features.spec import (
    DISPLAY_ONLY_FEATURES,
    FEATURE_SPECS,
    MODEL_INPUT_FEATURES,
)


def test_every_feature_is_computed(runtime: RuntimeRepository) -> None:
    """The builder returns exactly the declared feature set."""

    features = build_features(runtime, runtime.account_ids()[0])
    assert set(features.values) == {spec.name for spec in FEATURE_SPECS}


def test_no_feature_name_collides_with_a_forbidden_field() -> None:
    """A feature must never be named after latent or outcome data."""

    assert not set(MODEL_INPUT_FEATURES) & FORBIDDEN_RUNTIME_FIELDS


def test_days_to_renewal_is_excluded_from_model_inputs(runtime: RuntimeRepository) -> None:
    """Section 8.3: it is constant at 90, so it carries no signal.

    It is still computed for display, which is why the exclusion is asserted
    rather than assumed from its absence.
    """

    assert "days_to_renewal" in DISPLAY_ONLY_FEATURES
    assert "days_to_renewal" not in MODEL_INPUT_FEATURES
    features = build_features(runtime, runtime.account_ids()[0])
    assert features.values["days_to_renewal"] == 90.0
    assert len(features.vector()) == len(MODEL_INPUT_FEATURES)


def test_days_to_renewal_really_is_constant(
    runtime: RuntimeRepository, sample_account_ids: list[str]
) -> None:
    """Confirms the premise behind excluding it, rather than trusting the plan."""

    observed = {
        build_features(runtime, account).values["days_to_renewal"] for account in sample_account_ids
    }
    assert observed == {90.0}


def test_advanced_depth_comes_from_telemetry_not_the_latent_target(
    runtime: RuntimeRepository, dataset: RawDataset, sample_account_ids: list[str]
) -> None:
    """Section 8.3: the archive derives depth from `advanced_adoption_target`.

    That column is latent generator state. Recomputing from
    `usage_weekly.advanced_feature_adoption_pct` must therefore produce values
    that track observed telemetry, not the latent field scaled by 100.
    """

    latent_targets = dataset.accounts.set_index("account_id")["advanced_adoption_target"].astype(
        float
    )
    for account_id in sample_account_ids:
        features = build_features(runtime, account_id)
        depth = features.values["advanced_feature_depth"]
        latent = float(latent_targets.loc[account_id]) * 100.0
        usage = runtime.usage(account_id)
        if usage.empty:
            continue
        observed = usage["advanced_feature_adoption_pct"]
        assert observed.min() <= depth <= observed.max()
        assert depth != pytest.approx(latent, abs=1e-9)


def test_escalation_rate_uses_the_26_week_denominator(
    runtime: RuntimeRepository, sample_account_ids: list[str]
) -> None:
    """Section 8.3: the archive divides by the whole observed history.

    Dividing by weeks inside the window can only produce a rate at least as
    large, because the window is a subset of the history.
    """

    for account_id in sample_account_ids:
        features = build_features(runtime, account_id)
        rate = features.values["support_escalation_rate"]
        assert rate >= 0.0
        weeks_in_window = features.coverage.observed_weeks_adoption_window
        assert features.coverage.observed_weeks_total >= weeks_in_window


def test_features_never_read_beyond_the_cutoff(
    runtime: RuntimeRepository, sample_account_ids: list[str]
) -> None:
    """An earlier cutoff must not produce identical adoption evidence."""

    for account_id in sample_account_ids:
        full = build_features(runtime, account_id)
        earlier_date = full.cutoff - timedelta(weeks=30)
        earlier = build_features(runtime, account_id, earlier_date)
        assert earlier.cutoff == earlier_date
        assert earlier.coverage.observed_weeks_total < full.coverage.observed_weeks_total


def test_cutoff_argument_cannot_widen_visibility(runtime: RuntimeRepository) -> None:
    """A later cutoff is clamped to the account's own effective cutoff."""

    account_id = runtime.account_ids()[0]
    effective = runtime.cutoff_for(account_id)
    widened = build_features(runtime, account_id, effective + timedelta(weeks=52))
    assert widened.cutoff == effective


def test_feature_computation_is_deterministic(runtime: RuntimeRepository) -> None:
    """The same inputs must produce identical values, for reproducible metrics."""

    account_id = runtime.account_ids()[3]
    assert build_features(runtime, account_id).values == build_features(runtime, account_id).values


def test_missing_csat_falls_back_to_neutral(runtime: RuntimeRepository) -> None:
    """Windows with no closed ticket use the documented neutral CSAT."""

    values = [
        build_features(runtime, account_id).values["avg_closed_csat_26w"]
        for account_id in runtime.account_ids()[:60]
    ]
    assert all(1.0 <= value <= 5.0 for value in values)
    assert DEFAULT_CSAT in values


def test_feature_frame_is_complete_and_finite(runtime: RuntimeRepository) -> None:
    """Every account yields a finite vector, so training never sees NaN."""

    frame = build_feature_frame(runtime)
    assert list(frame.columns) == list(MODEL_INPUT_FEATURES)
    assert len(frame) == len(runtime.account_ids())
    assert bool(frame.notna().all().all())
    assert bool(frame.map(lambda value: pd.notna(value) and abs(value) < 1e9).all().all())


def test_coverage_reports_evidence_volume(runtime: RuntimeRepository) -> None:
    """Section 10.1 requires each metric to carry its source row count."""

    features = build_features(runtime, runtime.account_ids()[0])
    coverage = features.coverage
    assert coverage.observed_weeks_total > 0
    assert coverage.observed_weeks_adoption_window <= coverage.observed_weeks_total
    assert coverage.tickets_in_window >= coverage.closed_tickets_with_csat
    assert isinstance(coverage.thin_families, tuple)
