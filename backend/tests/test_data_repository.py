"""The sanitized runtime boundary (plan section 8.4)."""

import pandas as pd
import pytest
from pydantic import ValidationError

from meridian.data.constants import FORBIDDEN_RUNTIME_FIELDS, RUNTIME_PROFILE_FIELDS
from meridian.data.loader import RawDataset
from meridian.data.repository import (
    AccountProfile,
    RuntimeRepository,
    UnknownAccountError,
    assert_no_forbidden_fields,
)
from meridian.data.sanitize import build_runtime_tables


def test_profile_exposes_no_forbidden_field(runtime: RuntimeRepository) -> None:
    """No latent or outcome field may appear on a runtime profile."""

    profile = runtime.profile(runtime.account_ids()[0])
    exposed = set(profile.model_dump())
    assert exposed == set(RUNTIME_PROFILE_FIELDS)
    assert not exposed & FORBIDDEN_RUNTIME_FIELDS


def test_runtime_tables_expose_no_forbidden_field(dataset: RawDataset) -> None:
    """Zero forbidden fields in any sanitized table (section 8.6)."""

    for name, frame in build_runtime_tables(dataset).items():
        assert_no_forbidden_fields(frame, f"runtime table {name}")


def test_assert_no_forbidden_fields_detects_a_leak() -> None:
    """The guard must actually fire; a silent no-op would be worse than nothing."""

    leaky = pd.DataFrame({"account_id": ["ACC-1"], "health_band": ["at_risk"]})
    with pytest.raises(ValueError, match="health_band"):
        assert_no_forbidden_fields(leaky, "test frame")


def test_profile_is_immutable(runtime: RuntimeRepository) -> None:
    """Profiles are frozen so callers cannot rewrite a cutoff."""

    profile = runtime.profile(runtime.account_ids()[0])
    with pytest.raises(ValidationError):
        profile.forecast_as_of_date = profile.renewal_date  # type: ignore[misc]


def test_profile_parses_products_owned(runtime: RuntimeRepository) -> None:
    """The semicolon-separated product list becomes a tuple with no empties."""

    for account_id in runtime.account_ids()[:25]:
        profile = runtime.profile(account_id)
        assert isinstance(profile.products_owned, tuple)
        assert all(part for part in profile.products_owned)
        assert len(profile.products_owned) == profile.num_products


def test_unknown_account_raises(runtime: RuntimeRepository) -> None:
    """An unknown id must raise rather than return an empty profile."""

    with pytest.raises(UnknownAccountError):
        runtime.profile("ACC-000000")


def test_every_fact_query_respects_the_cutoff(
    runtime: RuntimeRepository, sample_account_ids: list[str]
) -> None:
    """Each per-account accessor filters to that account's effective cutoff."""

    for account_id in sample_account_ids:
        cutoff = pd.Timestamp(runtime.cutoff_for(account_id))
        for frame, column in (
            (runtime.usage(account_id), "week_start"),
            (runtime.tickets(account_id), "created_date"),
            (runtime.notes(account_id), "note_date"),
            (runtime.events(account_id), "event_date"),
        ):
            assert set(frame["account_id"]) <= {account_id}
            assert not bool((frame[column] > cutoff).any())


def test_cutoff_never_exceeds_the_global_horizon(runtime: RuntimeRepository) -> None:
    """Section 8.2 caps every account cutoff at the dataset as-of date."""

    from meridian.data.constants import DATASET_AS_OF_DATE

    for account_id in runtime.account_ids():
        assert runtime.cutoff_for(account_id) <= DATASET_AS_OF_DATE


def test_profile_effective_cutoff_matches_repository(runtime: RuntimeRepository) -> None:
    """The profile property and the repository helper must not diverge."""

    for account_id in runtime.account_ids()[:25]:
        profile: AccountProfile = runtime.profile(account_id)
        assert profile.effective_cutoff == runtime.cutoff_for(account_id)
