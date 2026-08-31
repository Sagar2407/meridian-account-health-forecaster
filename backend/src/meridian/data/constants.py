"""Dataset-wide constants shared by the runtime and evaluation boundaries.

These values are duplicated nowhere else. `DATASET_AS_OF_DATE` and `PROJECT_SEED`
mirror `AS_OF_DATE` and `RANDOM_SEED` in the supplied generator's `config.py`; the
manifest test asserts they still agree with the archive.
"""

from datetime import date
from typing import Final

DATASET_VERSION: Final[str] = "meridian-account-health-2026-07-21"
"""Version label of the supplied synthetic archive."""

DATASET_AS_OF_DATE: Final[date] = date(2026, 6, 28)
"""Global observation horizon. No runtime record may postdate this."""

PROJECT_SEED: Final[int] = 20260721
"""Fixed seed for every deterministic operation, including the account split."""

RUNTIME_PROFILE_FIELDS: Final[tuple[str, ...]] = (
    "account_id",
    "account_name",
    "segment",
    "industry",
    "region",
    "country",
    "employees",
    "licensed_seats",
    "acv_usd",
    "contract_term_months",
    "contract_start_date",
    "renewal_date",
    "forecast_as_of_date",
    "products_owned",
    "num_products",
    "primary_product",
    "csm_name",
    "exec_sponsor_name",
    "sponsor_status",
    "onboarding_completed",
)
"""Allowlist of account columns the runtime repository may expose (plan section 8.4).

This is an allowlist rather than a denylist so that any column added to the raw
archive later is excluded by default instead of leaking silently.
"""

FORBIDDEN_RUNTIME_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "advanced_adoption_target",
        "churn_probability",
        "health_archetype",
        "health_band",
        "health_index",
        "health_index_noised",
        "outcome",
        "outcome_date",
        "outcome_reason",
        "top_negative_drivers",
        "top_positive_drivers",
        "usage_cliff_date",
    }
)
"""Latent or outcome-bearing fields that must never reach runtime code.

`usage_cliff_date` is listed because the archive supplies it as generated truth.
A usage cliff may still be *computed* at runtime from `usage_weekly` observations
up to the cutoff; that derived value is a different field and is permitted.
"""
