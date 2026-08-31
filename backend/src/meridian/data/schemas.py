"""Declarative schemas for the raw archive (plan section 8.1).

Every table is validated on load: primary keys, foreign keys, allowed categorical
values, numeric ranges, and nullability. Validation is lazy so that a bad archive
reports every violation at once instead of only the first.

These schemas describe the archive *as supplied*, including the latent
ground-truth columns. Removing those columns is the job of the runtime
repository, not of validation.
"""

from dataclasses import dataclass

import pandera.pandas as pa

SEGMENTS = ("Strategic", "Enterprise", "Mid-Market")
REGIONS = ("NA", "EMEA", "APAC", "LATAM")
SPONSOR_STATUSES = ("strong", "stable", "new", "lost")
INDUSTRIES = (
    "Consumer Goods",
    "Financial Services",
    "Healthcare & Life Sciences",
    "Manufacturing",
    "Media & Entertainment",
    "Public Sector & Education",
    "Retail & E-commerce",
    "Technology & Software",
    "Telecommunications",
    "Travel & Hospitality",
)
PRODUCTS = (
    "Analytics",
    "Campaign",
    "Commerce",
    "Content Management",
    "Digital Asset Management",
    "Personalization",
)
TICKET_CHANNELS = ("Support Portal", "Email", "In-app", "CSM-logged")
TICKET_CATEGORIES = (
    "Billing / Licensing",
    "Bug / Defect",
    "Escalation",
    "Feature Request",
    "How-to / Usage",
    "Integration / API",
    "Onboarding / Enablement",
    "Performance / Outage",
)
TICKET_PRIORITIES = ("P1", "P2", "P3", "P4")
TICKET_STATUSES = ("Resolved", "Closed", "Open", "Pending Customer")
NOTE_TYPES = (
    "Onboarding Kickoff",
    "Monthly Touchpoint",
    "Quarterly Business Review",
    "Escalation / Save Play",
    "Renewal Prep",
    "Expansion Discussion",
)
EVENT_TYPES = (
    "Acquisition (as acquirer)",
    "Acquisition (as target)",
    "Cost-cutting initiative",
    "Earnings beat",
    "Earnings miss",
    "Executive hire (digital/CX)",
    "Funding round / capital raise",
    "Layoffs / restructuring",
    "Leadership change (CxO)",
    "New product / market launch",
    "Office relocation",
    "Partnership announcement",
    "Regulatory / compliance issue",
)
OUTCOMES = ("Churned", "Contracted", "Renewed", "Expanded")
HEALTH_ARCHETYPES = (
    "expanding",
    "onboarding_stall",
    "recovered",
    "seasonal_healthy",
    "sharp_drop",
    "slow_decline",
    "stable_healthy",
)
HEALTH_BANDS = ("thriving", "steady", "slipping", "at_risk", "stalled", "recovering")

_ACCOUNT_ID = pa.Column(str, pa.Check.str_matches(r"^ACC-\d+$"))
_SENTIMENT = pa.Column(float, pa.Check.in_range(-1.0, 1.0))
_DATE = pa.Column("datetime64[ns]")


def _categorical(allowed: tuple[str, ...]) -> pa.Column:
    """Return a string column constrained to `allowed`."""

    return pa.Column(str, pa.Check.isin(allowed))


ACCOUNTS_SCHEMA = pa.DataFrameSchema(
    {
        "account_id": pa.Column(str, pa.Check.str_matches(r"^ACC-\d+$"), unique=True),
        "account_name": pa.Column(str),
        "segment": _categorical(SEGMENTS),
        "industry": _categorical(INDUSTRIES),
        "region": _categorical(REGIONS),
        "country": pa.Column(str),
        "employees": pa.Column(int, pa.Check.gt(0)),
        "licensed_seats": pa.Column(int, pa.Check.gt(0)),
        "acv_usd": pa.Column(float, pa.Check.gt(0)),
        "contract_term_months": pa.Column(int, pa.Check.isin((12, 24, 36))),
        "contract_start_date": _DATE,
        "renewal_date": _DATE,
        "forecast_as_of_date": _DATE,
        "products_owned": pa.Column(str),
        "num_products": pa.Column(int, pa.Check.in_range(1, len(PRODUCTS))),
        "primary_product": _categorical(PRODUCTS),
        "csm_name": pa.Column(str),
        "exec_sponsor_name": pa.Column(str),
        "sponsor_status": _categorical(SPONSOR_STATUSES),
        "onboarding_completed": pa.Column(bool),
        "advanced_adoption_target": pa.Column(float, pa.Check.in_range(0.0, 1.0)),
        "health_archetype": _categorical(HEALTH_ARCHETYPES),
        "health_band": _categorical(HEALTH_BANDS),
        "usage_cliff_date": pa.Column("datetime64[ns]", nullable=True),
    },
    strict=True,
    coerce=True,
    name="accounts",
)

USAGE_WEEKLY_SCHEMA = pa.DataFrameSchema(
    {
        "account_id": _ACCOUNT_ID,
        "week_start": _DATE,
        "product": _categorical(PRODUCTS),
        "active_users": pa.Column(int, pa.Check.ge(0)),
        "sessions": pa.Column(int, pa.Check.ge(0)),
        "feature_events": pa.Column(int, pa.Check.ge(0)),
        "api_calls": pa.Column(int, pa.Check.ge(0)),
        "storage_gb": pa.Column(float, pa.Check.ge(0.0)),
        "advanced_feature_adoption_pct": pa.Column(float, pa.Check.in_range(0.0, 100.0)),
    },
    strict=True,
    coerce=True,
    unique=["account_id", "week_start", "product"],
    name="usage_weekly",
)

SUPPORT_TICKETS_SCHEMA = pa.DataFrameSchema(
    {
        "ticket_id": pa.Column(str, pa.Check.str_matches(r"^TCK-\d+$"), unique=True),
        "account_id": _ACCOUNT_ID,
        "created_date": _DATE,
        "channel": _categorical(TICKET_CHANNELS),
        "category": _categorical(TICKET_CATEGORIES),
        "priority": _categorical(TICKET_PRIORITIES),
        "status": _categorical(TICKET_STATUSES),
        "product": _categorical(PRODUCTS),
        "subject": pa.Column(str),
        "body": pa.Column(str),
        "sentiment": _SENTIMENT,
        "csat": pa.Column("Int64", pa.Check.in_range(1, 5), nullable=True),
        "resolution_hours": pa.Column(float, pa.Check.ge(0.0), nullable=True),
    },
    strict=True,
    coerce=True,
    name="support_tickets",
)

CSM_NOTES_SCHEMA = pa.DataFrameSchema(
    {
        "note_id": pa.Column(str, pa.Check.str_matches(r"^NOTE-\d+$"), unique=True),
        "account_id": _ACCOUNT_ID,
        "note_date": _DATE,
        "note_type": _categorical(NOTE_TYPES),
        "author": pa.Column(str),
        "sentiment": _SENTIMENT,
        "body": pa.Column(str),
    },
    strict=True,
    coerce=True,
    name="csm_notes",
)

EXTERNAL_EVENTS_SCHEMA = pa.DataFrameSchema(
    {
        "account_id": _ACCOUNT_ID,
        "event_date": _DATE,
        "event_type": _categorical(EVENT_TYPES),
        "polarity": pa.Column(int, pa.Check.isin((-1, 0, 1))),
        "source": pa.Column(str),
        "headline": pa.Column(str),
    },
    strict=True,
    coerce=True,
    name="external_events",
)

ACCOUNT_FEATURES_SCHEMA = pa.DataFrameSchema(
    {
        "account_id": pa.Column(str, pa.Check.str_matches(r"^ACC-\d+$"), unique=True),
        "adoption_trend_13w": pa.Column(float),
        # The data dictionary documents this as 0-100, but the archive reaches
        # 109.04. The observed scale is authoritative; the ceiling below is a
        # corruption guard, not the documented bound. See docs/DATA_LINEAGE.md.
        "adoption_level_last_q": pa.Column(float, pa.Check.in_range(0.0, 200.0)),
        "advanced_feature_depth": pa.Column(float, pa.Check.in_range(0.0, 100.0)),
        "product_breadth": pa.Column(int, pa.Check.in_range(1, len(PRODUCTS))),
        "support_escalation_rate": pa.Column(float, pa.Check.ge(0.0)),
        "avg_sentiment": _SENTIMENT,
        "avg_csat": pa.Column(float, pa.Check.in_range(1.0, 5.0)),
        "adverse_events_2q": pa.Column(int, pa.Check.ge(0)),
        "favorable_events_2q": pa.Column(int, pa.Check.ge(0)),
        "sponsor_change": pa.Column(int, pa.Check.isin((0, 1))),
        "sponsor_lost": pa.Column(int, pa.Check.isin((0, 1))),
        "onboarding_incomplete": pa.Column(int, pa.Check.isin((0, 1))),
        "days_to_renewal": pa.Column(int, pa.Check.ge(0)),
    },
    strict=True,
    coerce=True,
    name="account_features",
)

RENEWAL_OUTCOMES_SCHEMA = pa.DataFrameSchema(
    {
        "account_id": pa.Column(str, pa.Check.str_matches(r"^ACC-\d+$"), unique=True),
        "health_index": pa.Column(float),
        "churn_probability": pa.Column(float, pa.Check.in_range(0.0, 1.0)),
        "outcome": _categorical(OUTCOMES),
        "outcome_reason": pa.Column(str, nullable=False),
        "outcome_date": _DATE,
    },
    strict=True,
    coerce=True,
    name="renewal_outcomes",
)


@dataclass(frozen=True)
class TableSpec:
    """How one raw CSV is read, coerced, and validated."""

    name: str
    filename: str
    schema: pa.DataFrameSchema
    date_columns: tuple[str, ...]
    nullable_columns: tuple[str, ...] = ()
    boolean_columns: tuple[str, ...] = ()
    has_account_foreign_key: bool = True


TABLE_SPECS: tuple[TableSpec, ...] = (
    TableSpec(
        name="accounts",
        filename="accounts.csv",
        schema=ACCOUNTS_SCHEMA,
        date_columns=(
            "contract_start_date",
            "renewal_date",
            "forecast_as_of_date",
            "usage_cliff_date",
        ),
        nullable_columns=("usage_cliff_date",),
        boolean_columns=("onboarding_completed",),
        has_account_foreign_key=False,
    ),
    TableSpec(
        name="usage_weekly",
        filename="usage_weekly.csv",
        schema=USAGE_WEEKLY_SCHEMA,
        date_columns=("week_start",),
    ),
    TableSpec(
        name="support_tickets",
        filename="support_tickets.csv",
        schema=SUPPORT_TICKETS_SCHEMA,
        date_columns=("created_date",),
        nullable_columns=("csat", "resolution_hours"),
    ),
    TableSpec(
        name="csm_notes",
        filename="csm_notes.csv",
        schema=CSM_NOTES_SCHEMA,
        date_columns=("note_date",),
    ),
    TableSpec(
        name="external_events",
        filename="external_events.csv",
        schema=EXTERNAL_EVENTS_SCHEMA,
        date_columns=("event_date",),
    ),
    TableSpec(
        name="account_features",
        filename="account_features.csv",
        schema=ACCOUNT_FEATURES_SCHEMA,
        date_columns=(),
    ),
    TableSpec(
        name="renewal_outcomes",
        filename="renewal_outcomes.csv",
        schema=RENEWAL_OUTCOMES_SCHEMA,
        date_columns=("outcome_date",),
    ),
)
"""Every raw table, in load order. `accounts` must be first so it can seed the
foreign-key check applied to the fact tables."""
