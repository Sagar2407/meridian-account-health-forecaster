"""Loader guarantees: reader settings, key integrity, and permitted nulls."""

from pathlib import Path

import pandas as pd
import pytest

from meridian.data.loader import DataValidationError, RawDataset, load_raw_dataset
from meridian.data.schemas import TABLE_SPECS


def test_region_na_is_north_america_not_null(dataset: RawDataset) -> None:
    """`keep_default_na=False` must keep the 116 North America rows intact.

    This is the regression test named in plan section 8.3: pandas would
    otherwise read region code `NA` as a missing value.
    """

    accounts = dataset.accounts
    assert accounts["region"].isna().sum() == 0
    assert int((accounts["region"] == "NA").sum()) == 116
    assert set(accounts["region"].unique()) == {"NA", "EMEA", "APAC", "LATAM"}


def test_no_orphaned_foreign_keys(dataset: RawDataset) -> None:
    """Every fact row must reference a known account (section 8.6)."""

    known = set(dataset.accounts["account_id"])
    for spec in TABLE_SPECS:
        if not spec.has_account_foreign_key:
            continue
        referenced = set(dataset.table(spec.name)["account_id"])
        assert referenced <= known, f"{spec.name} references unknown accounts"


def test_no_duplicate_primary_or_grain_keys(dataset: RawDataset) -> None:
    """Primary keys and the usage fact grain must be unique (section 8.6)."""

    assert not dataset.accounts["account_id"].duplicated().any()
    assert not dataset.support_tickets["ticket_id"].duplicated().any()
    assert not dataset.csm_notes["note_id"].duplicated().any()
    assert not dataset.renewal_outcomes["account_id"].duplicated().any()
    assert not dataset.account_features["account_id"].duplicated().any()
    grain = dataset.usage_weekly.duplicated(subset=["account_id", "week_start", "product"])
    assert not grain.any()


def test_permitted_missing_values_are_explicit(dataset: RawDataset) -> None:
    """The four documented nullable fields keep their nulls (section 8.6)."""

    tickets = dataset.support_tickets
    assert int(tickets["csat"].isna().sum()) == 575
    assert int(tickets["resolution_hours"].isna().sum()) == 575
    # An unresolved ticket is exactly one missing both CSAT and resolution time.
    assert bool((tickets["csat"].isna() == tickets["resolution_hours"].isna()).all())
    assert int(dataset.accounts["usage_cliff_date"].isna().sum()) == 231
    assert int((dataset.renewal_outcomes["outcome_reason"] == "").sum()) == 135


def test_dates_are_parsed_not_left_as_text(dataset: RawDataset) -> None:
    """Every declared date column must be datetime64, never object."""

    for spec in TABLE_SPECS:
        frame = dataset.table(spec.name)
        for column in spec.date_columns:
            assert pd.api.types.is_datetime64_any_dtype(frame[column]), (
                f"{spec.name}.{column} was not parsed as a date"
            )


def test_malformed_date_is_rejected(tmp_path: Path, dataset: RawDataset) -> None:
    """A bad date must raise rather than become a silent NaT."""

    for spec in TABLE_SPECS:
        frame = dataset.table(spec.name)
        for column in spec.date_columns:
            frame[column] = frame[column].dt.strftime("%Y-%m-%d").fillna("")
        if spec.name == "accounts":
            frame.loc[0, "renewal_date"] = "not-a-date"
        frame.to_csv(tmp_path / spec.filename, index=False)

    with pytest.raises(DataValidationError, match="malformed date"):
        load_raw_dataset(tmp_path)


def test_unknown_account_reference_is_rejected(tmp_path: Path, dataset: RawDataset) -> None:
    """A fact row for a nonexistent account must raise, not be dropped."""

    for spec in TABLE_SPECS:
        frame = dataset.table(spec.name)
        for column in spec.date_columns:
            frame[column] = frame[column].dt.strftime("%Y-%m-%d").fillna("")
        if spec.name == "external_events":
            frame.loc[0, "account_id"] = "ACC-999999"
        frame.to_csv(tmp_path / spec.filename, index=False)

    with pytest.raises(DataValidationError, match="unknown account_id"):
        load_raw_dataset(tmp_path)


def test_missing_source_file_is_reported(tmp_path: Path) -> None:
    """An absent CSV names the file it could not find."""

    with pytest.raises(DataValidationError, match="missing source file"):
        load_raw_dataset(tmp_path)


def test_table_accessor_rejects_unknown_name(dataset: RawDataset) -> None:
    """`RawDataset.table` must not silently return a non-frame attribute."""

    with pytest.raises(KeyError):
        dataset.table("no_such_table")
