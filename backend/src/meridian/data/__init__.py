"""Central, point-in-time-safe access to the Meridian account-health dataset.

Every runtime read of the dataset must go through this package. Application code
must never call :func:`pandas.read_csv` on the raw archive directly, because the
raw tables contain latent ground-truth fields and records that postdate an
account's forecast cutoff.
"""

from meridian.data.constants import (
    DATASET_AS_OF_DATE,
    DATASET_VERSION,
    FORBIDDEN_RUNTIME_FIELDS,
    PROJECT_SEED,
    RUNTIME_PROFILE_FIELDS,
)
from meridian.data.cutoff import effective_cutoff, filter_to_cutoff

__all__ = [
    "DATASET_AS_OF_DATE",
    "DATASET_VERSION",
    "FORBIDDEN_RUNTIME_FIELDS",
    "PROJECT_SEED",
    "RUNTIME_PROFILE_FIELDS",
    "effective_cutoff",
    "filter_to_cutoff",
]
