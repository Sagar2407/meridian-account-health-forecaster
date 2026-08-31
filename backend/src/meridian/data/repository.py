"""The sanitized runtime boundary (plan sections 8.2 and 8.4).

Two guarantees hold for everything returned from this module:

1. **No latent fields.** Account profiles are built from an allowlist, so a
   column added to the archive later is excluded by default rather than leaked.
2. **No future records.** Every fact query is filtered to
   `effective_cutoff(account) = min(forecast_as_of_date, DATASET_AS_OF_DATE)`.
   There is no parameter to disable this.

Labels, outcomes, health indices, and driver contributions are deliberately
absent. They live in `meridian_eval`, a package runtime code must not import.
"""

from datetime import date
from functools import cached_property

import pandas as pd
from pydantic import BaseModel, ConfigDict

from meridian.data.constants import FORBIDDEN_RUNTIME_FIELDS, RUNTIME_PROFILE_FIELDS
from meridian.data.cutoff import effective_cutoff, filter_to_cutoff
from meridian.data.loader import RawDataset, load_raw_dataset


class AccountProfile(BaseModel):
    """Immutable, sanitized account identity and commercial terms."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: str
    account_name: str
    segment: str
    industry: str
    region: str
    country: str
    employees: int
    licensed_seats: int
    acv_usd: float
    contract_term_months: int
    contract_start_date: date
    renewal_date: date
    forecast_as_of_date: date
    products_owned: tuple[str, ...]
    num_products: int
    primary_product: str
    csm_name: str
    exec_sponsor_name: str
    sponsor_status: str
    onboarding_completed: bool

    @property
    def effective_cutoff(self) -> date:
        """Return the latest date whose records may inform this account."""

        return effective_cutoff(self.forecast_as_of_date)


class UnknownAccountError(KeyError):
    """Raised when an account id is not present in the dataset."""


class RuntimeRepository:
    """Point-in-time-safe read access to the dataset for application code."""

    def __init__(self, dataset: RawDataset | None = None) -> None:
        self._dataset = dataset if dataset is not None else load_raw_dataset()

    @cached_property
    def _accounts(self) -> pd.DataFrame:
        """Return accounts reduced to the runtime allowlist."""

        return self._dataset.accounts.loc[:, list(RUNTIME_PROFILE_FIELDS)].copy()

    def account_ids(self) -> tuple[str, ...]:
        """Return every account id, sorted."""

        return tuple(sorted(self._accounts["account_id"]))

    def profile(self, account_id: str) -> AccountProfile:
        """Return one sanitized account profile.

        Raises:
            UnknownAccountError: If `account_id` is not in the dataset.
        """

        rows = self._accounts.loc[self._accounts["account_id"] == account_id]
        if rows.empty:
            raise UnknownAccountError(account_id)
        record = rows.iloc[0].to_dict()
        record["products_owned"] = tuple(
            part for part in str(record["products_owned"]).split(";") if part
        )
        for field in ("contract_start_date", "renewal_date", "forecast_as_of_date"):
            record[field] = pd.Timestamp(record[field]).date()
        return AccountProfile.model_validate(record)

    def cutoff_for(self, account_id: str) -> date:
        """Return the effective cutoff for one account."""

        return self.profile(account_id).effective_cutoff

    def _account_facts(self, table: str, account_id: str, date_column: str) -> pd.DataFrame:
        """Return one account's rows from a fact table, filtered to its cutoff."""

        cutoff = self.cutoff_for(account_id)
        frame = getattr(self._dataset, table)
        rows = frame.loc[frame["account_id"] == account_id]
        return filter_to_cutoff(rows, date_column, cutoff).reset_index(drop=True)

    def usage(self, account_id: str) -> pd.DataFrame:
        """Return weekly telemetry observed on or before the account's cutoff."""

        return self._account_facts("usage_weekly", account_id, "week_start")

    def tickets(self, account_id: str) -> pd.DataFrame:
        """Return support tickets opened on or before the account's cutoff."""

        return self._account_facts("support_tickets", account_id, "created_date")

    def notes(self, account_id: str) -> pd.DataFrame:
        """Return CSM notes written on or before the account's cutoff."""

        return self._account_facts("csm_notes", account_id, "note_date")

    def events(self, account_id: str) -> pd.DataFrame:
        """Return external events dated on or before the account's cutoff.

        This is the query that drops the archive's post-horizon events; section
        8.3 requires they never reach runtime or a rebuilt index.
        """

        return self._account_facts("external_events", account_id, "event_date")

    def supplied_features(self, account_id: str) -> pd.DataFrame:
        """Return the archive's precomputed observable features for one account.

        These are provided for comparison only. Phase 2 recomputes features from
        raw records at an arbitrary cutoff and does not depend on this table.
        """

        frame = self._dataset.account_features
        return frame.loc[frame["account_id"] == account_id].reset_index(drop=True).copy()


def assert_no_forbidden_fields(frame: pd.DataFrame, context: str) -> None:
    """Raise if `frame` carries any latent or outcome-bearing column.

    Args:
        frame: Any frame about to cross into runtime, retrieval, or a prompt.
        context: Human-readable description used in the error message.

    Raises:
        ValueError: If a forbidden column is present.
    """

    leaked = sorted(FORBIDDEN_RUNTIME_FIELDS.intersection(frame.columns))
    if leaked:
        raise ValueError(f"{context} exposes forbidden field(s): {leaked}")
