"""Point-in-time cutoff arithmetic (plan section 8.2).

The packaged corpus contains records that postdate some accounts' forecast dates,
so cutoff filtering is mandatory on every runtime query and retrieval. It is
enforced here, in the repository layer, rather than left to a prompt.
"""

from datetime import date

import pandas as pd

from meridian.data.constants import DATASET_AS_OF_DATE


def effective_cutoff(forecast_as_of_date: date, as_of_date: date = DATASET_AS_OF_DATE) -> date:
    """Return the latest date whose records may inform a forecast for one account.

    Args:
        forecast_as_of_date: The account's own forecast date, `renewal_date - 90 days`.
        as_of_date: The global dataset horizon. Overridable only for testing.

    Returns:
        `min(forecast_as_of_date, as_of_date)`.
    """

    return min(forecast_as_of_date, as_of_date)


def filter_to_cutoff(frame: pd.DataFrame, date_column: str, cutoff: date) -> pd.DataFrame:
    """Return the rows of `frame` whose `date_column` falls on or before `cutoff`.

    Args:
        frame: Any validated fact table.
        date_column: Name of the datetime64 column to filter on.
        cutoff: Inclusive upper bound, normally from :func:`effective_cutoff`.

    Raises:
        KeyError: If `date_column` is absent, which would otherwise silently
            return unfiltered rows.
    """

    if date_column not in frame.columns:
        raise KeyError(f"cannot enforce a cutoff on missing column {date_column!r}")
    return frame.loc[frame[date_column] <= pd.Timestamp(cutoff)].copy()
