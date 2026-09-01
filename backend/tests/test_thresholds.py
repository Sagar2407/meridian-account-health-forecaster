"""The decision thresholds are frozen and single-sourced (plan section 22.7).

Section 22.7 requires the config to be frozen before held-out execution and
forbids tuning on held-out outcomes. A test cannot stop someone editing a
number, but it can make the edit *loud*: change any threshold without bumping
the version and this suite fails, so the change cannot reach a held-out run by
accident.
"""

import pytest

from meridian.graph import confidence, routing
from meridian.graph.thresholds import (
    FROZEN_DIGEST,
    THRESHOLD_VERSION,
    THRESHOLDS,
    DecisionThresholds,
)

#: The digest of the thresholds as frozen for version v1. Written out rather
#: than computed, so that editing a threshold *and* the expectation together is
#: a visible two-line diff rather than an invisible one.
EXPECTED_DIGEST = "5e23d7f9d9fef896"


def test_the_frozen_digest_still_matches_the_frozen_values() -> None:
    """A threshold edited without a version bump must not pass silently."""

    assert THRESHOLDS.version == THRESHOLD_VERSION
    assert THRESHOLDS.digest() == FROZEN_DIGEST
    assert THRESHOLDS.digest() == EXPECTED_DIGEST, (
        "A decision threshold changed. That is allowed, but it is a deliberate act: "
        "bump THRESHOLD_VERSION, update EXPECTED_DIGEST here, and record the "
        "development-split evidence in docs/PHASE_10_STATUS.md. Section 22.7 forbids "
        "making this change on held-out outcomes."
    )


def test_every_consumer_reads_the_frozen_source() -> None:
    """Two copies of a threshold means a change to one of them is invisible."""

    assert THRESHOLDS.calibrated_weight == confidence.CALIBRATED_WEIGHT
    assert THRESHOLDS.coverage_weight == confidence.COVERAGE_WEIGHT
    assert THRESHOLDS.agreement_weight == confidence.AGREEMENT_WEIGHT
    assert THRESHOLDS.cap_critical_source_missing == confidence.CAP_CRITICAL_SOURCE_MISSING
    assert THRESHOLDS.cap_unresolved_conflict == confidence.CAP_UNRESOLVED_CONFLICT
    assert THRESHOLDS.cap_exhausted_retrieval_gap == confidence.CAP_EXHAUSTED_RETRIEVAL_GAP
    assert THRESHOLDS.cap_repaired_verification == confidence.CAP_REPAIRED_VERIFICATION
    assert THRESHOLDS.tie_margin == confidence.TIE_MARGIN
    assert THRESHOLDS.green_minimum_confidence == routing.GREEN_MINIMUM_CONFIDENCE
    assert THRESHOLDS.amber_minimum_confidence == routing.AMBER_MINIMUM_CONFIDENCE


def test_the_digest_ignores_prose_and_notices_numbers() -> None:
    """Rewording a rationale is not a change to what the system decides."""

    reworded = DecisionThresholds(rationale="a different explanation entirely")
    assert reworded.digest() == THRESHOLDS.digest()

    moved = DecisionThresholds(green_minimum_confidence=0.9)
    assert moved.digest() != THRESHOLDS.digest()


def test_weights_that_do_not_sum_to_one_are_refused() -> None:
    """A confidence formula whose weights do not sum to one is not a formula."""

    with pytest.raises(ValueError, match="sum to"):
        DecisionThresholds(calibrated_weight=0.5, coverage_weight=0.15, agreement_weight=0.15)


def test_bands_out_of_order_are_refused() -> None:
    """Amber above green would route every confident answer to a person."""

    with pytest.raises(ValueError, match="ordered"):
        DecisionThresholds(green_minimum_confidence=0.6, amber_minimum_confidence=0.8)


def test_a_cap_outside_the_unit_interval_is_refused() -> None:
    """A cap above 1.0 caps nothing; a cap at or below 0 releases nothing."""

    with pytest.raises(ValueError, match="cap_critical_source_missing"):
        DecisionThresholds(cap_critical_source_missing=1.5)
    with pytest.raises(ValueError, match="cap_unresolved_conflict"):
        DecisionThresholds(cap_unresolved_conflict=0.0)
    with pytest.raises(ValueError, match="cap_exhausted_retrieval_gap"):
        DecisionThresholds(cap_exhausted_retrieval_gap=-0.1)


def test_the_thresholds_are_not_configurable_at_runtime() -> None:
    """Section 22.7: a threshold an operator can move is not a calibration."""

    with pytest.raises(Exception):  # noqa: B017 - frozen dataclass raises FrozenInstanceError
        THRESHOLDS.green_minimum_confidence = 0.5  # type: ignore[misc]
