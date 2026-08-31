"""Materialize sanitized, cutoff-filtered runtime tables (plan sections 8.2-8.4).

`RuntimeRepository` applies the same rules one account at a time. This module
applies them to whole tables at once so the results can be written to
`data/processed/` and reused by retrieval and training without re-deriving the
cutoff on every read.
"""

from dataclasses import dataclass

import pandas as pd

from meridian.data.constants import DATASET_AS_OF_DATE, RUNTIME_PROFILE_FIELDS
from meridian.data.loader import RawDataset

_CUTOFF_COLUMN = "_effective_cutoff"


@dataclass(frozen=True)
class FactTableSpec:
    """One fact table and the date column its cutoff applies to."""

    name: str
    date_column: str


RUNTIME_FACT_TABLES: tuple[FactTableSpec, ...] = (
    FactTableSpec("usage_weekly", "week_start"),
    FactTableSpec("support_tickets", "created_date"),
    FactTableSpec("csm_notes", "note_date"),
    FactTableSpec("external_events", "event_date"),
)


def account_cutoffs(dataset: RawDataset) -> pd.DataFrame:
    """Return `account_id` with its effective cutoff.

    The cutoff is `min(forecast_as_of_date, DATASET_AS_OF_DATE)`, computed
    vectorized so it matches :func:`meridian.data.cutoff.effective_cutoff`
    row for row.
    """

    frame = dataset.accounts.loc[:, ["account_id", "forecast_as_of_date"]].copy()
    horizon = pd.Timestamp(DATASET_AS_OF_DATE)
    forecast = frame["forecast_as_of_date"]
    frame[_CUTOFF_COLUMN] = forecast.where(forecast <= horizon, horizon)
    return frame.loc[:, ["account_id", _CUTOFF_COLUMN]]


def runtime_accounts(dataset: RawDataset) -> pd.DataFrame:
    """Return the account dimension reduced to the runtime allowlist."""

    return dataset.accounts.loc[:, list(RUNTIME_PROFILE_FIELDS)].copy()


def runtime_fact_table(dataset: RawDataset, spec: FactTableSpec) -> pd.DataFrame:
    """Return one fact table with every post-cutoff row removed."""

    frame: pd.DataFrame = getattr(dataset, spec.name)
    merged = frame.merge(account_cutoffs(dataset), on="account_id", how="left", validate="m:1")
    if bool(merged[_CUTOFF_COLUMN].isna().any()):
        raise ValueError(f"{spec.name}: rows without a resolvable account cutoff")
    kept = merged.loc[merged[spec.date_column] <= merged[_CUTOFF_COLUMN]]
    return kept.drop(columns=[_CUTOFF_COLUMN]).reset_index(drop=True)


def build_runtime_tables(dataset: RawDataset) -> dict[str, pd.DataFrame]:
    """Return every sanitized runtime table, keyed by name."""

    tables: dict[str, pd.DataFrame] = {"accounts": runtime_accounts(dataset)}
    for spec in RUNTIME_FACT_TABLES:
        tables[spec.name] = runtime_fact_table(dataset, spec)
    return tables
