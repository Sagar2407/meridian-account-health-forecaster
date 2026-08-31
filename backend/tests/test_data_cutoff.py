"""Point-in-time enforcement (plan section 8.2)."""

from datetime import date

import pandas as pd
import pytest

from meridian.data.constants import DATASET_AS_OF_DATE
from meridian.data.cutoff import effective_cutoff, filter_to_cutoff
from meridian.data.loader import RawDataset
from meridian.data.sanitize import RUNTIME_FACT_TABLES, build_runtime_tables


def test_effective_cutoff_takes_the_earlier_bound() -> None:
    """The cutoff is the minimum of the account date and the global horizon."""

    assert effective_cutoff(date(2026, 1, 15)) == date(2026, 1, 15)
    assert effective_cutoff(date(2026, 12, 31)) == DATASET_AS_OF_DATE
    assert effective_cutoff(DATASET_AS_OF_DATE) == DATASET_AS_OF_DATE


def test_filter_to_cutoff_is_inclusive() -> None:
    """A record dated exactly on the cutoff is retained."""

    frame = pd.DataFrame({"d": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"])})
    kept = filter_to_cutoff(frame, "d", date(2026, 1, 2))
    assert list(kept["d"].dt.strftime("%Y-%m-%d")) == ["2026-01-01", "2026-01-02"]


def test_filter_to_cutoff_rejects_missing_column() -> None:
    """Filtering on an absent column must raise, not pass rows through."""

    with pytest.raises(KeyError):
        filter_to_cutoff(pd.DataFrame({"a": [1]}), "missing", date(2026, 1, 1))


def test_no_runtime_record_postdates_its_account_cutoff(dataset: RawDataset) -> None:
    """Zero accepted runtime records after the effective cutoff (section 8.6)."""

    horizon = pd.Timestamp(DATASET_AS_OF_DATE)
    forecast = dataset.accounts.set_index("account_id")["forecast_as_of_date"]
    cutoffs = forecast.where(forecast <= horizon, horizon)
    for name, frame in build_runtime_tables(dataset).items():
        if name == "accounts":
            continue
        spec = next(item for item in RUNTIME_FACT_TABLES if item.name == name)
        limits = frame["account_id"].map(cutoffs)
        assert not bool((frame[spec.date_column] > limits).any()), f"{name} leaks future rows"


def test_sanitization_actually_removes_rows(dataset: RawDataset) -> None:
    """The archive really does contain post-cutoff rows, so the filter matters.

    Without this the cutoff tests could pass against data that never needed
    filtering in the first place.
    """

    tables = build_runtime_tables(dataset)
    for spec in RUNTIME_FACT_TABLES:
        raw_rows = len(dataset.table(spec.name))
        assert len(tables[spec.name]) < raw_rows, f"{spec.name} had nothing to filter"


def test_external_events_past_the_horizon_are_dropped(dataset: RawDataset) -> None:
    """Section 8.3: the archive's events run to 2026-07-02 and must not survive."""

    raw = dataset.external_events
    assert bool((raw["event_date"] > pd.Timestamp(DATASET_AS_OF_DATE)).any())
    runtime = build_runtime_tables(dataset)["external_events"]
    assert not bool((runtime["event_date"] > pd.Timestamp(DATASET_AS_OF_DATE)).any())
